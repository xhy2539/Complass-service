"""版本比对相关的数据模型。"""

from typing import Optional

from pydantic import BaseModel


class ComparisonTaskSchema(BaseModel):
    """比对任务 schema。"""

    id: str
    old_file_name: str
    new_file_name: str
    old_file_type: str
    new_file_type: str
    old_char_count: Optional[int] = None
    new_char_count: Optional[int] = None
    sanitization_status: str = "not_required"
    sanitization_error: Optional[str] = None
    rule_version_id: Optional[str] = None
    contract_type: str = "通用"
    diff_stats: Optional[dict] = None
    total_risks: int = 0
    token_cost: Optional[int] = None
    status: str
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    risk_count: int = 0
    risk_stats: Optional[dict] = None

    class Config:
        from_attributes = True


class ComparisonTaskCreateResponse(BaseModel):
    """创建比对任务响应。"""

    task_id: str
    message: str = "版本比对任务创建成功"
    old_file: dict
    new_file: dict
    diff_stats: dict


class ComparisonTaskQueryResponse(BaseModel):
    """查询比对任务响应。"""

    task: ComparisonTaskSchema
    diff_details: list
    risk_points: list
    coze_enhanced: list
    message: str = "查询成功"


class ComparisonRiskPointSchema(BaseModel):
    """比对风险点 schema。"""

    id: str
    change_type: str
    old_text: Optional[str] = None
    new_text: Optional[str] = None
    similarity: Optional[int] = None
    summary: Optional[str] = None
    risk_level: Optional[str] = None
    rule_code: Optional[str] = None
    rule_snapshot_json: Optional[dict] = None
    # 新增字段
    category: Optional[str] = None
    evidence: Optional[str] = None
    impact: Optional[str] = None
    suggestion: Optional[str] = None
    old_position: Optional[dict] = None
    new_position: Optional[dict] = None
    status: str = "pending"
    confirmed_at: Optional[str] = None
    confirmed_by_user_id: Optional[str] = None
    confirmed_by: Optional[str] = None
    ignore_reason: Optional[str] = None
    review_comment: Optional[str] = None
    source: str = "coze"
    created_at: Optional[str] = None

    class Config:
        from_attributes = True
