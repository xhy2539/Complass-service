"""RAG 检索质量评估脚本。

用法:
    python scripts/evaluate_rag_retrieval.py              # 本地检索评估
    python scripts/evaluate_rag_retrieval.py --rag         # RAG 服务评估（需服务运行）
    python scripts/evaluate_rag_retrieval.py --all         # 全部评估
    python scripts/evaluate_rag_retrieval.py --report      # 输出详细报告
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# 测试集构建
# ---------------------------------------------------------------------------


def build_self_retrieval_test_set() -> list[dict[str, Any]]:
    """用每条案例自身字段构建查询，期望召回自己。"""
    jsonl_path = PROJECT_ROOT / "data" / "reverse_rule_cases.jsonl"
    if not jsonl_path.exists():
        jsonl_path = Path("data/reverse_rule_cases.jsonl")

    cases = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    test_set = []
    for case in cases:
        # 多种查询变体
        queries = [
            f"{case['review_module']} {case['change_pattern']}",
            f"{case['review_module']} {case['risk_name']} {case['diff_summary']}",
            f"{case['contract_type'][0]} {case['review_module']} {case['change_pattern']}",
        ]
        test_set.append(
            {
                "case_id": case["case_id"],
                "review_module": case["review_module"],
                "contract_type": case.get("contract_type", [None])[0],
                "queries": queries,
                "relevant_ids": [case["case_id"]],  # 至少应召回自己
            }
        )

    return test_set


def build_cross_retrieval_test_set() -> list[dict[str, Any]]:
    """跨案例检索测试：同一模块下相似案例应互相召回。"""
    jsonl_path = PROJECT_ROOT / "data" / "reverse_rule_cases.jsonl"
    if not jsonl_path.exists():
        jsonl_path = Path("data/reverse_rule_cases.jsonl")

    cases = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    # 按模块分组
    by_module: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        by_module[case["review_module"]].append(case)

    test_set = []
    # 对有多条案例的模块，用一条查其他条
    for module, module_cases in by_module.items():
        if len(module_cases) < 2:
            continue
        for i, case_a in enumerate(module_cases):
            # 用 case_a 的 change_pattern 查询，期望召回同模块其他案例
            query = f"{module} {case_a['change_pattern']} {case_a['risk_name']}"
            relevant = [c["case_id"] for j, c in enumerate(module_cases) if j != i][:3]
            test_set.append(
                {
                    "case_id": case_a["case_id"],
                    "review_module": module,
                    "contract_type": case_a.get("contract_type", [None])[0],
                    "queries": [query],
                    "relevant_ids": relevant,
                }
            )

    return test_set


# ---------------------------------------------------------------------------
# 评估指标计算
# ---------------------------------------------------------------------------


def recall_at_k(results: list[str], relevant: list[str], k: int) -> float:
    """Top-K 结果中相关案例的召回比例。"""
    if not relevant:
        return 1.0
    top_k_ids = set(results[:k])
    found = sum(1 for rid in relevant if rid in top_k_ids)
    return found / len(relevant)


def mrr(results: list[str], relevant: list[str]) -> float:
    """Mean Reciprocal Rank：第一个相关案例的排名倒数。"""
    relevant_set = set(relevant)
    for i, rid in enumerate(results):
        if rid in relevant_set:
            return 1.0 / (i + 1)
    return 0.0


def hit_rate(results: list[str], relevant: list[str]) -> float:
    """Top-K 中至少命中一条的比例。"""
    relevant_set = set(relevant)
    return 1.0 if any(rid in relevant_set for rid in results) else 0.0


# ---------------------------------------------------------------------------
# 评估执行
# ---------------------------------------------------------------------------


def evaluate_local(test_set: list[dict[str, Any]], k: int = 5) -> dict[str, Any]:
    """用本地检索器评估。"""
    from app.kb.retriever import retrieve_reverse_rule_cases

    metrics = _run_evaluation(test_set, k, retriever_fn=retrieve_reverse_rule_cases)
    metrics["retriever"] = "local"
    return metrics


def evaluate_rag(test_set: list[dict[str, Any]], k: int = 5) -> dict[str, Any]:
    """用 RAG 服务评估。"""
    from app.kb.rag_client import rag_search

    def rag_retrieve(query, review_module=None, contract_type=None, **kw):
        return rag_search(
            query=query,
            review_module=review_module,
            contract_type=contract_type,
            top_k=k,
        )

    metrics = _run_evaluation(test_set, k, retriever_fn=rag_retrieve)
    metrics["retriever"] = "rag_service"
    return metrics


def _run_evaluation(
    test_set: list[dict[str, Any]],
    k: int,
    retriever_fn: Any,
) -> dict[str, Any]:
    """通用评估执行器。"""
    total = len(test_set)
    recall_scores = {1: [], 3: [], 5: []}
    mrr_scores = []
    hit_scores = {1: [], 3: [], 5: []}
    latencies = []
    errors = 0

    # 按模块统计
    module_stats: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "recall5": [], "hit5": 0}
    )

    for item in test_set:
        query = item["queries"][0]  # 用第一个查询
        relevant = item["relevant_ids"]
        review_module = item.get("review_module")
        contract_type = item.get("contract_type")

        try:
            start = time.monotonic()
            results = retriever_fn(
                query=query,
                review_module=review_module,
                contract_type=contract_type,
                k=k,
            )
            elapsed = time.monotonic() - start
            latencies.append(elapsed)

            # 提取 case_id
            result_ids = []
            for r in results:
                if isinstance(r, dict):
                    result_ids.append(r.get("case_id", ""))
                elif hasattr(r, "case_id"):
                    result_ids.append(r.case_id)
                else:
                    result_ids.append(str(r))

            # 计算指标
            for _k in [1, 3, 5]:
                recall_scores[_k].append(recall_at_k(result_ids, relevant, _k))
                hit_scores[_k].append(hit_rate(result_ids[:_k], relevant))
            mrr_scores.append(mrr(result_ids, relevant))

            # 模块统计
            module = item.get("review_module", "unknown")
            module_stats[module]["total"] += 1
            module_stats[module]["recall5"].append(recall_at_k(result_ids, relevant, 5))
            if hit_rate(result_ids[:5], relevant) > 0:
                module_stats[module]["hit5"] += 1

        except Exception:
            errors += 1

    # 汇总
    def _avg(lst):
        return sum(lst) / len(lst) if lst else 0.0

    def _pct(lst):
        return sum(1 for v in lst if v > 0) / len(lst) if lst else 0.0

    # 模块 Breakdown
    module_breakdown = {}
    for mod, stats in sorted(module_stats.items()):
        module_breakdown[mod] = {
            "total": stats["total"],
            "recall@5": round(_avg(stats["recall5"]), 3),
            "hit@5": round(stats["hit5"] / stats["total"], 3) if stats["total"] else 0,
        }

    return {
        "total_queries": total,
        "errors": errors,
        "recall@1": round(_avg(recall_scores[1]), 3),
        "recall@3": round(_avg(recall_scores[3]), 3),
        "recall@5": round(_avg(recall_scores[5]), 3),
        "hit@1": round(_pct(hit_scores[1]), 3),
        "hit@3": round(_pct(hit_scores[3]), 3),
        "hit@5": round(_pct(hit_scores[5]), 3),
        "mrr": round(_avg(mrr_scores), 3),
        "latency_avg_ms": round(_avg(latencies) * 1000, 1),
        "latency_p95_ms": round(_percentile(latencies, 95) * 1000, 1),
        "modules": module_breakdown,
    }


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    return sorted_data[min(idx, len(sorted_data) - 1)]


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------


def print_report(metrics: dict[str, Any], title: str = "RAG 检索评估报告"):
    """打印格式化评估报告。"""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")
    print(f"  检索器:       {metrics.get('retriever', 'unknown')}")
    print(f"  总查询数:     {metrics['total_queries']}")
    print(f"  错误数:       {metrics['errors']}")
    print()
    print("  ┌──────────┬────────┬────────┐")
    print("  │ 指标     │  值    │  评级  │")
    print("  ├──────────┼────────┼────────┤")
    _print_metric_row("Recall@1", metrics["recall@1"], 0.7, 0.5)
    _print_metric_row("Recall@3", metrics["recall@3"], 0.85, 0.7)
    _print_metric_row("Recall@5", metrics["recall@5"], 0.95, 0.8)
    _print_metric_row("Hit@3", metrics["hit@3"], 0.9, 0.75)
    _print_metric_row("MRR", metrics["mrr"], 0.8, 0.6)
    print("  └──────────┴────────┴────────┘")
    print()
    print(
        f"  延迟:  avg={metrics['latency_avg_ms']:.1f}ms  p95={metrics['latency_p95_ms']:.1f}ms"
    )
    print()

    # 模块 Breakdown
    if metrics.get("modules"):
        print(f"  {'模块':<20} {'总数':<6} {'Recall@5':<10} {'Hit@5':<8}")
        print(f"  {'-' * 44}")
        for mod, stats in sorted(
            metrics["modules"].items(), key=lambda x: -x[1]["total"]
        ):
            recall_bar = _bar(stats["recall@5"])
            print(
                f"  {mod:<20} {stats['total']:<6} {stats['recall@5']:<10.3f} {stats['hit@5']:<8.3f} {recall_bar}"
            )

    print(f"\n{'=' * 60}\n")


def _print_metric_row(name: str, value: float, good: float, ok: float):
    if value >= good:
        rating = "🟢 优"
    elif value >= ok:
        rating = "🟡 可"
    else:
        rating = "🔴 差"
    print(f"  │ {name:<8} │ {value:<6.3f} │ {rating:<6} │")


def _bar(value: float, width: int = 15) -> str:
    filled = int(value * width)
    return "█" * filled + "░" * (width - filled)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(description="RAG 检索质量评估")
    parser.add_argument(
        "--local", action="store_true", default=True, help="评估本地检索器"
    )
    parser.add_argument(
        "--rag", action="store_true", help="评估 RAG 服务（需服务运行）"
    )
    parser.add_argument("--all", action="store_true", help="全部评估")
    parser.add_argument("--self-only", action="store_true", help="仅自检索测试")
    parser.add_argument("--report", action="store_true", default=True, help="输出报告")
    parser.add_argument("--json-output", type=str, help="输出 JSON 报告到文件")
    args = parser.parse_args()

    # 构建测试集
    print("构建测试集...")
    self_test = build_self_retrieval_test_set()
    cross_test = build_cross_retrieval_test_set()
    test_set = self_test + cross_test
    print(f"  自检索: {len(self_test)} 条查询")
    print(f"  跨检索: {len(cross_test)} 条查询")
    print(f"  合计:   {len(test_set)} 条查询")

    all_metrics = {}

    if args.local or args.all:
        print("\n运行本地检索评估...")
        metrics = evaluate_local(test_set)
        all_metrics["local"] = metrics
        if args.report:
            print_report(metrics, "本地检索评估")

    if args.rag or args.all:
        print("\n运行 RAG 服务评估...")
        try:
            metrics = evaluate_rag(test_set)
            all_metrics["rag"] = metrics
            if args.report:
                print_report(metrics, "RAG 服务评估")
        except Exception as e:
            print(f"  RAG 服务不可用: {e}")

    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as f:
            json.dump(all_metrics, f, ensure_ascii=False, indent=2)
        print(f"\n报告已保存到: {args.json_output}")


if __name__ == "__main__":
    main()
