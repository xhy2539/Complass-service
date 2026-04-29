"""风险点人工确认路由占位，后续实现确认和忽略状态流转。"""

from fastapi import APIRouter

risk_manual_decision_router = APIRouter(tags=["风险点人工确认"])
