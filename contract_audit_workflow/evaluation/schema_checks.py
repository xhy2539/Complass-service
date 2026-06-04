"""Schema checks for audit workflow evaluation."""

from __future__ import annotations

from typing import Any


TOP_LEVEL_FIELDS = {
    "agreeCount",
    "highlevelriskCount",
    "mediumlevelriskCount",
    "lowlevelriskCount",
    "output",
}
OUTPUT_FIELDS = {
    "rule_code",
    "risk",
    "risk_label",
    "action_type",
    "key",
    "tip",
    "content",
    "advice",
    "replace_text",
}
COUNT_KEYS = (
    "agreeCount",
    "highlevelriskCount",
    "mediumlevelriskCount",
    "lowlevelriskCount",
)
ALLOWED_RISKS = {"pass", "high", "medium", "low"}
RISK_LABEL_MAP = {
    "pass": "通过",
    "high": "高风险",
    "medium": "中风险",
    "low": "低风险",
}
ALLOWED_ACTION_TYPES = {"manual", "append", "insert", "replace"}


def count_sum(result: dict[str, Any]) -> int:
    return sum(int(result[key]) for key in COUNT_KEYS)


def validate_audit_result(result: Any) -> dict[str, Any]:
    issues: list[str] = []

    if not isinstance(result, dict):
        return {
            "pass": False,
            "issues": ["result is not a dict"],
            "output_length": 0,
            "count_sum": 0,
            "count_sum_equals_output_length": False,
            "top_level_fields_ok": False,
            "count_types_ok": False,
            "output_is_list": False,
            "item_fields_ok": False,
            "risk_values_ok": False,
            "risk_label_consistency_ok": False,
            "action_type_values_ok": False,
        }

    top_level_fields_ok = set(result.keys()) == TOP_LEVEL_FIELDS
    if not top_level_fields_ok:
        issues.append("top_level_fields_mismatch")

    count_types_ok = all(isinstance(result.get(key), str) for key in COUNT_KEYS)
    if not count_types_ok:
        issues.append("count_fields_not_string")

    output = result.get("output")
    output_is_list = isinstance(output, list)
    if not output_is_list:
        issues.append("output_not_list")
        output = []

    output_length = len(output)

    try:
        result_count_sum = count_sum(result)
        count_sum_equals_output_length = result_count_sum == output_length
        if not count_sum_equals_output_length:
            issues.append("count_sum_mismatch")
    except Exception:
        result_count_sum = 0
        count_sum_equals_output_length = False
        issues.append("count_sum_not_computable")

    item_fields_ok = True
    risk_values_ok = True
    risk_label_consistency_ok = True
    action_type_values_ok = True

    for index, item in enumerate(output):
        if not isinstance(item, dict):
            issues.append(f"output_item_{index}_not_dict")
            item_fields_ok = False
            risk_values_ok = False
            risk_label_consistency_ok = False
            action_type_values_ok = False
            continue

        if set(item.keys()) != OUTPUT_FIELDS:
            issues.append(f"output_item_{index}_fields_mismatch")
            item_fields_ok = False

        risk = item.get("risk")
        if risk not in ALLOWED_RISKS:
            issues.append(f"output_item_{index}_risk_invalid")
            risk_values_ok = False

        if risk in RISK_LABEL_MAP and item.get("risk_label") != RISK_LABEL_MAP[risk]:
            issues.append(f"output_item_{index}_risk_label_mismatch")
            risk_label_consistency_ok = False

        if item.get("action_type") not in ALLOWED_ACTION_TYPES:
            issues.append(f"output_item_{index}_action_type_invalid")
            action_type_values_ok = False

    return {
        "pass": not issues,
        "issues": issues,
        "output_length": output_length,
        "count_sum": result_count_sum,
        "count_sum_equals_output_length": count_sum_equals_output_length,
        "top_level_fields_ok": top_level_fields_ok,
        "count_types_ok": count_types_ok,
        "output_is_list": output_is_list,
        "item_fields_ok": item_fields_ok,
        "risk_values_ok": risk_values_ok,
        "risk_label_consistency_ok": risk_label_consistency_ok,
        "action_type_values_ok": action_type_values_ok,
    }
