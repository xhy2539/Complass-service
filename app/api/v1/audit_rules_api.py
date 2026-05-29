"""Coze 审查规则查询接口，按审核模块分组返回通用+专项规则。"""

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from sqlalchemy.orm import Session

from app.models.database import ReviewRule
from app.models.database import ReviewRuleVersion
from app.models.database import RuleVersionStatus
from app.models.database_connection import get_db

audit_rules_router = APIRouter(tags=["Coze 规则查询"])

MODULE_TO_KEY = {
    "财务": "finance_rules",
    "法务": "legal_rules",
    "履约": "performance_rules",
}


def _rule_to_coze_dict(rule: ReviewRule) -> dict:
    """转为 Coze 需要的英文 key 格式。"""
    return {
        "rule_id": rule.rule_code,
        "contract_type": rule.contract_type,
        "module": rule.review_module,
        "risk_name": rule.risk_name,
        "check_point": rule.check_point,
        "trigger_condition": rule.trigger_condition,
        "default_risk_level": rule.default_risk_level,
        "suggestion_template": rule.suggestion_template,
        "example_clause": rule.example_clause,
    }


@audit_rules_router.get("/api/audit-rules")
def get_audit_rules(
    contract_type: str = Query(
        "通用", description="合同类型：采购合同/服务合同/合作协议/其他"
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Coze 审查工作流 HTTP 节点调用的规则查询接口。"""

    # 获取激活版本
    version = (
        db.query(ReviewRuleVersion)
        .filter(ReviewRuleVersion.status == RuleVersionStatus.ACTIVE)
        .first()
    )
    if not version:
        return {
            "finance_rules": [],
            "legal_rules": [],
            "performance_rules": [],
            "other_rules": [],
            "debug_info": {"error": "no active rule version"},
        }

    # 确定查询的合同类型
    types: set[str]
    if contract_type in ("其他", ""):
        types = {"通用"}
    else:
        types = {"通用", contract_type}

    # 查规则
    rules = (
        db.query(ReviewRule)
        .filter(
            ReviewRule.version_id == version.id,
            ReviewRule.enabled == True,  # noqa: E712
            ReviewRule.contract_type.in_(types),
        )
        .order_by(ReviewRule.review_module, ReviewRule.rule_code)
        .all()
    )

    coze_rules = [_rule_to_coze_dict(r) for r in rules]
    grouped: dict[str, list[dict]] = {
        "finance_rules": [],
        "legal_rules": [],
        "performance_rules": [],
        "other_rules": [],
    }
    for r in coze_rules:
        key = MODULE_TO_KEY.get(r["module"], "other_rules")
        grouped[key].append(r)

    # 统计
    contract_type_counts: dict[str, int] = {}
    module_counts: dict[str, int] = {}
    for r in coze_rules:
        ct = r["contract_type"]
        contract_type_counts[ct] = contract_type_counts.get(ct, 0) + 1
        m = r["module"]
        module_counts[m] = module_counts.get(m, 0) + 1

    common_count = sum(1 for r in coze_rules if r["contract_type"] == "通用")
    specific_count = sum(1 for r in coze_rules if r["contract_type"] != "通用")

    return {
        "finance_rules": grouped["finance_rules"],
        "legal_rules": grouped["legal_rules"],
        "performance_rules": grouped["performance_rules"],
        "other_rules": grouped["other_rules"],
        "debug_info": {
            "current_contract_type": contract_type,
            "common_count": common_count,
            "specific_count": specific_count,
            "finance_count": len(grouped["finance_rules"]),
            "legal_count": len(grouped["legal_rules"]),
            "performance_count": len(grouped["performance_rules"]),
            "other_count": len(grouped["other_rules"]),
            "total_count": len(coze_rules),
            "final_contract_type_count": contract_type_counts,
            "final_module_count": module_counts,
        },
    }
