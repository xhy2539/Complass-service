"""JWT 认证安全模块，包含 token 生成、验证和密码哈希功能。"""

from datetime import datetime, timedelta
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.complass_service_settings import get_complass_service_settings

settings = get_complass_service_settings()

# 密码哈希上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码是否正确。"""
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    """对密码进行哈希。"""
    return pwd_context.hash(password)


def create_access_token(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    创建 JWT access token。

    Args:
        data: 要编码到 token 中的数据
        expires_delta: token 过期时间，不提供则使用默认配置

    Returns:
        编码后的 JWT token 字符串
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """
    解码并验证 JWT token。

    Args:
        token: JWT token 字符串

    Returns:
        解码后的数据字典，验证失败返回 None
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError:
        return None
