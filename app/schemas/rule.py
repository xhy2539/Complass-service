"""规则库相关的数据模型。"""

from typing import Optional

from pydantic import BaseModel, Field


class RuleCreateRequest(BaseModel):
    """创建规则请求。"""
    rule_code: str = Field(..., min_length=1, max_length=50)
    contract_type: str = Field(..., min_length=1, max_length=50)
    review_module: str = Field(..., min_length=1, max_length=50)
    risk_name: str = Field(..., min_length=1, max_length=100)
    check_point: Optional[str] = None
    trigger_condition: Optional[str] = None
    default_risk_level: str = Field(..., description="高/中/低")
    suggestion_template: Optional[str] = None
    example_clause: Optional[str] = None
    enabled: bool = True


class RuleUpdateRequest(BaseModel):
    """更新规则请求。"""
    contract_type: Optional[str] = None
    review_module: Optional[str] = None
    risk_name: Optional[str] = None
    check_point: Optional[str] = None
    trigger_condition: Optional[str] = None
    default_risk_level: Optional[str] = None
    suggestion_template: Optional[str] = None
    example_clause: Optional[str] = None
    enabled: Optional[bool] = None


class RuleEnabledRequest(BaseModel):
    """启用或停用规则请求。"""
    enabled: bool


class RuleVersionCreateRequest(BaseModel):
    """创建规则版本请求。"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class RuleResponse(BaseModel):
    """规则响应。"""
    id: str
    version_id: str
    rule_code: str
    contract_type: str
    review_module: str
    risk_name: str
    check_point: Optional[str] = None
    trigger_condition: Optional[str] = None
    default_risk_level: str
    suggestion_template: Optional[str] = None
    example_clause: Optional[str] = None
    enabled: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RuleListResponse(BaseModel):
    """规则列表响应。"""
    rules: list[RuleResponse]
    total: int
    skip: int
    limit: int


class RuleVersionResponse(BaseModel):
    """规则版本响应。"""
    id: str
    version_no: int
    name: str
    description: Optional[str] = None
    status: str
    activated_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    rule_count: int = 0


class CsvImportErrorItem(BaseModel):
    """CSV 导入错误项。"""
    row: int
    field: str
    message: str


class CsvImportResponse(BaseModel):
    """CSV 导入响应。"""
    success: bool
    version_id: Optional[str] = None
    version_no: Optional[int] = None
    imported_count: int = 0
    errors: list[CsvImportErrorItem] = []
