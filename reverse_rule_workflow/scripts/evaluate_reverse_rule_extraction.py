from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.chains.reverse_rule_graph import run_reverse_rule_extraction
from app.models.reverse_rule import CandidateRuleForDB


DEFAULT_FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "reverse_rule_samples.json"
BACKEND_FIELDS = {
    "id",
    "version_id",
    "rule_code",
    "enabled",
    "created_at",
    "updated_at",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate reverse rule extraction quality.")
    parser.add_argument(
        "--fixture",
        default=str(DEFAULT_FIXTURE_PATH),
        help="Path to reverse_rule_samples.json.",
    )
    parser.add_argument(
        "--use-real-llm",
        action="store_true",
        help="Use configured real LLM credentials instead of the deterministic local stub.",
    )
    args = parser.parse_args()

    if args.use_real_llm and not _has_llm_key():
        print("未检测到真实模型 key。请配置 OPENAI_API_KEY 或 MINIMAX_API_KEY 后重试。")
        return 2
    if not args.use_real_llm:
        os.environ["DISABLE_REAL_LLM"] = "1"
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("MINIMAX_API_KEY", None)

    samples = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    rows = [evaluate_sample(sample) for sample in samples]

    print("逐样本评估结果")
    for row in rows:
        status = "PASS" if row["passed"] else "FAIL"
        print(
            f"- [{status}] {row['name']}: "
            f"生成={row['generated']} module={row['review_module_hit']} "
            f"risk={row['risk_hit']} trigger={row['trigger_hit']} "
            f"suggestion={row['suggestion_hit']} confidence={row['confidence_ok']} "
            f"schema={row['schema_ok']} backend_fields_clean={row['backend_fields_clean']}"
        )
        if row["notes"]:
            print(f"  notes: {'; '.join(row['notes'])}")

    total = len(rows)
    passed = sum(1 for row in rows if row["passed"])
    generated_accuracy = _rate(row["generation_ok"] for row in rows)
    module_hit = _rate(row["review_module_hit"] for row in rows if row["expected_generated"])
    risk_hit = _rate(row["risk_hit"] for row in rows if row["expected_generated"])
    trigger_hit = _rate(row["trigger_hit"] for row in rows if row["expected_generated"])
    suggestion_hit = _rate(row["suggestion_hit"] for row in rows if row["expected_generated"])
    schema_ok = _rate(row["schema_ok"] for row in rows if row["generated"])

    print("\nsummary")
    print(f"样本数: {total}")
    print(f"通过数: {passed}")
    print(f"是否生成规则准确率: {generated_accuracy:.2%}")
    print(f"review_module 命中率: {module_hit:.2%}")
    print(f"risk_name 关键词命中率: {risk_hit:.2%}")
    print(f"trigger_condition 关键词命中率: {trigger_hit:.2%}")
    print(f"suggestion_template 关键词命中率: {suggestion_hit:.2%}")
    print(f"CandidateRuleForDB schema 通过率: {schema_ok:.2%}")
    return 0 if passed == total else 1


def evaluate_sample(sample: dict[str, Any]) -> dict[str, Any]:
    pairs = _pairs_from_sample(sample)
    result = run_reverse_rule_extraction(pairs)
    rules = result.get("rules", [])

    expected_generated = bool(sample["should_generate_rule"])
    generated = bool(rules)
    row = {
        "name": sample["name"],
        "expected_generated": expected_generated,
        "generated": generated,
        "generation_ok": generated == expected_generated,
        "review_module_hit": False,
        "risk_hit": not expected_generated,
        "trigger_hit": not expected_generated,
        "suggestion_hit": not expected_generated,
        "example_clause_ok": not expected_generated,
        "trace_ok": not expected_generated,
        "confidence_ok": False,
        "schema_ok": not generated,
        "backend_fields_clean": True,
        "notes": [],
    }

    if not rules:
        row["confidence_ok"] = not expected_generated
        row["passed"] = all(
            [
                row["generation_ok"],
                row["confidence_ok"],
            ]
        )
        return row

    row["review_module_hit"] = any(
        rule.get("review_module") in sample["expected_review_modules"] for rule in rules
    )
    row["risk_hit"] = _any_keyword_hit(rules, "risk_name", sample["expected_risk_keywords"])
    row["trigger_hit"] = _any_keyword_hit(rules, "trigger_condition", sample["expected_trigger_keywords"])
    row["suggestion_hit"] = _any_keyword_hit(rules, "suggestion_template", sample["expected_suggestion_keywords"])
    row["example_clause_ok"] = all(bool(rule.get("example_clause", "").strip()) for rule in rules)
    row["trace_ok"] = all(
        rule.get("traces")
        and all(
            trace.get("evidence_before", "").strip()
            and trace.get("evidence_after", "").strip()
            for trace in rule["traces"]
        )
        for rule in rules
    )
    row["schema_ok"] = _all_schema_valid(rules)
    row["backend_fields_clean"] = all(BACKEND_FIELDS.isdisjoint(rule) for rule in rules)

    confidences = [
        trace.get("confidence", 0)
        for rule in rules
        for trace in rule.get("traces", [])
    ]
    if "min_confidence" in sample:
        row["confidence_ok"] = bool(confidences) and min(confidences) >= sample["min_confidence"]
    elif "max_confidence" in sample:
        row["confidence_ok"] = not confidences or max(confidences) <= sample["max_confidence"]
    else:
        row["confidence_ok"] = True

    checks = [
        "generation_ok",
        "review_module_hit",
        "risk_hit",
        "trigger_hit",
        "suggestion_hit",
        "example_clause_ok",
        "trace_ok",
        "confidence_ok",
        "schema_ok",
        "backend_fields_clean",
    ]
    row["passed"] = all(row[check] for check in checks)
    row["notes"] = [check for check in checks if not row[check]]
    return row


def _pairs_from_sample(sample: dict[str, Any]) -> list[dict[str, Any]]:
    before_parts = sample["before_text"].split("\n---PAIR---\n")
    after_parts = sample["after_text"].split("\n---PAIR---\n")
    return [
        {
            "pair_id": f"pair-{index}",
            "before_text": before_text,
            "after_text": after_parts[index - 1],
            "contract_type": sample["contract_type"],
            "review_role": sample["review_role"],
        }
        for index, before_text in enumerate(before_parts, start=1)
    ]


def _any_keyword_hit(rules: list[dict[str, Any]], field: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    return any(
        any(keyword in str(rule.get(field, "")) for keyword in keywords)
        for rule in rules
    )


def _all_schema_valid(rules: list[dict[str, Any]]) -> bool:
    for rule in rules:
        try:
            CandidateRuleForDB.model_validate(rule)
        except Exception:
            return False
    return True


def _rate(values: Any) -> float:
    items = list(values)
    if not items:
        return 1.0
    return sum(1 for item in items if item) / len(items)


def _has_llm_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("MINIMAX_API_KEY"))


if __name__ == "__main__":
    raise SystemExit(main())
