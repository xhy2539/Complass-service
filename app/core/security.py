"""JWT 认证安全模块，包含 token 生成、验证和密码哈希功能。"""

import base64
import hashlib
import json
from datetime import datetime
from datetime import timedelta
from typing import Any
from typing import Optional

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers import modes
from jose import JWTError
from jose import jwt
from passlib.context import CryptContext

from app.core.complass_service_settings import get_complass_service_settings

settings = get_complass_service_settings()


def decrypt_feishu_data(encrypt_str: str, encrypt_key: str) -> dict:
    """
    解密飞书回调数据。

    飞书官方加密说明：
    - 使用 AES-256-CBC 算法
    - encrypt_key 是 Base64 编码的 AES 密钥 (32字节)
    - 加密数据格式：Base64(IV[16字节] + AES加密后的数据)
    - 填充方式：PKCS7

    Args:
        encrypt_str: 加密的字符串
        encrypt_key: 飞书开放平台配置的加密密钥

    Returns:
        解密后的 JSON 数据字典
    """
    try:
        # 修复 Base64 padding（飞书有时会省略末尾的 =）
        padding_needed = 4 - len(encrypt_str) % 4
        if padding_needed != 4:
            encrypt_str += "=" * padding_needed

        # Base64 解码加密数据
        encrypt_bytes = base64.b64decode(encrypt_str)

        encrypt_key = (encrypt_key or "").strip()
        if not encrypt_key:
            raise ValueError("缺少 encrypt_key")

        key = None

        # 优先尝试：按飞书文档将 encrypt_key 当作 Base64 密钥解码得到 32 字节
        try:
            key_padding_needed = 4 - len(encrypt_key) % 4
            key_b64 = encrypt_key + (
                "=" * key_padding_needed if key_padding_needed != 4 else ""
            )
            key_bytes = base64.b64decode(key_b64)
            if len(key_bytes) == 32:
                key = key_bytes
        except Exception:
            key = None

        # 兼容：部分场景 encrypt_key 不是 Base64（或解码后不是 32 字节），直接对原始字符串做 SHA256 作为 AES key
        if key is None:
            key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()

        # 加密数据格式：前16字节是 IV，后面是加密数据
        if len(encrypt_bytes) < 16:
            raise ValueError(
                f"加密数据过短，无法提取IV。数据长度: {len(encrypt_bytes)} 字节"
            )

        iv = encrypt_bytes[:16]
        encrypted_data = encrypt_bytes[16:]

        # AES CBC 解密
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        decrypted_bytes = decryptor.update(encrypted_data) + decryptor.finalize()

        # PKCS7 去填充
        unpadder = padding.PKCS7(128).unpadder()
        unpadded_bytes = unpadder.update(decrypted_bytes) + unpadder.finalize()

        # 解析 JSON
        return json.loads(unpadded_bytes.decode("utf-8"))
    except Exception as e:
        raise Exception(f"飞书数据解密失败: {str(e)}")


# 密码哈希上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码是否正确。"""
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    """对密码进行哈希。"""
    return pwd_context.hash(password)


def create_access_token(
    data: dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
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
        expire = datetime.utcnow() + timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
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
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError:
        return None
