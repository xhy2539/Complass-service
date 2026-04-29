"""应用启动入口，负责创建 FastAPI 实例并挂载基础路由。"""

from fastapi import FastAPI

from app.api.v1.contract_review_api import contract_review_api_router
from app.core.complass_service_settings import get_complass_service_settings


def create_app() -> FastAPI:
    """创建 FastAPI 应用并挂载版本化路由。"""
    settings = get_complass_service_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="合规罗盘 V0 后端服务",
    )
    application.include_router(contract_review_api_router, prefix="/api/v1")

    @application.get("/health")
    def health_check() -> dict[str, str]:
        """返回服务存活状态，供 CI 和部署探针使用。"""
        return {"status": "ok", "service": settings.service_name}

    return application


app = create_app()
