from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


RiskLevel = Literal["低", "中", "高"]
ChangeType = Literal["新增", "删除", "修改"]


class ContractPair(BaseModel):
    pair_id: str
    before_text: str
    after_text: str
    contract_type: str | None = None
    review_role: str | None = None

    @field_validator("before_text", "after_text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("before_text 和 after_text 不能为空")
        return value.strip()


class DiffClause(BaseModel):
    review_module: str
    change_type: ChangeType
    before: str
    after: str
    diff_summary: str
    is_substantive: bool
    substantive_reason: str | None = None


class DiffResult(BaseModel):
    pair_id: str
    changed_clauses: list[DiffClause] = Field(default_factory=list)


class ContractBaseInfo(BaseModel):
    pair_id: str
    contract_type: str
    review_role: str
    contract_subject: str
    party_a_identity: str | None = None
    party_b_identity: str | None = None
    confidence: float = Field(ge=0, le=1)


class RetrievedCase(BaseModel):
    case_id: str
    contract_type: list[str] | str | None = None
    review_role: list[str] | str | None = None
    review_module: str
    change_pattern: str
    before_example: str | None = None
    after_example: str | None = None
    diff_summary: str | None = None
    user_intent: str | None = None
    risk_name: str
    check_point: str
    trigger_condition: str
    default_risk_level: RiskLevel | None = None
    suggestion_template: str
    example_clause: str | None = None


class RuleExtractionTrace(BaseModel):
    pair_id: str
    evidence_before: str
    evidence_after: str
    diff_summary: str
    user_intent: str
    confidence: float = Field(ge=0, le=1)


class CandidateRuleForDB(BaseModel):
    contract_type: str
    review_perspective: Literal["甲方", "乙方", "通用"] = "通用"
    review_module: str
    risk_name: str = Field(max_length=100)
    check_point: str
    trigger_condition: str
    default_risk_level: RiskLevel
    suggestion_template: str
    example_clause: str
    traces: list[RuleExtractionTrace]


class FinalRuleResult(BaseModel):
    summary: str
    rules: list[CandidateRuleForDB] = Field(default_factory=list)


class CandidateRuleBatch(BaseModel):
    rules: list[CandidateRuleForDB] = Field(default_factory=list)


class RuleRecord(BaseModel):
    id: str
    version_id: str
    rule_code: str
    contract_type: str
    review_module: str
    risk_name: str
    check_point: str
    trigger_condition: str
    default_risk_level: str
    suggestion_template: str
    example_clause: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
