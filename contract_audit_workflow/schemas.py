"""Shared constants, errors, and normalization helpers."""

from __future__ import annotations

import json
import re
from typing import Any

REVIEW_ITEM_KEYS = ("risk", "key", "tip", "content", "advice", "replace_text")
FINAL_ITEM_KEYS = (
    "rule_code",
    "risk",
    "risk_label",
    "action_type",
    "key",
    "tip",
    "content",
    "advice",
    "replace_text",
)
COUNT_KEYS = (
    "agreeCount",
    "highlevelriskCount",
    "mediumlevelriskCount",
    "lowlevelriskCount",
)
FINAL_RISK_LABELS = {
    "high": "高风险",
    "medium": "中风险",
    "low": "低风险",
    "pass": "通过",
}


class ContractAuditWorkflowError(RuntimeError):
    """Base error for the contract audit workflow."""


class LLMConfigError(ContractAuditWorkflowError):
    """Raised when LLM configuration is missing or unsupported."""


class LLMRequestError(ContractAuditWorkflowError):
    """Raised when the LLM request fails."""


class LLMOutputError(ContractAuditWorkflowError):
    """Raised when the LLM output cannot be parsed or validated."""


class RulesFetchError(ContractAuditWorkflowError):
    """Raised when audit rules cannot be fetched."""


def empty_review_result() -> dict[str, Any]:
    return {
        "output": [],
        "agreeCount": "0",
        "highlevelriskCount": "0",
        "mediumlevelriskCount": "0",
        "lowlevelriskCount": "0",
    }


def empty_final_result() -> dict[str, Any]:
    return {
        "agreeCount": "0",
        "highlevelriskCount": "0",
        "mediumlevelriskCount": "0",
        "lowlevelriskCount": "0",
        "output": [],
    }


def ensure_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def preview_text(value: Any, limit: int = 1000) -> str:
    text = ensure_str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...(truncated)"


def strip_markdown_code_fence(text: str) -> str:
    value = text.strip()
    fence_match = re.fullmatch(
        r"```(?:json|JSON)?\s*(.*?)\s*```",
        value,
        flags=re.DOTALL,
    )
    if fence_match:
        return fence_match.group(1).strip()
    fence_search = re.search(
        r"```(?:json|JSON)?\s*(.*?)\s*```",
        value,
        flags=re.DOTALL,
    )
    if fence_search:
        return fence_search.group(1).strip()
    return value


def parse_json_like(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        raise LLMOutputError("LLM output is empty.")

    text = strip_markdown_code_fence(str(value))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    object_start = text.find("{")
    object_end = text.rfind("}")
    if object_start != -1 and object_end > object_start:
        try:
            return json.loads(text[object_start : object_end + 1])
        except json.JSONDecodeError:
            pass

    array_start = text.find("[")
    array_end = text.rfind("]")
    if array_start != -1 and array_end > array_start:
        try:
            return json.loads(text[array_start : array_end + 1])
        except json.JSONDecodeError:
            pass

    raise LLMOutputError(
        "LLM output is not valid JSON. "
        f"raw_preview={preview_text(value)!r} "
        f"cleaned_preview={preview_text(text)!r}"
    )


def normalize_intermediate_risk(value: Any) -> str:
    risk = ensure_str(value, "通过").lower().replace(" ", "")
    if risk in {"high", "高", "高风险"} or "高风险" in risk:
        return "高风险"
    if risk in {"medium", "mid", "中", "中风险"} or "中风险" in risk:
        return "中风险"
    if risk in {"low", "低", "低风险"} or "低风险" in risk:
        return "低风险"
    if risk in {"pass", "passed", "通过"} or "通过" in risk:
        return "通过"
    return "通过"


def normalize_final_risk(value: Any) -> tuple[str, str]:
    risk = ensure_str(value, "pass").lower().replace(" ", "")
    if risk in {"high", "高", "高风险"} or "高风险" in risk:
        return "high", FINAL_RISK_LABELS["high"]
    if risk in {"medium", "mid", "中", "中风险"} or "中风险" in risk:
        return "medium", FINAL_RISK_LABELS["medium"]
    if risk in {"low", "低", "低风险"} or "低风险" in risk:
        return "low", FINAL_RISK_LABELS["low"]
    if risk in {"pass", "passed", "通过"} or "通过" in risk:
        return "pass", FINAL_RISK_LABELS["pass"]
    return "pass", FINAL_RISK_LABELS["pass"]


def normalize_review_item(
    item: Any,
    rule: dict[str, Any] | None = None,
) -> dict[str, str]:
    raw_item = item if isinstance(item, dict) else {}
    rule = rule or {}
    risk = normalize_intermediate_risk(raw_item.get("risk"))
    default_key = ensure_str(rule.get("risk_name")) or ensure_str(rule.get("check_point"))
    normalized = {
        "risk": risk,
        "key": ensure_str(raw_item.get("key"), default_key),
        "tip": ensure_str(raw_item.get("tip"), "无"),
        "content": ensure_str(raw_item.get("content"), "无"),
        "advice": ensure_str(raw_item.get("advice"), "无"),
        "replace_text": ensure_str(raw_item.get("replace_text"), "无"),
    }
    for code_key in ("rule_code", "rule_id"):
        code_value = ensure_str(raw_item.get(code_key)) or ensure_str(rule.get(code_key))
        if code_value:
            normalized[code_key] = code_value
    return normalized


def normalize_review_result(
    raw_result: Any,
    expected_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if isinstance(raw_result, str):
        raw_result = parse_json_like(raw_result)
    if isinstance(raw_result, list):
        raw_result = {"output": raw_result}
    if not isinstance(raw_result, dict):
        raw_result = {}

    output = raw_result.get("output", [])
    if not isinstance(output, list):
        output = []

    normalized_output = []
    for index, item in enumerate(output):
        rule = expected_rules[index] if expected_rules and index < len(expected_rules) else None
        normalized_output.append(normalize_review_item(item, rule))

    result = {"output": normalized_output}
    result.update(count_intermediate_items(normalized_output))
    return result


def count_intermediate_items(items: list[dict[str, Any]]) -> dict[str, str]:
    counts = {
        "agreeCount": 0,
        "highlevelriskCount": 0,
        "mediumlevelriskCount": 0,
        "lowlevelriskCount": 0,
    }
    for item in items:
        risk = normalize_intermediate_risk(item.get("risk"))
        if risk == "高风险":
            counts["highlevelriskCount"] += 1
        elif risk == "中风险":
            counts["mediumlevelriskCount"] += 1
        elif risk == "低风险":
            counts["lowlevelriskCount"] += 1
        else:
            counts["agreeCount"] += 1
    return {key: str(value) for key, value in counts.items()}


def count_final_items(items: list[dict[str, Any]]) -> dict[str, str]:
    counts = {
        "agreeCount": 0,
        "highlevelriskCount": 0,
        "mediumlevelriskCount": 0,
        "lowlevelriskCount": 0,
    }
    for item in items:
        risk, _ = normalize_final_risk(item.get("risk"))
        if risk == "high":
            counts["highlevelriskCount"] += 1
        elif risk == "medium":
            counts["mediumlevelriskCount"] += 1
        elif risk == "low":
            counts["lowlevelriskCount"] += 1
        else:
            counts["agreeCount"] += 1
    return {key: str(value) for key, value in counts.items()}
