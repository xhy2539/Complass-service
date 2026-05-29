"""合同优化版本相关的数据模型。"""

from typing import Optional

from pydantic import BaseModel
from pydantic import Field


class ApplySuggestionsRequest(BaseModel):
    """采纳建议生成优化合同请求。"""

    risk_ids: list[str] = Field(..., min_length=1)
    title: Optional[str] = None


class OptimizedContractVersionResponse(BaseModel):
    """优化合同版本响应。"""

    id: str
    review_task_id: str
    version_no: int
    title: str
    text: str
    accepted_risk_ids: list[str]
    created_by_user_id: str
    created_at: Optional[str] = None


class ApplySuggestionsResponse(BaseModel):
    """采纳建议响应。"""

    success: bool
    version: OptimizedContractVersionResponse
    message: str = "优化合同版本已生成"
