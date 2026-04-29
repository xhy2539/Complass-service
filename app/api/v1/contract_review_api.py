"""合同审查 V1 API 聚合入口，集中挂载当前业务路由占位。"""

from fastapi import APIRouter

from app.api.v1.contract_comparison_routes import contract_comparison_router
from app.api.v1.contract_review_routes import contract_review_router
from app.api.v1.risk_manual_decision_routes import risk_manual_decision_router

contract_review_api_router = APIRouter()
contract_review_api_router.include_router(contract_review_router)
contract_review_api_router.include_router(contract_comparison_router)
contract_review_api_router.include_router(risk_manual_decision_router)
