"""认证相关的数据模型。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from pydantic import EmailStr
from pydantic import Field


class UserRegisterRequest(BaseModel):
    """用户注册请求。"""

    email: EmailStr = Field(..., description="邮箱地址")
    phone: str = Field(..., min_length=11, max_length=20, description="手机号")
    nickname: str = Field(..., min_length=1, max_length=100, description="昵称")
    password: str = Field(
        ..., min_length=6, max_length=128, description="密码（至少6位）"
    )


class UserLoginRequest(BaseModel):
    """用户登录请求，支持邮箱或手机号。"""

    account: str = Field(..., min_length=5, max_length=255, description="邮箱或手机号")
    password: str = Field(..., description="密码")


class TokenResponse(BaseModel):
    """登录/注册成功响应。"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒
    user: "UserInfo"


class UserInfo(BaseModel):
    """用户信息。"""

    id: str
    email: str
    phone: str = ""
    nickname: str
    is_active: bool = True
    is_verified: bool = False
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    token_quota: int = 0
    token_used: int = 0

    class Config:
        from_attributes = True


class UserResponse(BaseModel):
    """用户信息响应。"""

    id: str
    email: str
    phone: str = ""
    nickname: str
    is_active: bool
    is_verified: bool
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None

    class Config:
        from_attributes = True
