"""Expanded local validation for the standalone audit workflow."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
import sys
from typing import Any, Callable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import contract_audit_workflow.audit_workflow as workflow


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
ALLOWED_RISKS = {"pass", "high", "medium", "low"}
RISK_LABEL_MAP = {
    "pass": "通过",
    "high": "高风险",
    "medium": "中风险",
    "low": "低风险",
}
ALLOWED_ACTION_TYPES = {"manual", "append", "insert", "replace"}
COUNT_KEYS = (
    "agreeCount",
    "highlevelriskCount",
    "mediumlevelriskCount",
    "lowlevelriskCount",
)


def _make_rule(
    rule_code: str,
    review_module: str,
    contract_type: str = "采购合同",
    risk_name: str | None = None,
) -> dict[str, str]:
    return {
        "rule_code": rule_code,
        "rule_id": rule_code,
        "contract_type": contract_type,
        "review_module": review_module,
        "risk_name": risk_name or rule_code.lower(),
        "check_point": f"{rule_code.lower()}_check",
        "trigger_condition": f"{rule_code.lower()}_trigger",
        "default_risk_level": "低",
        "suggestion_template": f"{rule_code.lower()}_suggestion",
        "example_clause": "",
    }


async def _fake_classify_contract_type(content: str) -> str:
    return "采购合同"


def _make_fetcher(rule_payload: dict[str, list[dict[str, str]]]) -> Callable[[str], Any]:
    async def _fetch(contract_type: str) -> dict[str, Any]:
        return {
            "finance_rules": list(rule_payload.get("finance_rules", [])),
            "legal_rules": list(rule_payload.get("legal_rules", [])),
            "performance_rules": list(rule_payload.get("performance_rules", [])),
            "other_rules": list(rule_payload.get("other_rules", [])),
        }

    return _fetch


def _make_review_stub(
    builder: Callable[[str, list[dict[str, Any]], str], list[dict[str, str]]]
) -> Callable[[str, list[dict[str, Any]], str], Any]:
    async def _review(
        module: str,
        rules: list[dict[str, Any]],
        clean_contract_text: str,
    ) -> dict[str, Any]:
        return {
            "output": builder(module, rules, clean_contract_text),
            "agreeCount": "0",
            "highlevelriskCount": "0",
            "mediumlevelriskCount": "0",
            "lowlevelriskCount": "0",
        }

    return _review


def _count_sum(result: dict[str, Any]) -> int:
    return sum(int(result[key]) for key in COUNT_KEYS)


def _assert_common_contract(result: dict[str, Any]) -> None:
    assert set(result.keys()) == TOP_LEVEL_FIELDS
    assert all(isinstance(result[key], str) for key in COUNT_KEYS)
    assert isinstance(result["output"], list)
    assert _count_sum(result) == len(result["output"])

    for item in result["output"]:
        assert set(item.keys()) == OUTPUT_FIELDS
        assert item["risk"] in ALLOWED_RISKS
        assert item["risk_label"] == RISK_LABEL_MAP[item["risk"]]
        assert item["action_type"] in ALLOWED_ACTION_TYPES


def _module_name(module: str) -> str:
    return {"财务": "finance", "法务": "legal", "履约": "performance"}[module]


@contextmanager
def _patched_workflow(
    *,
    classify: Callable[[str], Any] | None = None,
    fetch: Callable[[str], Any] | None = None,
    review: Callable[[str, list[dict[str, Any]], str], Any] | None = None,
) -> Iterator[None]:
    original_classify = workflow.classify_contract_type
    original_fetch = workflow.fetch_audit_rules
    original_review = workflow.review_rules_with_llm
    if classify is not None:
        workflow.classify_contract_type = classify
    if fetch is not None:
        workflow.fetch_audit_rules = fetch
    if review is not None:
        workflow.review_rules_with_llm = review
    try:
        yield
    finally:
        workflow.classify_contract_type = original_classify
        workflow.fetch_audit_rules = original_fetch
        workflow.review_rules_with_llm = original_review


async def _scenario_all_pass() -> dict[str, Any]:
    rules = {
        "finance_rules": [
            _make_rule("PASS-FIN-001", "财务"),
            _make_rule("PASS-FIN-002", "财务", contract_type="通用"),
        ],
        "legal_rules": [_make_rule("PASS-LGL-001", "法务")],
        "performance_rules": [],
        "other_rules": [],
    }

    def _builder(module: str, module_rules: list[dict[str, Any]], _: str) -> list[dict[str, str]]:
        return [
            {
                "rule_code": rule["rule_code"],
                "risk": "pass",
                "key": f"{rule['rule_code']}_key",
                "tip": "无",
                "content": "无",
                "advice": "无",
                "replace_text": "无",
            }
            for rule in module_rules
        ]

    with _patched_workflow(
        classify=_fake_classify_contract_type,
        fetch=_make_fetcher(rules),
        review=_make_review_stub(_builder),
    ):
        result = await workflow.audit_contract("all pass contract text")

    _assert_common_contract(result)
    assert len(result["output"]) == 3
    assert result["agreeCount"] == "3"
    assert result["highlevelriskCount"] == "0"
    assert result["mediumlevelriskCount"] == "0"
    assert result["lowlevelriskCount"] == "0"
    return result


async def _scenario_mixed_risks() -> dict[str, Any]:
    rules = {
        "finance_rules": [_make_rule("MIX-FIN-001", "财务")],
        "legal_rules": [
            _make_rule("MIX-LGL-001", "法务"),
            _make_rule("MIX-LGL-002", "法务"),
        ],
        "performance_rules": [_make_rule("MIX-PER-001", "履约")],
        "other_rules": [],
    }
    risk_by_code = {
        "MIX-FIN-001": "high",
        "MIX-LGL-001": "medium",
        "MIX-LGL-002": "low",
        "MIX-PER-001": "pass",
    }

    def _builder(module: str, module_rules: list[dict[str, Any]], _: str) -> list[dict[str, str]]:
        return [
            {
                "rule_code": rule["rule_code"],
                "risk": risk_by_code[rule["rule_code"]],
                "key": f"{rule['rule_code']}_key",
                "tip": "无" if risk_by_code[rule["rule_code"]] == "pass" else "risk_tip",
                "content": "无" if risk_by_code[rule["rule_code"]] == "pass" else "risk_content",
                "advice": "无" if risk_by_code[rule["rule_code"]] == "pass" else "risk_advice",
                "replace_text": "无" if risk_by_code[rule["rule_code"]] == "pass" else "risk_replace",
            }
            for rule in module_rules
        ]

    with _patched_workflow(
        classify=_fake_classify_contract_type,
        fetch=_make_fetcher(rules),
        review=_make_review_stub(_builder),
    ):
        result = await workflow.audit_contract("mixed risks contract text")

    _assert_common_contract(result)
    assert len(result["output"]) == 4
    assert result["agreeCount"] == "1"
    assert result["highlevelriskCount"] == "1"
    assert result["mediumlevelriskCount"] == "1"
    assert result["lowlevelriskCount"] == "1"
    return result


async def _scenario_duplicated_results_preserved() -> dict[str, Any]:
    rules = {
        "finance_rules": [
            _make_rule("DUP-001", "财务"),
            _make_rule("DUP-002", "财务"),
            _make_rule("DUP-003", "财务"),
        ],
        "legal_rules": [],
        "performance_rules": [],
        "other_rules": [],
    }

    def _builder(module: str, module_rules: list[dict[str, Any]], _: str) -> list[dict[str, str]]:
        return [
            {
                "rule_code": rule["rule_code"],
                "risk": "pass",
                "key": "same_key",
                "tip": "same_tip",
                "content": "same_content",
                "advice": "same_advice",
                "replace_text": "same_replace",
            }
            for rule in module_rules
        ]

    with _patched_workflow(
        classify=_fake_classify_contract_type,
        fetch=_make_fetcher(rules),
        review=_make_review_stub(_builder),
    ):
        result = await workflow.audit_contract("duplicate results contract text")

    _assert_common_contract(result)
    assert len(result["output"]) == 3
    assert [item["rule_code"] for item in result["output"]] == [
        "DUP-001",
        "DUP-002",
        "DUP-003",
    ]
    return result


async def _scenario_three_modules() -> dict[str, Any]:
    rules = {
        "finance_rules": [_make_rule("MOD-FIN-001", "财务")],
        "legal_rules": [_make_rule("MOD-LGL-001", "法务")],
        "performance_rules": [_make_rule("MOD-PER-001", "履约")],
        "other_rules": [],
    }

    def _builder(module: str, module_rules: list[dict[str, Any]], _: str) -> list[dict[str, str]]:
        module_name = _module_name(module)
        return [
            {
                "rule_code": rule["rule_code"],
                "risk": "pass",
                "key": f"{module_name}_key",
                "tip": "无",
                "content": "无",
                "advice": "无",
                "replace_text": "无",
            }
            for rule in module_rules
        ]

    with _patched_workflow(
        classify=_fake_classify_contract_type,
        fetch=_make_fetcher(rules),
        review=_make_review_stub(_builder),
    ):
        result = await workflow.audit_contract("three modules contract text")

    _assert_common_contract(result)
    assert {item["rule_code"] for item in result["output"]} == {
        "MOD-FIN-001",
        "MOD-LGL-001",
        "MOD-PER-001",
    }
    return result


async def _scenario_pass_defaults() -> dict[str, Any]:
    rules = {
        "finance_rules": [_make_rule("PASS-DEF-001", "财务")],
        "legal_rules": [],
        "performance_rules": [],
        "other_rules": [],
    }

    def _builder(module: str, module_rules: list[dict[str, Any]], _: str) -> list[dict[str, str]]:
        return [
            {
                "rule_code": rule["rule_code"],
                "risk": "pass",
                "key": "pass_default_key",
                "tip": "无",
                "content": "无",
                "advice": "无",
                "replace_text": "无",
            }
            for rule in module_rules
        ]

    with _patched_workflow(
        classify=_fake_classify_contract_type,
        fetch=_make_fetcher(rules),
        review=_make_review_stub(_builder),
    ):
        result = await workflow.audit_contract("pass defaults contract text")

    _assert_common_contract(result)
    item = result["output"][0]
    assert item["risk"] == "pass"
    assert item["risk_label"] == "通过"
    assert item["tip"] == "无"
    assert item["content"] == "无"
    assert item["advice"] == "无"
    assert item["replace_text"] == "无"
    return result


async def _scenario_action_types() -> dict[str, Any]:
    rules = {
        "finance_rules": [
            _make_rule("ACT-001", "财务", risk_name="manual_case"),
            _make_rule("ACT-002", "财务", risk_name="append_case"),
            _make_rule("ACT-003", "财务", risk_name="insert_case"),
            _make_rule("ACT-004", "财务", risk_name="replace_case"),
        ],
        "legal_rules": [],
        "performance_rules": [],
        "other_rules": [],
    }

    def _builder(module: str, module_rules: list[dict[str, Any]], _: str) -> list[dict[str, str]]:
        payloads = {
            "ACT-001": {
                "risk": "pass",
                "key": "manual_key",
                "tip": "无",
                "content": "无",
                "advice": "无",
                "replace_text": "无",
            },
            "ACT-002": {
                "risk": "high",
                "key": "append_key",
                "tip": "append_tip",
                "content": "未发现明确原文，但相关内容缺失",
                "advice": "append_advice",
                "replace_text": "append_replace",
            },
            "ACT-003": {
                "risk": "medium",
                "key": "交货时间不明确",
                "tip": "insert_tip",
                "content": "交货时间由双方协商",
                "advice": "insert_advice",
                "replace_text": "insert_replace",
            },
            "ACT-004": {
                "risk": "low",
                "key": "replace_key",
                "tip": "replace_tip",
                "content": "乙方应于约定时间交付。",
                "advice": "replace_advice",
                "replace_text": "乙方应于【期限】完成交付。",
            },
        }
        return [
            {"rule_code": rule["rule_code"], **payloads[rule["rule_code"]]}
            for rule in module_rules
        ]

    with _patched_workflow(
        classify=_fake_classify_contract_type,
        fetch=_make_fetcher(rules),
        review=_make_review_stub(_builder),
    ):
        result = await workflow.audit_contract("action type contract text")

    _assert_common_contract(result)
    action_types = [item["action_type"] for item in result["output"]]
    assert action_types == ["manual", "append", "insert", "replace"]
    return result


async def _scenario_empty_rules() -> dict[str, Any]:
    with _patched_workflow(
        classify=_fake_classify_contract_type,
        fetch=_make_fetcher(
            {
                "finance_rules": [],
                "legal_rules": [],
                "performance_rules": [],
                "other_rules": [],
            }
        ),
    ):
        result = await workflow.audit_contract("empty rules contract text")

    _assert_common_contract(result)
    assert result["agreeCount"] == "0"
    assert result["highlevelriskCount"] == "0"
    assert result["mediumlevelriskCount"] == "0"
    assert result["lowlevelriskCount"] == "0"
    assert result["output"] == []
    return result


async def _scenario_empty_input() -> dict[str, Any]:
    result = await workflow.audit_contract("")
    _assert_common_contract(result)
    assert result["agreeCount"] == "0"
    assert result["highlevelriskCount"] == "0"
    assert result["mediumlevelriskCount"] == "0"
    assert result["lowlevelriskCount"] == "0"
    assert result["output"] == []
    return result


async def _run_validation() -> list[tuple[str, bool]]:
    scenarios = [
        ("all_pass", _scenario_all_pass),
        ("mixed_risks", _scenario_mixed_risks),
        ("duplicated_results_preserved", _scenario_duplicated_results_preserved),
        ("three_modules", _scenario_three_modules),
        ("pass_defaults", _scenario_pass_defaults),
        ("action_types", _scenario_action_types),
        ("empty_rules", _scenario_empty_rules),
        ("empty_input", _scenario_empty_input),
    ]
    results: list[tuple[str, bool]] = []
    for name, scenario in scenarios:
        await scenario()
        results.append((name, True))
    return results


def main() -> None:
    scenario_results = asyncio.run(_run_validation())
    print("audit workflow validation ok")
    for name, passed in scenario_results:
        print(f"{name}: {passed}")


if __name__ == "__main__":
    main()
