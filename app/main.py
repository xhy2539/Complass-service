"""应用启动入口，负责创建 FastAPI 实例并挂载基础路由。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import Request
from fastapi import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer

from app.api.v1.audit_rules_api import audit_rules_router
from app.api.v1.contract_comparison_routes import recover_pending_comparison_tasks
from app.api.v1.contract_review_api import contract_review_api_router
from app.api.v1.contract_review_routes import recover_pending_review_tasks
from app.api.v1.reverse_rule_routes import recover_pending_reverse_rule_tasks
from app.api.v1.reverse_rule_routes import reverse_rule_candidate_router
from app.api.v1.reverse_rule_routes import reverse_rule_router
from app.core.complass_service_settings import get_complass_service_settings
from app.models.database_connection import init_db
from app.services.feishu_bot import handle_feishu_callback

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger().setLevel(logging.INFO)

# 全局安全依赖，API 文档中会显示认证组件
security = HTTPBearer()


# 生命周期函数（只初始化数据库，不再启动长连接）
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理，启动时初始化数据库。"""
    init_db()  # 启动时创建所有表
    review_count = recover_pending_review_tasks()
    comparison_count = recover_pending_comparison_tasks()
    reverse_rule_count = recover_pending_reverse_rule_tasks()
    if review_count or comparison_count or reverse_rule_count:
        logging.info(
            "Recovered pending tasks: reviews=%s, comparisons=%s, reverse_rules=%s",
            review_count,
            comparison_count,
            reverse_rule_count,
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

    @application.middleware("http")
    async def _log_incoming_requests(request: Request, call_next):
        try:
            logging.info("[HTTP] %s %s", request.method, request.url.path)
        except Exception:
            pass
        response = await call_next(request)
        try:
            logging.info(
                "[HTTP] %s %s -> %s",
                request.method,
                request.url.path,
                response.status_code,
            )
        except Exception:
            pass
        return response

    origins = [
        origin.strip()
        for origin in settings.cors_allow_origins.split(",")
        if origin.strip()
    ]
    extra_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        getattr(settings, "frontend_base_url", ""),
        getattr(settings, "frontend_url", ""),
        "https://open.feishu.cn",
    ]
    allow_origins = list(dict.fromkeys([*origins, *[o for o in extra_origins if o]]))

    application.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 挂载原有业务路由
    application.include_router(contract_review_api_router, prefix="/api/v1")
    application.include_router(audit_rules_router)
    application.include_router(reverse_rule_router, prefix="/api/v1")
    application.include_router(reverse_rule_candidate_router, prefix="/api/v1")

    # 👉 挂载飞书回调路由（关键）
    @application.post("/api/feishu/callback")
    async def feishu_callback(request: Request) -> Response:
        return await handle_feishu_callback(request)

    @application.post("/api/feishu/callback/")
    async def feishu_callback_slash(request: Request) -> Response:
        return await handle_feishu_callback(request)

    # 健康检查接口
    @application.get("/health")
    def health_check() -> dict[str, str]:
        """返回服务存活状态，供 CI 和部署探针使用。"""
        return {"status": "ok", "service": settings.service_name}

    return application


app = create_app()
