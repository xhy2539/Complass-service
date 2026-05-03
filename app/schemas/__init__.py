"""数据结构包，后续放置请求体、响应体和领域 DTO。"""

from app.schemas.review import (
    RiskPointSchema,
    RiskStatsSchema,
    ReviewTaskSchema,
    ReviewTaskCreateResponse,
    ReviewTaskQueryResponse,
    RiskStatusUpdateRequest,
    RiskStatusUpdateResponse,
    RiskListResponse
)
from app.schemas.comparison import (
    ComparisonTaskSchema,
    ComparisonTaskCreateResponse,
    ComparisonTaskQueryResponse,
    ComparisonRiskPointSchema
)

__all__ = [
    "RiskPointSchema",
    "RiskStatsSchema",
    "ReviewTaskSchema",
    "ReviewTaskCreateResponse",
    "ReviewTaskQueryResponse",
    "RiskStatusUpdateRequest",
    "RiskStatusUpdateResponse",
    "RiskListResponse",
    "ComparisonTaskSchema",
    "ComparisonTaskCreateResponse",
    "ComparisonTaskQueryResponse",
    "ComparisonRiskPointSchema"
]
