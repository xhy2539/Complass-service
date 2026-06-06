"""RAG 服务请求/响应模型，与主后端 RetrievedCase 字段兼容。"""

from pydantic import BaseModel
from pydantic import Field


class SearchRequest(BaseModel):
    query: str
    review_module: str | None = None
    contract_type: str | None = None
    review_role: str | None = None
    top_k: int = Field(default=3, ge=1, le=20)


class RetrievedCaseResult(BaseModel):
    case_id: str
    score: float
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
    default_risk_level: str | None = None
    suggestion_template: str
    example_clause: str | None = None


class SearchResponse(BaseModel):
    results: list[RetrievedCaseResult]


class IndexRequest(BaseModel):
    case: dict  # ReverseRuleCase 原始字段


class RebuildResponse(BaseModel):
    indexed: int
    modules: int
