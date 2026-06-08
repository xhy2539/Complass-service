"""Expanded runnable validation for the contract comparison workflow."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from contract_compare_workflow import workflow


TOP_LEVEL_FIELDS = {"success", "enhanced", "total_risks", "message"}
ENHANCED_FIELDS = {
    "category",
    "change_type",
    "evidence",
    "impact",
    "new_quote",
    "old_quote",
    "original",
    "risk_level",
    "suggestion",
    "summary",
}
ALLOWED_CHANGE_TYPES = {"added", "deleted", "modified", "moved"}
ALLOWED_RISK_LEVELS = {"high", "medium", "low"}

COMMON_RULES_BODY = {
    "data": {
        "finance_rules": [
            {
                "contract_type": "通用",
                "module": "财务",
                "risk_name": "合同金额",
                "check_point": "关注金额变化",
                "trigger_condition": "合同金额变化",
                "default_risk_level": "低",
                "suggestion_template": "建议人工复核金额变化是否符合审批结果",
            },
            {
                "contract_type": "采购合同",
                "module": "财务",
                "risk_name": "付款条款",
                "check_point": "关注付款条件与付款期限变化",
                "trigger_condition": "付款条件或期限变化",
                "default_risk_level": "中",
                "suggestion_template": "建议明确付款前提，例如验收合格且收到合规发票后若干日内付款",
            },
        ],
        "legal_rules": [
            {
                "contract_type": "采购合同",
                "module": "法务",
                "risk_name": "违约责任",
                "check_point": "关注违约责任变化",
                "trigger_condition": "违约责任减轻或加重",
                "default_risk_level": "中",
                "suggestion_template": "建议复核违约责任是否足以覆盖违约损失",
            },
            {
                "contract_type": "通用",
                "module": "法务",
                "risk_name": "保密条款",
                "check_point": "关注新增保密义务",
                "trigger_condition": "新增保密条款",
                "default_risk_level": "低",
                "suggestion_template": "建议明确保密范围、期限和违约责任",
            },
        ],
        "performance_rules": [
            {
                "contract_type": "采购合同",
                "module": "履约",
                "risk_name": "验收条款",
                "check_point": "关注验收标准变化",
                "trigger_condition": "验收标准变化",
                "default_risk_level": "中",
                "suggestion_template": "建议明确性能测试标准和验收流程",
            },
            {
                "contract_type": "通用",
                "module": "法务",
                "risk_name": "争议解决",
                "check_point": "关注争议解决变化",
                "trigger_condition": "争议解决条款删除或变化",
                "default_risk_level": "中",
                "suggestion_template": "建议补充明确的争议解决方式和管辖安排",
            },
        ],
        "other_rules": [],
    }
}


@dataclass
class Scenario:
    name: str
    old_text: str
    new_text: str
    contract_type: str
    diff_texts: list[dict[str, str]] | None
    enhanced: list[dict[str, str]] | None
    expected_success: bool
    expected_message: str | None = None


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    response: dict[str, Any]
    details: str


def _json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _base_item(
    *,
    category: str,
    change_type: str,
    old_quote: str,
    new_quote: str,
    original: str,
    summary: str,
    evidence: str,
    impact: str,
    suggestion: str,
    risk_level: str,
) -> dict[str, str]:
    return {
        "category": category,
        "change_type": change_type,
        "evidence": evidence,
        "impact": impact,
        "new_quote": new_quote,
        "old_quote": old_quote,
        "original": original,
        "risk_level": risk_level,
        "suggestion": suggestion,
        "summary": summary,
    }


def _scenario_normal_modified() -> Scenario:
    old_text = """采购合同
合同总价为人民币100000元。
甲方应在乙方交付全部设备并经甲方验收合格后30个工作日内付款。
设备验收标准为外观完好、数量一致。
乙方逾期交付的，每逾期一日按合同总价的0.1%支付违约金。
"""
    new_text = """采购合同
合同总价为人民币120000元。
甲方应在乙方交付设备后15个工作日内付款。
设备验收标准为外观完好、数量一致，并通过甲方性能测试。
乙方逾期交付的，每逾期一日按合同总价的0.05%支付违约金。
"""
    diff_texts = [
        {
            "change_type": "modified",
            "old_quote": "合同总价为人民币100000元。",
            "new_quote": "合同总价为人民币120000元。",
            "original": "合同金额从100000元变更为120000元。",
        },
        {
            "change_type": "modified",
            "old_quote": "甲方应在乙方交付全部设备并经甲方验收合格后30个工作日内付款。",
            "new_quote": "甲方应在乙方交付设备后15个工作日内付款。",
            "original": "付款条款变更：删除交付全部设备及验收合格的付款前提，付款期限从30个工作日缩短为15个工作日。",
        },
        {
            "change_type": "modified",
            "old_quote": "设备验收标准为外观完好、数量一致。",
            "new_quote": "设备验收标准为外观完好、数量一致，并通过甲方性能测试。",
            "original": "验收条款新增甲方性能测试要求。",
        },
        {
            "change_type": "modified",
            "old_quote": "乙方逾期交付的，每逾期一日按合同总价的0.1%支付违约金。",
            "new_quote": "乙方逾期交付的，每逾期一日按合同总价的0.05%支付违约金。",
            "original": "违约责任变更：每日违约金比例从0.1%调整为0.05%。",
        },
    ]
    enhanced = [
        _base_item(
            category="合同金额",
            change_type="modified",
            old_quote=diff_texts[0]["old_quote"],
            new_quote=diff_texts[0]["new_quote"],
            original=diff_texts[0]["original"],
            summary="合同金额上调，属于采购成本的实质变化。",
            evidence="旧合同金额为100000元；新合同金额为120000元。",
            impact="采购成本可能增加，影响预算与审批安排。",
            suggestion="建议人工复核金额变化是否符合审批结果",
            risk_level="low",
        ),
        _base_item(
            category="付款条款",
            change_type="modified",
            old_quote=diff_texts[1]["old_quote"],
            new_quote=diff_texts[1]["new_quote"],
            original=diff_texts[1]["original"],
            summary="付款前提减少且付款期限缩短，存在提前付款风险。",
            evidence="旧合同要求交付全部设备并经验收合格后30个工作日付款；新合同仅要求交付设备后15个工作日付款。",
            impact="可能导致设备未完全交付或未经验收即发生付款。",
            suggestion="建议明确付款前提，例如验收合格且收到合规发票后若干日内付款",
            risk_level="medium",
        ),
        _base_item(
            category="验收条款",
            change_type="modified",
            old_quote=diff_texts[2]["old_quote"],
            new_quote=diff_texts[2]["new_quote"],
            original=diff_texts[2]["original"],
            summary="验收标准新增性能测试，交付要求更严格。",
            evidence="新合同在外观完好、数量一致基础上新增通过甲方性能测试要求。",
            impact="可能拉长验收周期并影响交付计划。",
            suggestion="建议明确性能测试标准和验收流程",
            risk_level="medium",
        ),
        _base_item(
            category="违约责任",
            change_type="modified",
            old_quote=diff_texts[3]["old_quote"],
            new_quote=diff_texts[3]["new_quote"],
            original=diff_texts[3]["original"],
            summary="违约金比例下调，违约责任保护有所减弱。",
            evidence="旧合同违约金比例为0.1%；新合同违约金比例为0.05%。",
            impact="守约方对迟延交付的补偿保护可能降低。",
            suggestion="建议复核违约责任是否足以覆盖违约损失",
            risk_level="medium",
        ),
    ]
    return Scenario(
        name="正常修改场景",
        old_text=old_text,
        new_text=new_text,
        contract_type="采购合同",
        diff_texts=diff_texts,
        enhanced=enhanced,
        expected_success=True,
    )


def _scenario_added_clause() -> Scenario:
    old_text = "采购合同\n双方应合法履行本合同。\n"
    new_text = "采购合同\n双方应合法履行本合同。\n乙方应对甲方商业秘密承担保密义务，保密期限为三年。\n"
    diff_texts = [
        {
            "change_type": "added",
            "old_quote": "",
            "new_quote": "乙方应对甲方商业秘密承担保密义务，保密期限为三年。",
            "original": "新增保密条款，约定乙方承担保密义务且保密期限为三年。",
        }
    ]
    enhanced = [
        _base_item(
            category="保密条款",
            change_type="added",
            old_quote="",
            new_quote=diff_texts[0]["new_quote"],
            original=diff_texts[0]["original"],
            summary="新增保密义务条款，需要关注保密范围与期限是否明确。",
            evidence="新合同新增保密义务及三年保密期限。",
            impact="若表述不清，可能影响秘密信息范围和违约责任认定。",
            suggestion="建议明确保密范围、期限和违约责任",
            risk_level="low",
        )
    ]
    return Scenario(
        name="新增条款场景",
        old_text=old_text,
        new_text=new_text,
        contract_type="采购合同",
        diff_texts=diff_texts,
        enhanced=enhanced,
        expected_success=True,
    )


def _scenario_deleted_clause() -> Scenario:
    old_text = "采购合同\n因本合同产生争议，由甲方所在地人民法院管辖。\n"
    new_text = "采购合同\n双方应友好协商处理争议。\n"
    diff_texts = [
        {
            "change_type": "deleted",
            "old_quote": "因本合同产生争议，由甲方所在地人民法院管辖。",
            "new_quote": "",
            "original": "删除争议解决条款，移除了明确的法院管辖安排。",
        }
    ]
    enhanced = [
        _base_item(
            category="争议解决",
            change_type="deleted",
            old_quote=diff_texts[0]["old_quote"],
            new_quote="",
            original=diff_texts[0]["original"],
            summary="争议解决条款被删除，后续处理路径不明确。",
            evidence="旧合同约定由甲方所在地人民法院管辖；新合同未保留对应条款。",
            impact="争议发生时可能出现程序路径不清、管辖争议增加的问题。",
            suggestion="建议补充明确的争议解决方式和管辖安排",
            risk_level="medium",
        )
    ]
    return Scenario(
        name="删除条款场景",
        old_text=old_text,
        new_text=new_text,
        contract_type="采购合同",
        diff_texts=diff_texts,
        enhanced=enhanced,
        expected_success=True,
    )


def _scenario_moved_clause() -> Scenario:
    old_text = "采购合同\n第一条 交付条款：乙方应在签约后10日内交付设备。\n第二条 付款条款：甲方应在验收合格后付款。\n"
    new_text = "采购合同\n第一条 付款条款：甲方应在验收合格后付款。\n第二条 交付条款：乙方应在签约后10日内交付设备。\n"
    diff_texts = [
        {
            "change_type": "moved",
            "old_quote": "交付条款：乙方应在签约后10日内交付设备。",
            "new_quote": "交付条款：乙方应在签约后10日内交付设备。",
            "original": "交付条款位置发生变化，但条款内容保持不变。",
        }
    ]
    enhanced = [
        _base_item(
            category="交付条款",
            change_type="moved",
            old_quote=diff_texts[0]["old_quote"],
            new_quote=diff_texts[0]["new_quote"],
            original=diff_texts[0]["original"],
            summary="条款内容未变，仅位置调整。",
            evidence="旧版与新版交付条款文本一致，仅编排位置发生变化。",
            impact="一般不会改变合同实质含义，但建议人工确认排版调整未影响引用关系。",
            suggestion="无需修改，建议人工确认",
            risk_level="low",
        )
    ]
    return Scenario(
        name="移动条款场景",
        old_text=old_text,
        new_text=new_text,
        contract_type="采购合同",
        diff_texts=diff_texts,
        enhanced=enhanced,
        expected_success=True,
    )


def _scenario_low_risk() -> Scenario:
    old_text = "采购合同\n乙方应及时提供服务支持。\n"
    new_text = "采购合同\n乙方应及时提供相关服务支持。\n"
    diff_texts = [
        {
            "change_type": "modified",
            "old_quote": "乙方应及时提供服务支持。",
            "new_quote": "乙方应及时提供相关服务支持。",
            "original": "服务支持表述增加“相关”一词，属于轻微措辞变化。",
        }
    ]
    enhanced = [
        _base_item(
            category="其他",
            change_type="modified",
            old_quote=diff_texts[0]["old_quote"],
            new_quote=diff_texts[0]["new_quote"],
            original=diff_texts[0]["original"],
            summary="该差异主要为轻微措辞变化，未改变核心权利义务。",
            evidence="新旧合同仅增加“相关”一词，其余表达保持一致。",
            impact="通常不产生实质性风险，但建议人工确认语义未变化。",
            suggestion="无需修改，建议人工确认",
            risk_level="low",
        )
    ]
    return Scenario(
        name="低风险场景",
        old_text=old_text,
        new_text=new_text,
        contract_type="采购合同",
        diff_texts=diff_texts,
        enhanced=enhanced,
        expected_success=True,
    )


def _scenario_empty_diff() -> Scenario:
    text = "采购合同\n甲乙双方按本合同约定履行义务。\n"
    return Scenario(
        name="空差异场景",
        old_text=text,
        new_text=text,
        contract_type="采购合同",
        diff_texts=[],
        enhanced=[],
        expected_success=True,
    )


def _scenario_empty_old_text() -> Scenario:
    return Scenario(
        name="错误输入场景-old_text为空",
        old_text="",
        new_text="采购合同\n乙方应提供服务。\n",
        contract_type="采购合同",
        diff_texts=None,
        enhanced=None,
        expected_success=False,
        expected_message="old_text 不能为空",
    )


def _scenario_empty_new_text() -> Scenario:
    return Scenario(
        name="错误输入场景-new_text为空",
        old_text="采购合同\n乙方应提供服务。\n",
        new_text="",
        contract_type="采购合同",
        diff_texts=None,
        enhanced=None,
        expected_success=False,
        expected_message="new_text 不能为空",
    )


def _build_scenarios() -> list[Scenario]:
    return [
        _scenario_normal_modified(),
        _scenario_added_clause(),
        _scenario_deleted_clause(),
        _scenario_moved_clause(),
        _scenario_low_risk(),
        _scenario_empty_diff(),
        _scenario_empty_old_text(),
        _scenario_empty_new_text(),
    ]


def _assert_top_level_contract(result: dict[str, Any], *, expect_success: bool) -> None:
    assert set(result.keys()) == TOP_LEVEL_FIELDS, result.keys()
    assert "diff_list" not in result
    assert "stats" not in result
    assert "addCount" not in result
    assert "deleteCount" not in result
    assert "modifyCount" not in result
    assert "contract_type" not in result
    assert isinstance(result["success"], bool)
    assert isinstance(result["enhanced"], list)
    assert isinstance(result["total_risks"], int)
    assert isinstance(result["message"], str)
    assert result["total_risks"] == len(result["enhanced"])
    if expect_success:
        assert result["success"] is True
        assert result["message"] == ""
    else:
        assert result["success"] is False
        assert result["message"].strip()


def _assert_enhanced_items(items: list[dict[str, Any]]) -> None:
    for item in items:
        assert set(item.keys()) == ENHANCED_FIELDS, item.keys()
        assert item["change_type"] in ALLOWED_CHANGE_TYPES
        assert item["risk_level"] in ALLOWED_RISK_LEVELS


def _make_fake_chat_completion(scenario: Scenario):
    async def _fake_chat_completion(prompt: str, *, json_mode: bool = False) -> str:
        _ = json_mode
        if "合同类型判断标准" in prompt:
            return scenario.contract_type
        if '"diff_texts"' in prompt and '"common_rules"' not in prompt:
            diff_items = scenario.diff_texts or []
            filtered: list[dict[str, str]] = []
            for item in diff_items:
                old_quote = item.get("old_quote", "")
                new_quote = item.get("new_quote", "")
                old_match = not old_quote or old_quote in prompt
                new_match = not new_quote or new_quote in prompt
                if old_match and new_match:
                    filtered.append(item)
            return _json_text({"diff_texts": filtered})
        return _json_text(
            {
                "success": True,
                "enhanced": scenario.enhanced,
                "total_risks": len(scenario.enhanced or []),
                "message": "",
            }
        )

    return _fake_chat_completion


def _make_fake_fetch_audit_rules(scenario: Scenario):
    async def _fake_fetch_audit_rules(contract_type: str) -> dict[str, str | int]:
        if contract_type != scenario.contract_type:
            raise AssertionError(f"{scenario.name}: unexpected contract_type {contract_type}")
        return {
            "body": _json_text(COMMON_RULES_BODY),
            "status_code": 200,
        }

    return _fake_fetch_audit_rules


async def _run_scenario(scenario: Scenario) -> ScenarioResult:
    original_chat_completion = workflow.chat_completion
    original_fetch_audit_rules = workflow.fetch_audit_rules

    workflow.chat_completion = _make_fake_chat_completion(scenario)
    workflow.fetch_audit_rules = _make_fake_fetch_audit_rules(scenario)

    try:
        response = await workflow.compare_contracts(
            old_text=scenario.old_text,
            new_text=scenario.new_text,
            task_type="compare",
        )

        _assert_top_level_contract(response, expect_success=scenario.expected_success)
        if scenario.expected_success:
            _assert_enhanced_items(response["enhanced"])
            assert len(response["enhanced"]) == len(scenario.enhanced or [])
            if scenario.diff_texts is not None:
                for index, diff_item in enumerate(scenario.diff_texts):
                    assert response["enhanced"][index]["old_quote"] == diff_item["old_quote"]
                    assert response["enhanced"][index]["new_quote"] == diff_item["new_quote"]
        else:
            if scenario.expected_message is not None:
                assert response["message"] == scenario.expected_message

        return ScenarioResult(
            name=scenario.name,
            passed=True,
            response=response,
            details="passed",
        )
    except AssertionError as exc:
        return ScenarioResult(
            name=scenario.name,
            passed=False,
            response=response if "response" in locals() else {},
            details=str(exc) or "assertion failed",
        )
    finally:
        workflow.chat_completion = original_chat_completion
        workflow.fetch_audit_rules = original_fetch_audit_rules


async def main() -> None:
    results: list[ScenarioResult] = []
    for scenario in _build_scenarios():
        result = await _run_scenario(scenario)
        results.append(result)

    summary = {
        "all_passed": all(result.passed for result in results),
        "results": [
            {
                "name": result.name,
                "passed": result.passed,
                "details": result.details,
                "response": result.response,
            }
            for result in results
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if not summary["all_passed"]:
        failed = [result.name for result in results if not result.passed]
        raise SystemExit(f"validation failed: {', '.join(failed)}")


if __name__ == "__main__":
    asyncio.run(main())
