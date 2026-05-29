"""合同审查相关的数据模型。"""

from typing import Optional

from pydantic import BaseModel
from pydantic import Field

from app.schemas.comparison import ComparisonRiskPointSchema
from app.schemas.comparison import ComparisonTaskSchema


class ParagraphSchema(BaseModel):
    """段落 schema。"""

    id: str
    review_task_id: str
    index: int
    text: Optional[str] = None
    char_offset_start: Optional[int] = None
    char_offset_end: Optional[int] = None
    page_number: Optional[int] = None
    is_key_clause: bool = False
    paragraph_type: str = "body"
    paragraph_level: int = 0
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class SentenceSchema(BaseModel):
    """句子 schema。"""

    id: str
    review_task_id: str
    index: int
    text: Optional[str] = None
    char_offset_start: Optional[int] = None
    char_offset_end: Optional[int] = None
    paragraph_index: Optional[int] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class RiskPointSchema(BaseModel):
    """风险点 schema。"""

    id: str
    title: str
    level: str
    reason: Optional[str] = None
    suggestion: Optional[str] = None
    # 新增字段
    category: Optional[str] = None  # 风险分类
    evidence: Optional[str] = None  # 证据材料
    impact: Optional[str] = None  # 影响程度
    replace_text: Optional[str] = None  # Coze 返回的可替换修改文本
    rule_code: Optional[str] = None  # 命中的规则编号
    rule_snapshot_json: Optional[dict] = None  # 任务执行时的规则快照
    # 位置和原文
    position: Optional[dict] = None  # {"paragraph_index": 0, "char_offset_start": 100}
    original_text: Optional[str] = None
    # 状态
    status: str = "pending"
    confirmed_at: Optional[str] = None
    confirmed_by_user_id: Optional[str] = None  # 确认人ID（真实外键）
    confirmed_by: Optional[str] = None  # 确认人（兼容字段）
    ignore_reason: Optional[str] = None
    review_comment: Optional[str] = None  # 人工复核备注
    source: str = "coze"  # 来源：coze=AI分析, manual=人工标记
    sentence_id: Optional[str] = None  # 关联句子ID
    sentence_text: Optional[str] = None  # 关联句子文本
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class RiskStatsSchema(BaseModel):
    """风险统计 schema。"""

    total: int = 0
    confirmed: int = 0
    ignored: int = 0
    pending: int = 0


class ReviewTaskSchema(BaseModel):
    """审查任务 schema。"""

    id: str
    file_name: str
    file_type: str
    file_size: Optional[int] = None
    sanitized_text: Optional[str] = None
    sanitization_status: str = "not_required"
    sanitization_error: Optional[str] = None
    rule_version_id: Optional[str] = None
    contract_type: str = "通用"
    char_count: Optional[int] = None
    page_count: Optional[int] = None
    paragraph_count: Optional[int] = None
    sentence_count: Optional[int] = None
    overall_conclusion: Optional[str] = None
    risk_summary: Optional[dict] = None  # {"high": 0, "medium": 0, "low": 0}
    suggest_deep_review: bool = False
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None
    risk_count: int = 0
    risk_stats: Optional[RiskStatsSchema] = None
    # 新增：段落和句子列表
    paragraphs: list[ParagraphSchema] = []
    sentences: list[SentenceSchema] = []
    # 保留兼容：原有 JSON 字段
    paragraphs_json: Optional[list[dict]] = None

    class Config:
        from_attributes = True


class ReviewTaskCreateResponse(BaseModel):
    """创建审查任务响应。"""

    task_id: str
    message: str = "审查任务创建成功"


class ReviewTaskListResponse(BaseModel):
    """审查任务列表响应（带分页信息）。"""

    tasks: list[ReviewTaskSchema]
    total: int
    skip: int
    limit: int


class ReviewTaskQueryResponse(BaseModel):
    """查询审查任务响应。"""

    task: ReviewTaskSchema
    risk_points: list[RiskPointSchema] = []
    message: str = "查询成功"


class ReviewRiskListResponse(BaseModel):
    """审查任务的风险点列表响应。"""

    task_id: str
    risk_points: list[RiskPointSchema]
    total: int
    risk_stats: RiskStatsSchema


class ComparisonRiskListResponse(BaseModel):
    """比对任务的风险点列表响应。"""

    task_id: str
    risk_points: list[ComparisonRiskPointSchema]
    total: int
    risk_stats: RiskStatsSchema


class ComparisonTaskListResponse(BaseModel):
    """比对任务列表响应（带分页信息）。"""

    tasks: list[ComparisonTaskSchema]
    total: int
    skip: int
    limit: int


class ReviewExportRequest(BaseModel):
    """导出合同请求（接收用户修改后的文本）。"""

    final_text: str = Field(..., description="用户修改后的合同完整文本")
    file_name: Optional[str] = Field(None, description="导出的文件名")


class RiskStatusUpdateRequest(BaseModel):
    """更新风险状态请求。"""

    status: str = Field(..., description="新状态: pending/confirmed/ignored")
    ignore_reason: Optional[str] = Field(
        None, description="忽略原因（当 status=ignored 时）"
    )
    review_comment: Optional[str] = Field(None, description="人工复核备注")


class RiskStatusUpdateResponse(BaseModel):
    """更新风险状态响应。"""

    risk_id: str
    old_status: str
    new_status: str
    message: str = "状态更新成功"


class RiskListResponse(BaseModel):
    """风险点列表响应。"""

    task_id: str
    risk_points: list[RiskPointSchema]
    total: int
    risk_stats: RiskStatsSchema
