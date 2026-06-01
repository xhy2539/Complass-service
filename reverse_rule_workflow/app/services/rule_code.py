from datetime import datetime
from uuid import uuid4

from app.models.reverse_rule import CandidateRuleForDB, RuleRecord


MODULE_PREFIX = {
    "付款条款": "PAY",
    "违约责任": "BREACH",
    "赔偿责任上限": "LIAB",
    "解除条款": "TERM",
    "保密义务": "CONF",
    "保密条款": "CONF",
}


def to_rule_record(
    candidate: CandidateRuleForDB,
    rule_code: str | None = None,
    version_id: str | None = None,
) -> RuleRecord:
    now = datetime.now()
    return RuleRecord(
        id=str(uuid4()),
        version_id=version_id or str(uuid4()),
        rule_code=rule_code or _generate_rule_code(candidate.review_module),
        contract_type=candidate.contract_type,
        review_module=candidate.review_module,
        risk_name=candidate.risk_name,
        check_point=candidate.check_point,
        trigger_condition=candidate.trigger_condition,
        default_risk_level=candidate.default_risk_level,
        suggestion_template=candidate.suggestion_template,
        example_clause=candidate.example_clause,
        enabled=True,
        created_at=now,
        updated_at=now,
    )


def _generate_rule_code(review_module: str) -> str:
    prefix = MODULE_PREFIX.get(review_module, "GEN")
    return f"RULE-{prefix}-{uuid4().hex[:8].upper()}"
