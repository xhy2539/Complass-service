"""Rule response adaptation and splitting."""

from __future__ import annotations

import json
import math
from typing import Any

from .schemas import parse_json_like

RULE_BUCKET_KEYS = (
    "finance_rules",
    "legal_rules",
    "performance_rules",
    "other_rules",
)


FIELD_ALIASES = {
    "rule_code": ("rule_code", "rule_id", "规则编号"),
    "contract_type": ("contract_type", "合同类型"),
    "review_module": ("review_module", "module", "审核模块"),
    "risk_name": ("risk_name", "风险名称"),
    "check_point": ("check_point", "检查点"),
    "trigger_condition": ("trigger_condition", "触发条件"),
    "default_risk_level": ("default_risk_level", "默认风险等级"),
    "suggestion_template": ("suggestion_template", "修改建议模板"),
    "example_clause": ("example_clause", "示例问题条款"),
}


def adapt_rules(rule_response: dict | str) -> dict:
    source = parse_json_like(rule_response) if isinstance(rule_response, str) else rule_response
    if not isinstance(source, dict):
        source = {}
    payload = source.get("data") if isinstance(source.get("data"), dict) else source

    buckets = {
        "finance_rules": [],
        "legal_rules": [],
        "performance_rules": [],
        "other_rules": [],
    }

    source_rules = _extract_source_rules(payload)
    for bucket_name, rules in source_rules.items():
        fallback_module = _module_from_bucket(bucket_name)
        for raw_rule in rules:
            rule = normalize_rule(raw_rule, fallback_module=fallback_module)
            target_bucket = _bucket_from_module(rule.get("review_module"))
            buckets[target_bucket].append(rule)

    deduped = {key: _deduplicate_rules(value) for key, value in buckets.items()}
    deduped["debug_info"] = {
        "finance_rules_count": len(deduped["finance_rules"]),
        "legal_rules_count": len(deduped["legal_rules"]),
        "performance_rules_count": len(deduped["performance_rules"]),
        "other_rules_count": len(deduped["other_rules"]),
    }
    return deduped


def normalize_rule(raw_rule: Any, fallback_module: str = "其他") -> dict[str, str]:
    raw = raw_rule if isinstance(raw_rule, dict) else {}
    rule_code = _pick_field(raw, FIELD_ALIASES["rule_code"])
    review_module = normalize_review_module(
        _pick_field(raw, FIELD_ALIASES["review_module"]),
        fallback=fallback_module,
    )
    return {
        "rule_code": rule_code,
        "rule_id": rule_code,
        "contract_type": _pick_field(raw, FIELD_ALIASES["contract_type"]),
        "review_module": review_module,
        "module": review_module,
        "risk_name": _pick_field(raw, FIELD_ALIASES["risk_name"]),
        "check_point": _pick_field(raw, FIELD_ALIASES["check_point"]),
        "trigger_condition": _pick_field(raw, FIELD_ALIASES["trigger_condition"]),
        "default_risk_level": _pick_field(raw, FIELD_ALIASES["default_risk_level"]),
        "suggestion_template": _pick_field(raw, FIELD_ALIASES["suggestion_template"]),
        "example_clause": _pick_field(raw, FIELD_ALIASES["example_clause"]),
    }


def normalize_review_module(value: Any, fallback: str = "其他") -> str:
    text = str(value or "").strip()
    if "财务" in text:
        return "财务"
    if "法务" in text or "法律" in text:
        return "法务"
    if "履约" in text or "履行" in text:
        return "履约"
    return fallback if fallback in {"财务", "法务", "履约", "其他"} else "其他"


def split_common_specific_rules(
    rules: list[dict],
) -> tuple[list[dict], list[dict]]:
    common_rules: list[dict] = []
    specific_rules: list[dict] = []
    for rule in rules:
        if str(rule.get("contract_type", "")).strip() == "通用":
            common_rules.append(rule)
        else:
            specific_rules.append(rule)
    return common_rules, specific_rules


def split_rules_in_half(rules: list[dict]) -> tuple[list[dict], list[dict]]:
    mid = math.ceil(len(rules) / 2)
    return rules[:mid], rules[mid:]


def split_legal_specific_rules(rules: list[dict]) -> tuple[list[dict], list[dict]]:
    return split_rules_in_half(rules)


def flatten_rules(adapted_rules: dict) -> list[dict]:
    all_rules: list[dict] = []
    for key in RULE_BUCKET_KEYS:
        bucket = adapted_rules.get(key, [])
        if isinstance(bucket, list):
            all_rules.extend(rule for rule in bucket if isinstance(rule, dict))
    return all_rules


def _extract_source_rules(payload: dict) -> dict[str, list[Any]]:
    if any(key in payload for key in RULE_BUCKET_KEYS):
        return {
            key: payload.get(key, []) if isinstance(payload.get(key, []), list) else []
            for key in RULE_BUCKET_KEYS
        }

    rules = payload.get("rules", [])
    if isinstance(rules, list):
        return {"other_rules": rules}

    return {key: [] for key in RULE_BUCKET_KEYS}


def _pick_field(raw: dict[str, Any], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        value = raw.get(alias)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _module_from_bucket(bucket_name: str) -> str:
    return {
        "finance_rules": "财务",
        "legal_rules": "法务",
        "performance_rules": "履约",
        "other_rules": "其他",
    }.get(bucket_name, "其他")


def _bucket_from_module(module: Any) -> str:
    normalized = normalize_review_module(module)
    return {
        "财务": "finance_rules",
        "法务": "legal_rules",
        "履约": "performance_rules",
    }.get(normalized, "other_rules")


def _deduplicate_rules(rules: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for rule in rules:
        rule_code = rule.get("rule_code", "")
        if rule_code:
            key = f"rule_code:{rule_code}"
        elif rule.get("risk_name"):
            key = f"risk_name:{rule['risk_name']}"
        else:
            key = json.dumps(rule, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(rule)
    return deduped
