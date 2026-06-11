"""Metric helpers for audit workflow evaluation."""

from __future__ import annotations

import re
import statistics
from typing import Any

RISK_LABEL_MAP = {
    "pass": "通过",
    "high": "高风险",
    "medium": "中风险",
    "low": "低风险",
}
MISSING_CLAUSE_PHRASE = "未发现明确原文，但相关内容缺失"


def _safe_div(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _find_output_item(
    output: list[dict[str, Any]],
    expectation: dict[str, Any],
) -> dict[str, Any] | None:
    rule_code = expectation.get("rule_code") or ""
    if rule_code:
        for item in output:
            if item.get("rule_code") == rule_code:
                return item

    aliases = expectation.get("key_aliases", [])
    for item in output:
        key = str(item.get("key", ""))
        for alias in aliases:
            if alias and (alias in key or key in alias):
                return item
    return None


def schema_pass_rate(case_records: list[dict[str, Any]]) -> float | None:
    return _safe_div(
        sum(1 for record in case_records if record["schema"]["pass"]),
        len(case_records),
    )


def count_alignment_rate(case_records: list[dict[str, Any]]) -> float | None:
    return _safe_div(
        sum(
            1
            for record in case_records
            if record["schema"]["count_sum_equals_output_length"]
        ),
        len(case_records),
    )


def contract_type_accuracy(case_records: list[dict[str, Any]]) -> float | None:
    comparable = [
        record
        for record in case_records
        if record.get("predicted_contract_type") is not None
    ]
    return _safe_div(
        sum(
            1
            for record in comparable
            if record["predicted_contract_type"]
            == record["gold"]["expected_contract_type"]
        ),
        len(comparable),
    )


def output_retention_rate(case_records: list[dict[str, Any]]) -> float | None:
    comparable = [
        record
        for record in case_records
        if record.get("actual_review_rule_count") is not None
    ]
    numerator = 0
    denominator = 0
    for record in comparable:
        denominator += record["actual_review_rule_count"]
        numerator += min(record["schema"]["output_length"], record["actual_review_rule_count"])
    return _safe_div(numerator, denominator)


def risk_label_consistency_rate(case_records: list[dict[str, Any]]) -> float | None:
    total = 0
    passed = 0
    for record in case_records:
        for item in record.get("result", {}).get("output", []):
            total += 1
            if item.get("risk_label") == RISK_LABEL_MAP.get(item.get("risk")):
                passed += 1
    return _safe_div(passed, total)


def rule_code_fill_rate(case_records: list[dict[str, Any]]) -> float | None:
    total = 0
    filled = 0
    for record in case_records:
        for item in record.get("result", {}).get("output", []):
            total += 1
            if str(item.get("rule_code", "")).strip():
                filled += 1
    return _safe_div(filled, total)


def risk_accuracy(case_records: list[dict[str, Any]]) -> float | None:
    total = 0
    correct = 0
    for record in case_records:
        output = record.get("result", {}).get("output", [])
        for expectation in record["gold"].get("rule_expectations", []):
            item = _find_output_item(output, expectation)
            if item is None:
                continue
            total += 1
            if item.get("risk") == expectation.get("risk_gold"):
                correct += 1
    return _safe_div(correct, total)


def action_type_accuracy(case_records: list[dict[str, Any]]) -> float | None:
    total = 0
    correct = 0
    for record in case_records:
        output = record.get("result", {}).get("output", [])
        for expectation in record["gold"].get("rule_expectations", []):
            item = _find_output_item(output, expectation)
            if item is None:
                continue
            total += 1
            if item.get("action_type") == expectation.get("action_type_gold"):
                correct += 1
    return _safe_div(correct, total)


def key_hit_rate(case_records: list[dict[str, Any]]) -> float | None:
    total = 0
    correct = 0
    for record in case_records:
        output = record.get("result", {}).get("output", [])
        for expectation in record["gold"].get("rule_expectations", []):
            aliases = expectation.get("key_aliases", [])
            if not aliases:
                continue
            total += 1
            item = _find_output_item(output, expectation)
            if item is not None and any(alias in item.get("key", "") for alias in aliases):
                correct += 1
    return _safe_div(correct, total)


def content_quote_accuracy(case_records: list[dict[str, Any]]) -> float | None:
    total = 0
    correct = 0
    for record in case_records:
        output = record.get("result", {}).get("output", [])
        for expectation in record["gold"].get("rule_expectations", []):
            content_mode = expectation.get("content_mode_gold")
            if not content_mode:
                continue
            total += 1
            item = _find_output_item(output, expectation)
            if item is None:
                continue
            content = str(item.get("content", ""))
            anchor = expectation.get("content_anchor_optional") or ""
            if content_mode == "none" and content == "无":
                correct += 1
            elif content_mode == "missing_clause" and MISSING_CLAUSE_PHRASE in content:
                correct += 1
            elif content_mode == "quote" and anchor and anchor in content:
                correct += 1
    return _safe_div(correct, total)


def missing_clause_detection_accuracy(case_records: list[dict[str, Any]]) -> float | None:
    total = 0
    correct = 0
    for record in case_records:
        output = record.get("result", {}).get("output", [])
        for expectation in record["gold"].get("rule_expectations", []):
            if expectation.get("content_mode_gold") != "missing_clause":
                continue
            total += 1
            item = _find_output_item(output, expectation)
            if item is not None and MISSING_CLAUSE_PHRASE in str(item.get("content", "")):
                correct += 1
    return _safe_div(correct, total)


def advice_alignment_rate(case_records: list[dict[str, Any]]) -> float | None:
    total = 0
    correct = 0
    for record in case_records:
        output = record.get("result", {}).get("output", [])
        for expectation in record["gold"].get("rule_expectations", []):
            advice_expectation = expectation.get("advice_expectation") or ""
            if not advice_expectation:
                continue
            total += 1
            item = _find_output_item(output, expectation)
            if item is None:
                continue
            if advice_expectation in str(item.get("advice", "")):
                correct += 1
    return _safe_div(correct, total)


def replace_text_non_fabrication_rate(case_records: list[dict[str, Any]]) -> float | None:
    total = 0
    passed = 0
    number_pattern = re.compile(r"\d")
    for record in case_records:
        output = record.get("result", {}).get("output", [])
        for expectation in record["gold"].get("rule_expectations", []):
            if not expectation.get("must_not_invent_numbers"):
                continue
            total += 1
            item = _find_output_item(output, expectation)
            if item is None:
                continue
            replace_text = str(item.get("replace_text", ""))
            if replace_text == "无" or not number_pattern.search(replace_text):
                passed += 1
    return _safe_div(passed, total)


def false_positive_rate(case_records: list[dict[str, Any]]) -> float | None:
    standard_cases = [
        record for record in case_records if record["case"]["quality_bucket"] == "standard"
    ]
    total = 0
    false_positive = 0
    for record in standard_cases:
        for item in record.get("result", {}).get("output", []):
            total += 1
            if item.get("risk") != "pass":
                false_positive += 1
    return _safe_div(false_positive, total)


def false_negative_rate(case_records: list[dict[str, Any]]) -> float | None:
    defective_cases = [
        record for record in case_records if record["case"]["quality_bucket"] == "defective"
    ]
    total = 0
    missed = 0
    for record in defective_cases:
        output = record.get("result", {}).get("output", [])
        for expectation in record["gold"].get("rule_expectations", []):
            if not expectation.get("expected_present", False):
                continue
            total += 1
            item = _find_output_item(output, expectation)
            if item is None or item.get("risk") == "pass":
                missed += 1
    return _safe_div(missed, total)


def latency_summary(case_records: list[dict[str, Any]]) -> dict[str, float | None]:
    latencies = [record["latency_ms"] for record in case_records if record.get("latency_ms") is not None]
    if not latencies:
        return {"avg_latency_ms": None, "max_latency_ms": None}
    return {
        "avg_latency_ms": round(statistics.fmean(latencies), 2),
        "max_latency_ms": round(max(latencies), 2),
    }


def stability_summary(case_records: list[dict[str, Any]]) -> dict[str, float | None]:
    stable_presence_scores: list[float] = []
    stable_risk_scores: list[float] = []
    stable_count_scores: list[float] = []

    for record in case_records:
        runs = record.get("stability_runs", [])
        if len(runs) <= 1:
            continue

        baseline = runs[0]
        baseline_codes = [item.get("rule_code") for item in baseline.get("output", [])]
        baseline_risks = [item.get("risk") for item in baseline.get("output", [])]
        baseline_counts = tuple(baseline.get(key) for key in ("agreeCount", "highlevelriskCount", "mediumlevelriskCount", "lowlevelriskCount"))

        for run in runs[1:]:
            current_codes = [item.get("rule_code") for item in run.get("output", [])]
            current_risks = [item.get("risk") for item in run.get("output", [])]
            current_counts = tuple(run.get(key) for key in ("agreeCount", "highlevelriskCount", "mediumlevelriskCount", "lowlevelriskCount"))
            stable_presence_scores.append(1.0 if current_codes == baseline_codes else 0.0)
            stable_risk_scores.append(1.0 if current_risks == baseline_risks else 0.0)
            stable_count_scores.append(1.0 if current_counts == baseline_counts else 0.0)

    return {
        "stable_rule_presence_rate": _safe_div(
            int(sum(stable_presence_scores)),
            len(stable_presence_scores),
        ) if stable_presence_scores else None,
        "stable_risk_rate": _safe_div(
            int(sum(stable_risk_scores)),
            len(stable_risk_scores),
        ) if stable_risk_scores else None,
        "stable_count_rate": _safe_div(
            int(sum(stable_count_scores)),
            len(stable_count_scores),
        ) if stable_count_scores else None,
    }
