"""Dataset evaluation runner for the audit workflow."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import contract_audit_workflow.audit_workflow as workflow
from contract_audit_workflow import audit_contract
from contract_audit_workflow.evaluation.metrics import action_type_accuracy
from contract_audit_workflow.evaluation.metrics import advice_alignment_rate
from contract_audit_workflow.evaluation.metrics import content_quote_accuracy
from contract_audit_workflow.evaluation.metrics import contract_type_accuracy
from contract_audit_workflow.evaluation.metrics import count_alignment_rate
from contract_audit_workflow.evaluation.metrics import false_negative_rate
from contract_audit_workflow.evaluation.metrics import false_positive_rate
from contract_audit_workflow.evaluation.metrics import key_hit_rate
from contract_audit_workflow.evaluation.metrics import latency_summary
from contract_audit_workflow.evaluation.metrics import missing_clause_detection_accuracy
from contract_audit_workflow.evaluation.metrics import output_retention_rate
from contract_audit_workflow.evaluation.metrics import replace_text_non_fabrication_rate
from contract_audit_workflow.evaluation.metrics import risk_accuracy
from contract_audit_workflow.evaluation.metrics import risk_label_consistency_rate
from contract_audit_workflow.evaluation.metrics import rule_code_fill_rate
from contract_audit_workflow.evaluation.metrics import schema_pass_rate
from contract_audit_workflow.evaluation.metrics import stability_summary
from contract_audit_workflow.evaluation.schema_checks import validate_audit_result
from contract_audit_workflow.rule_adapter import adapt_rules

EVAL_ROOT = Path(__file__).resolve().parent
CASES_ROOT = EVAL_ROOT / "cases"
GOLD_ROOT = EVAL_ROOT / "gold"
INDEX_FILE = CASES_ROOT / "index.json"
STABILITY_RUNS = max(1, int(os.getenv("AUDIT_EVAL_STABILITY_RUNS", "1")))
CASE_LIMIT = max(0, int(os.getenv("AUDIT_EVAL_CASE_LIMIT", "0")))
CASE_TIMEOUT_SECONDS = max(1, int(os.getenv("AUDIT_EVAL_CASE_TIMEOUT_SECONDS", "300")))


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _review_rule_count(adapted_rules: dict[str, Any]) -> int:
    return (
        len(adapted_rules.get("finance_rules", []))
        + len(adapted_rules.get("legal_rules", []))
        + len(adapted_rules.get("performance_rules", []))
    )


async def _execute_case(case: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    original_classify = workflow.classify_contract_type
    original_fetch = workflow.fetch_audit_rules
    capture: dict[str, Any] = {
        "predicted_contract_type": None,
        "actual_review_rule_count": None,
    }

    async def classify_with_capture(content: str) -> str:
        predicted = await original_classify(content)
        capture["predicted_contract_type"] = predicted
        return predicted

    async def fetch_with_capture(contract_type: str) -> dict[str, Any]:
        response = await original_fetch(contract_type)
        adapted = adapt_rules(response)
        capture["actual_review_rule_count"] = _review_rule_count(adapted)
        return response

    workflow.classify_contract_type = classify_with_capture
    workflow.fetch_audit_rules = fetch_with_capture

    started_at = time.perf_counter()
    error: str | None = None
    result: dict[str, Any] | None = None
    schema: dict[str, Any] | None = None
    stability_runs: list[dict[str, Any]] = []

    try:
        result = await asyncio.wait_for(
            audit_contract(case["input_text"]),
            timeout=CASE_TIMEOUT_SECONDS,
        )
        schema = validate_audit_result(result)
        stability_runs.append(result)
        for _ in range(STABILITY_RUNS - 1):
            rerun = await asyncio.wait_for(
                audit_contract(case["input_text"]),
                timeout=CASE_TIMEOUT_SECONDS,
            )
            stability_runs.append(rerun)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        workflow.classify_contract_type = original_classify
        workflow.fetch_audit_rules = original_fetch

    latency_ms = round((time.perf_counter() - started_at) * 1000, 2)

    if result is None:
        result = {
            "agreeCount": "0",
            "highlevelriskCount": "0",
            "mediumlevelriskCount": "0",
            "lowlevelriskCount": "0",
            "output": [],
        }
        schema = validate_audit_result(result)
        schema["pass"] = False
        schema["count_sum_equals_output_length"] = False
        schema["issues"].append("execution_error")

    assert schema is not None

    return {
        "case": case,
        "gold": gold,
        "result": result,
        "schema": schema,
        "latency_ms": latency_ms,
        "predicted_contract_type": capture["predicted_contract_type"],
        "actual_review_rule_count": capture["actual_review_rule_count"],
        "stability_runs": stability_runs,
        "error": error,
    }


def _print_case(record: dict[str, Any]) -> None:
    print(
        json.dumps(
            {
                "case_id": record["case"]["case_id"],
                "contract_type_expected": record["case"]["contract_type_expected"],
                "predicted_contract_type": record["predicted_contract_type"],
                "output_length": record["schema"]["output_length"],
                "count_sum": record["schema"]["count_sum"],
                "schema_pass": record["schema"]["pass"],
                "latency_ms": record["latency_ms"],
                "error": record["error"],
            },
            ensure_ascii=False,
        )
    )


def _build_summary(case_records: list[dict[str, Any]]) -> dict[str, Any]:
    latency = latency_summary(case_records)
    stability = stability_summary(case_records)
    return {
        "case_count": len(case_records),
        "schema_pass_rate": schema_pass_rate(case_records),
        "count_alignment_rate": count_alignment_rate(case_records),
        "contract_type_accuracy": contract_type_accuracy(case_records),
        "output_retention_rate": output_retention_rate(case_records),
        "risk_label_consistency_rate": risk_label_consistency_rate(case_records),
        "rule_code_fill_rate": rule_code_fill_rate(case_records),
        "risk_accuracy": risk_accuracy(case_records),
        "key_hit_rate": key_hit_rate(case_records),
        "content_quote_accuracy": content_quote_accuracy(case_records),
        "missing_clause_detection_accuracy": missing_clause_detection_accuracy(case_records),
        "advice_alignment_rate": advice_alignment_rate(case_records),
        "replace_text_non_fabrication_rate": replace_text_non_fabrication_rate(case_records),
        "action_type_accuracy": action_type_accuracy(case_records),
        "false_positive_rate": false_positive_rate(case_records),
        "false_negative_rate": false_negative_rate(case_records),
        "avg_latency_ms": latency["avg_latency_ms"],
        "max_latency_ms": latency["max_latency_ms"],
        "stable_rule_presence_rate": stability["stable_rule_presence_rate"],
        "stable_risk_rate": stability["stable_risk_rate"],
        "stable_count_rate": stability["stable_count_rate"],
        "error_count": sum(1 for record in case_records if record["error"] is not None),
    }


async def main() -> None:
    index_data = _load_json(INDEX_FILE)
    case_entries = index_data["cases"]
    if CASE_LIMIT:
        case_entries = case_entries[:CASE_LIMIT]
    case_records: list[dict[str, Any]] = []

    for item in case_entries:
        case = _load_json(CASES_ROOT / item["case_file"])
        gold = _load_json(GOLD_ROOT / item["gold_file"])
        record = await _execute_case(case, gold)
        case_records.append(record)
        _print_case(record)
        sys.stdout.flush()

    print(json.dumps({"summary": _build_summary(case_records)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
