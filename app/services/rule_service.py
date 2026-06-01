"""规则库业务服务。"""

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models.database import ReviewRule

VALID_RISK_LEVELS = {"高", "中", "低"}
VALID_PERSPECTIVES = {"甲方", "乙方", "中立", "通用"}
REQUIRED_RULE_FIELDS = [
    "rule_code",
    "contract_type",
    "review_module",
    "risk_name",
    "default_risk_level",
]


def validate_rule_payload(payload: dict) -> None:
    """校验规则字段，失败时抛出 ValueError。"""
    for field in REQUIRED_RULE_FIELDS:
        if not str(payload.get(field) or "").strip():
            raise ValueError(f"{field} 不能为空")

    risk_level = payload.get("default_risk_level")
    if risk_level not in VALID_RISK_LEVELS:
        raise ValueError("default_risk_level 必须是 高/中/低")

    perspective = payload.get("review_perspective", "通用")
    if perspective not in VALID_PERSPECTIVES:
        raise ValueError("review_perspective 必须是 甲方/乙方/中立/通用")


def list_rules(
    db: Session,
    contract_type: Optional[str] = None,
    enabled: Optional[bool] = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[ReviewRule], int]:
    """查询规则列表和总数。"""
    query = db.query(ReviewRule)

    if contract_type:
        query = query.filter(ReviewRule.contract_type == contract_type)
    if enabled is not None:
        query = query.filter(ReviewRule.enabled == enabled)

    total = query.count()
    rules = query.order_by(ReviewRule.rule_code.asc()).offset(skip).limit(limit).all()
    return rules, total


def create_rule(db: Session, payload: dict) -> ReviewRule:
    """创建规则。"""
    validate_rule_payload(payload)
    _ensure_rule_code_unique(db, payload["rule_code"])

    rule = ReviewRule(id=_uuid(), **payload)
    db.add(rule)
    db.flush()
    return rule


def update_rule(db: Session, rule_id: str, payload: dict) -> ReviewRule:
    """更新规则字段。"""
    rule = db.query(ReviewRule).filter(ReviewRule.id == rule_id).first()
    if not rule:
        raise ValueError("规则不存在")

    data = {key: value for key, value in payload.items() if value is not None}
    merged = rule.to_dict() | data
    validate_rule_payload(merged)

    for key, value in data.items():
        if hasattr(rule, key):
            setattr(rule, key, value)
    db.flush()
    return rule


def delete_rule(db: Session, rule_id: str) -> None:
    """删除规则。"""
    rule = db.query(ReviewRule).filter(ReviewRule.id == rule_id).first()
    if not rule:
        raise ValueError("规则不存在")
    db.delete(rule)
    db.flush()


def build_enabled_rules_snapshot(
    db: Session, contract_type: str
) -> tuple[None, list[dict]]:
    """读取适用于合同类型的启用规则。"""
    types = {"通用", contract_type or "通用"}
    rules = (
        db.query(ReviewRule)
        .filter(
            ReviewRule.enabled == True,  # noqa: E712
            ReviewRule.contract_type.in_(types),
        )
        .order_by(ReviewRule.rule_code.asc())
        .all()
    )

    return None, [_rule_to_snapshot(rule) for rule in rules]


def find_rule_snapshot(rules: list[dict], rule_code: Optional[str]) -> Optional[dict]:
    """按规则编号查找任务规则快照。"""
    if not rule_code:
        return None
    return next((rule for rule in rules if rule.get("rule_code") == rule_code), None)


def _rule_to_snapshot(rule: ReviewRule) -> dict:
    """构建传给 Coze 的规则快照。"""
    return {
        "rule_code": rule.rule_code,
        "contract_type": rule.contract_type,
        "review_module": rule.review_module,
        "risk_name": rule.risk_name,
        "check_point": rule.check_point,
        "trigger_condition": rule.trigger_condition,
        "default_risk_level": rule.default_risk_level,
        "suggestion_template": rule.suggestion_template,
        "example_clause": rule.example_clause,
        "review_perspective": rule.review_perspective,
    }


def _ensure_rule_code_unique(db: Session, rule_code: str) -> None:
    """确认规则编号唯一。"""
    exists = db.query(ReviewRule.id).filter(ReviewRule.rule_code == rule_code).first()
    if exists:
        raise ValueError("规则编号已存在")


def _uuid() -> str:
    """生成 UUID。"""
    return str(uuid.uuid4())
