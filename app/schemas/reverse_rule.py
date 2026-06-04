"""规则逆向解析相关 Schema。"""

from typing import Optional

from pydantic import BaseModel
from pydantic import Field


class CandidateRuleResponse(BaseModel):
    """候选规则响应。"""

    id: str
    task_id: str
    contract_type: str
    review_module: str
    risk_name: str
    check_point: Optional[str] = None
    trigger_condition: Optional[str] = None
    default_risk_level: str
    suggestion_template: Optional[str] = None
    example_clause: Optional[str] = None
    review_perspective: str = "通用"
    traces: Optional[list[dict]] = None
    source_pair: Optional[str] = None
    source_pair_index: Optional[int] = None
    decision: str = "pending"
    confidence: Optional[int] = None
    imported_rule_id: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class TaskResponse(BaseModel):
    """逆向解析任务响应。"""

    id: str
    task_name: str
    contract_type: Optional[str] = None
    review_role: Optional[str] = None
    status: str = "pending"
    progress: int = 0
    pair_count: int = 0
    stats: Optional[dict] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    """任务列表响应。"""

    tasks: list[TaskResponse]
    total: int
    skip: int
    limit: int


class CandidateListResponse(BaseModel):
    """候选规则列表响应。"""

    candidates: list[CandidateRuleResponse]
    task: TaskResponse


class DecideRequest(BaseModel):
    """候选规则决策请求。"""

    candidate_ids: list[str] = []
    decision: str = Field(..., description="included / ignored / pending")


class DecideResponse(BaseModel):
    """决策结果。"""

    updated: int
    decision: str


class ImportRequest(BaseModel):
    """入库请求。"""

    candidate_ids: list[str]


class ImportResponse(BaseModel):
    """入库结果。"""

    task_id: str
    included_count: int
    imported_rules: list[dict] = []
    ignored_count: int = 0
    ignored_rules: list[dict] = []
    pair_count: int = 0
