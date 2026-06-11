"""知识库相似案例检测脚本。

定期运行检查 JSONL 中是否有高度相似的案例，防止长期累积重复。

用法:
    python scripts/find_duplicate_cases.py              # 默认阈值 0.85
    python scripts/find_duplicate_cases.py --threshold 0.80  # 自定义阈值
    python scripts/find_duplicate_cases.py --json       # JSON 输出
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.kb.retriever import _cosine
from app.kb.retriever import embed_text

DEFAULT_JSONL = PROJECT_ROOT / "data" / "reverse_rule_cases.jsonl"
DEFAULT_THRESHOLD = 0.85


def load_cases(jsonl_path: Path) -> list[dict[str, Any]]:
    cases = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def find_similar_pairs(
    cases: list[dict[str, Any]], threshold: float
) -> list[dict[str, Any]]:
    """在同模块内查找相似案例对。"""
    pairs = []

    # 按模块分组（跨模块不比较）
    by_module: dict[str, list[tuple[int, dict]]] = {}
    for idx, case in enumerate(cases):
        module = case.get("review_module", "")
        by_module.setdefault(module, []).append((idx, case))

    for module, module_cases in by_module.items():
        if len(module_cases) < 2:
            continue

        for i in range(len(module_cases)):
            idx_a, case_a = module_cases[i]
            text_a = _embed_text(
                case_a.get("risk_name", "")
                + " "
                + case_a.get("check_point", "")
                + " "
                + case_a.get("trigger_condition", "")
            )
            for j in range(i + 1, len(module_cases)):
                idx_b, case_b = module_cases[j]
                text_b = _embed_text(
                    case_b.get("risk_name", "")
                    + " "
                    + case_b.get("check_point", "")
                    + " "
                    + case_b.get("trigger_condition", "")
                )
                sim = _cosine(text_a, text_b)
                if sim >= threshold:
                    pairs.append(
                        {
                            "case_a": case_a["case_id"],
                            "case_b": case_b["case_id"],
                            "module": module,
                            "risk_a": case_a.get("risk_name", ""),
                            "risk_b": case_b.get("risk_name", ""),
                            "similarity": round(sim, 4),
                        }
                    )

    pairs.sort(key=lambda p: -p["similarity"])
    return pairs


def _embed_text(text: str) -> list[float]:
    return embed_text(text)


def main():
    parser = argparse.ArgumentParser(description="知识库相似案例检测")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"相似度阈值 (默认 {DEFAULT_THRESHOLD})",
    )
    parser.add_argument("--jsonl", type=str, default=str(DEFAULT_JSONL))
    parser.add_argument("--json-output", action="store_true", help="JSON 格式输出")
    args = parser.parse_args()

    jsonl_path = Path(args.jsonl)
    if not jsonl_path.exists():
        print(f"文件不存在: {jsonl_path}")
        sys.exit(1)

    cases = load_cases(jsonl_path)
    print(f"扫描 {len(cases)} 条案例，阈值 {args.threshold}\n")

    pairs = find_similar_pairs(cases, args.threshold)

    if args.json_output:
        print(json.dumps(pairs, ensure_ascii=False, indent=2))
    else:
        if not pairs:
            print("No similar cases found. OK.")
            return

        # 按严重程度分级
        critical = [p for p in pairs if p["similarity"] >= 0.95]
        high = [p for p in pairs if 0.90 <= p["similarity"] < 0.95]
        medium = [p for p in pairs if 0.85 <= p["similarity"] < 0.90]

        print(f"Found {len(pairs)} similar pairs:")
        if critical:
            print(f"  [HIGH]   sim > 0.95: {len(critical)} pairs")
        if high:
            print(f"  [MEDIUM] sim 0.90-0.95: {len(high)} pairs")
        if medium:
            print(f"  [LOW]    sim 0.85-0.90: {len(medium)} pairs")
        print()

        for p in pairs[:20]:
            level = (
                "HIGH" if p["similarity"] >= 0.95
                else "MEDIUM" if p["similarity"] >= 0.90
                else "LOW"
            )
            print(
                f"  [{level}] sim={p['similarity']:.3f} | {p['module']} | "
                f"{p['case_a']} <-> {p['case_b']}"
            )
            print(f"         \"{p['risk_a']}\" vs \"{p['risk_b']}\"")
            print()

        if len(pairs) > 20:
            print(f"  ... {len(pairs) - 20} more pairs not shown")


if __name__ == "__main__":
    main()
