"""应用启动入口，负责创建 FastAPI 实例并挂载基础路由。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer

from app.api.v1.audit_rules_api import audit_rules_router
from app.api.v1.contract_comparison_routes import recover_pending_comparison_tasks
from app.api.v1.contract_review_api import contract_review_api_router
from app.api.v1.contract_review_routes import recover_pending_review_tasks
from app.api.v1.feishu_webhook import feishu_router
from app.core.complass_service_settings import get_complass_service_settings
from app.models.database_connection import init_db

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# 全局安全依赖，API 文档中会显示认证组件
security = HTTPBearer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理，启动时初始化数据库。"""
    init_db()  # 启动时创建所有表
    review_count = recover_pending_review_tasks()
    comparison_count = recover_pending_comparison_tasks()
    if review_count or comparison_count:
        logging.info(
            "Recovered pending tasks: reviews=%s, comparisons=%s",
            review_count,
            comparison_count,
        )
    yield


def create_app() -> FastAPI:
    """创建 FastAPI 应用并挂载版本化路由。"""
    settings = get_complass_service_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="合规罗盘 V0 后端服务",
        lifespan=lifespan,
    )

    # 配置 CORS，允许列表通过环境变量/配置管理
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            origin.strip() for origin in settings.cors_allow_origins.split(",")
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(contract_review_api_router, prefix="/api/v1")
    application.include_router(audit_rules_router)
    application.include_router(feishu_router, prefix="/api/v1")

    @application.get("/health")
    def health_check() -> dict[str, str]:
        """返回服务存活状态，供 CI 和部署探针使用。"""
        return {"status": "ok", "service": settings.service_name}

    return application


app = create_app()
