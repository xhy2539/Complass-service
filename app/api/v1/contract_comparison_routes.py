"""合同版本比对路由占位，后续实现旧版/新版合同比对接口。"""

from fastapi import APIRouter

contract_comparison_router = APIRouter(tags=["合同版本比对"])
