"""用户认证路由，包含注册、登录功能。"""

import uuid
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import EmailStr
from sqlalchemy.orm import Session

from app.core.complass_service_settings import get_complass_service_settings
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.models.database import User
from app.models.database_connection import get_db
from app.schemas.auth import (
    TokenResponse,
    UserInfo,
    UserLoginRequest,
    UserRegisterRequest,
)

auth_router = APIRouter(prefix="/auth", tags=["用户认证"])
security = HTTPBearer()  # API 文档中的认证组件

settings = get_complass_service_settings()


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
        user=UserInfo.model_validate(user.to_dict())
    )


@auth_router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: UserRegisterRequest,
    db: Session = Depends(get_db)
) -> TokenResponse:
    """
    用户注册。

    - email: 邮箱（唯一）
    - nickname: 昵称
    - password: 密码（至少6位）
    """
    # 检查邮箱是否已存在
    existing_user = db.query(User).filter(User.email == request.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该邮箱已被注册"
        )

    # 创建用户
    user = User(
        id=_uuid(),
        email=request.email,
        nickname=request.nickname,
        hashed_password=hash_password(request.password),
        is_active=True,
        is_verified=False,
        created_at=datetime.utcnow()
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return _create_token_response(user)


@auth_router.post("/login", response_model=TokenResponse)
async def login(
    request: UserLoginRequest,
    db: Session = Depends(get_db)
) -> TokenResponse:
    """
    用户登录。

    - email: 邮箱
    - password: 密码
    """
    # 查找用户
    user = db.query(User).filter(User.email == request.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误"
        )

    # 验证密码
    if not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误"
        )

    # 检查用户状态
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用"
        )

    # 更新最后登录时间
    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)

    return _create_token_response(user)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Session = Depends(get_db)
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
            headers={"WWW-Authenticate": "Bearer"}
        )

    # 获取用户 ID
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token 格式错误",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # 查询用户
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"}
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用"
        )

    return user
