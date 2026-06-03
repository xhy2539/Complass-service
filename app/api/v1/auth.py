"""用户认证路由，包含注册、登录功能。"""

import secrets
import uuid
from datetime import datetime
from datetime import timedelta
from typing import Annotated
from urllib.parse import quote
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.orm import Session

from app.core.complass_service_settings import get_complass_service_settings
from app.core.security import create_access_token
from app.core.security import decode_access_token
from app.core.security import hash_password
from app.core.security import verify_password
from app.models.database import User
from app.models.database_connection import get_db
from app.schemas.auth import TokenResponse
from app.schemas.auth import UserInfo
from app.schemas.auth import UserLoginRequest
from app.schemas.auth import UserRegisterRequest
from app.services.redis_service import get_redis_service

auth_router = APIRouter(prefix="/auth", tags=["用户认证"])
security = HTTPBearer()  # API 文档中的认证组件

settings = get_complass_service_settings()

_feishu_app_access_token: str | None = None
_feishu_app_access_token_expire_at: datetime | None = None


def _uuid() -> str:
    """生成 UUID。"""
    return str(uuid.uuid4())


def _create_token_response(user: User) -> TokenResponse:
    """为用户创建 token 响应。"""
    access_token = create_access_token(data={"sub": user.id, "email": user.email})
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
        user=UserInfo.model_validate(user.to_dict()),
    )


def _sanitize_next(next_path: str | None) -> str:
    if not next_path:
        return "/"
    next_path = next_path.strip()
    if not next_path.startswith("/"):
        return "/"
    if next_path.startswith("//"):
        return "/"
    return next_path


def _get_frontend_base_url() -> str:
    base = (
        getattr(settings, "frontend_base_url", "")
        or getattr(settings, "frontend_url", "")
        or ""
    ).strip()
    return base.rstrip("/")


def _get_feishu_app_access_token() -> str:
    global _feishu_app_access_token
    global _feishu_app_access_token_expire_at

    if _feishu_app_access_token and _feishu_app_access_token_expire_at:
        if datetime.utcnow() < _feishu_app_access_token_expire_at:
            return _feishu_app_access_token

    app_id = settings.feishu_app_id
    app_secret = settings.feishu_app_secret
    if not app_id or not app_secret:
        raise HTTPException(status_code=500, detail="缺少飞书 App ID 或 App Secret")

    url = "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal"
    payload = {"app_id": app_id, "app_secret": app_secret}
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        resp.raise_for_status()
        data = resp.json()
    if data.get("code") != 0:
        raise HTTPException(
            status_code=500, detail=f"获取飞书 app_access_token 失败: {data.get('msg')}"
        )

    token = data.get("app_access_token")
    expire = int(data.get("expire") or 0)
    if not token or expire <= 0:
        raise HTTPException(
            status_code=500, detail="获取飞书 app_access_token 失败: 返回数据异常"
        )

    _feishu_app_access_token = token
    _feishu_app_access_token_expire_at = datetime.utcnow() + timedelta(
        seconds=max(expire - 60, 60)
    )
    return token


@auth_router.post(
    "/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    request: UserRegisterRequest, db: Session = Depends(get_db)
) -> TokenResponse:
    """
    用户注册。

    - email: 邮箱（唯一）
    - phone: 手机号（必填）
    - nickname: 昵称
    - password: 密码（至少6位）
    """
    # 检查邮箱是否已存在
    existing_user = db.query(User).filter(User.email == request.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="该邮箱已被注册"
        )

    # 创建用户
    user = User(
        id=_uuid(),
        email=request.email,
        phone=request.phone,
        nickname=request.nickname,
        hashed_password=hash_password(request.password),
        is_active=True,
        is_verified=False,
        created_at=datetime.utcnow(),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return _create_token_response(user)


@auth_router.post("/login", response_model=TokenResponse)
async def login(
    request: UserLoginRequest, db: Session = Depends(get_db)
) -> TokenResponse:
    """
    用户登录，支持邮箱或手机号。

    - account: 邮箱或手机号
    - password: 密码
    """
    # 查找用户（邮箱或手机号）
    account = request.account or request.email
    user = (
        db.query(User).filter((User.email == account) | (User.phone == account)).first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误"
        )

    # 验证密码
    if not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误"
        )

    # 检查用户状态
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="用户已被禁用"
        )

    # 更新最后登录时间
    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)

    return _create_token_response(user)


@auth_router.get("/feishu/login")
def feishu_login(request: Request, next: str | None = None):
    next_path = _sanitize_next(next)
    state = secrets.token_urlsafe(24)

    redis = get_redis_service()
    redis.set_oauth_state(state, {"next": next_path}, expire_seconds=300)

    redirect_uri = (settings.feishu_oauth_redirect_uri or "").strip()
    if not redirect_uri:
        redirect_uri = str(request.url_for("feishu_oauth_callback"))

    feishu_url = "https://open.feishu.cn/open-apis/authen/v1/index"
    query = {
        "app_id": settings.feishu_app_id,
        "redirect_uri": quote(redirect_uri, safe=""),
        "state": state,
    }
    url = f"{feishu_url}?app_id={query['app_id']}&redirect_uri={query['redirect_uri']}&state={query['state']}"
    return RedirectResponse(url=url, status_code=302)


@auth_router.get("/feishu/callback", name="feishu_oauth_callback")
def feishu_callback(
    code: str | None = None, state: str | None = None, db: Session = Depends(get_db)
):
    if not code:
        raise HTTPException(status_code=400, detail="缺少 code")
    if not state:
        raise HTTPException(status_code=400, detail="缺少 state")

    redis = get_redis_service()
    state_payload = redis.pop_oauth_state(state)
    if not state_payload:
        raise HTTPException(status_code=400, detail="state 无效或已过期")
    next_path = _sanitize_next(state_payload.get("next"))

    app_access_token = _get_feishu_app_access_token()
    token_url = "https://open.feishu.cn/open-apis/authen/v1/access_token"
    headers = {
        "Authorization": f"Bearer {app_access_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = {"grant_type": "authorization_code", "code": code}
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(token_url, headers=headers, json=payload)
        resp.raise_for_status()
        body = resp.json()
    if body.get("code") != 0:
        raise HTTPException(
            status_code=400,
            detail=f"飞书换取 user_access_token 失败: {body.get('msg')}",
        )
    data = body.get("data") or {}
    open_id = data.get("open_id") or ""
    union_id = data.get("union_id") or ""
    name = data.get("name") or data.get("en_name") or ""
    email = (data.get("email") or data.get("enterprise_email") or "").strip()
    mobile = (data.get("mobile") or "").strip()

    if not open_id:
        raise HTTPException(status_code=400, detail="飞书返回缺少 open_id")

    user = db.query(User).filter(User.feishu_open_id == open_id).first()
    if not user and union_id:
        user = db.query(User).filter(User.feishu_union_id == union_id).first()
    if not user and email:
        user = db.query(User).filter(User.email == email).first()
    if not user and mobile:
        user = db.query(User).filter(User.phone == mobile).first()
    if not user:
        deterministic_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"feishu:{open_id}")
        user = db.query(User).filter(User.id == str(deterministic_uuid)).first()

    if not user:
        user = User(
            id=_uuid(),
            email=email or f"{open_id}@feishu.local",
            phone=mobile or "",
            nickname=name or f"feishu_{open_id[-6:]}",
            hashed_password=hash_password(secrets.token_urlsafe(24)),
            is_active=True,
            is_verified=True,
            created_at=datetime.utcnow(),
            feishu_open_id=open_id,
            feishu_union_id=union_id or None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.feishu_open_id = open_id
        if union_id:
            user.feishu_union_id = union_id
        if name and (not user.nickname or user.nickname.startswith("feishu_")):
            user.nickname = name
        if email and user.email.endswith("@feishu.local"):
            user.email = email
        if mobile and not user.phone:
            user.phone = mobile
        if not user.is_active:
            user.is_active = True
        user.last_login_at = datetime.utcnow()
        db.commit()
        db.refresh(user)

    token_response = _create_token_response(user)
    frontend = _get_frontend_base_url()
    feishu_path = (
        getattr(settings, "frontend_feishu_auth_path", "/auth/feishu") or "/auth/feishu"
    )
    if not feishu_path.startswith("/"):
        feishu_path = f"/{feishu_path}"
    redirect_target = f"{frontend}{feishu_path}"
    qs = urlencode(
        {
            "token": token_response.access_token,
            "expires_in": token_response.expires_in,
            "next": next_path,
        }
    )
    return RedirectResponse(url=f"{redirect_target}?{qs}", status_code=302)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Session = Depends(get_db),
) -> User:
    """
    获取当前登录用户（认证依赖项）。

    用法:
        @router.get("/xxx")
        async def xxx(current_user: User = Depends(get_current_user)):
            ...

    Args:
        credentials: HTTP Bearer 认证凭据
        db: 数据库会话

    Returns:
        当前登录的 User 对象

    Raises:
        HTTPException: token 无效或用户不存在
    """
    token = credentials.credentials

    # 解码 token
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token 已过期或无效",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 获取用户 ID
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token 格式错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 查询用户
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="用户已被禁用"
        )

    return user


@auth_router.get("/me", response_model=UserInfo)
def me(current_user: User = Depends(get_current_user)) -> UserInfo:
    return UserInfo.model_validate(current_user.to_dict())


class SetTokenQuotaRequest(BaseModel):
    user_id: str = Field(..., description="目标用户 ID")
    token_quota: int = Field(..., ge=0, description="Token 配额，0 表示无限制")


@auth_router.patch("/admin/token-quota")
def set_user_token_quota(
    request: SetTokenQuotaRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """管理员设置用户的 Token 配额。"""
    settings = get_complass_service_settings()
    admin_email = settings.admin_email or "1121799294@qq.com"
    if current_user.email != admin_email:
        raise HTTPException(status_code=403, detail="仅管理员可操作")

    target_user = db.query(User).filter(User.id == request.user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    target_user.token_quota = request.token_quota
    db.commit()

    return {
        "user_id": target_user.id,
        "email": target_user.email,
        "token_quota": target_user.token_quota,
        "token_used": target_user.token_used,
    }
