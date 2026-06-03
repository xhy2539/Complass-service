"""Redis 服务模块，提供飞书多轮会话所需的缓存功能。"""

import json
import logging
import uuid
from datetime import datetime
from datetime import timedelta
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from redis import Redis
from redis.exceptions import RedisError

from app.core.complass_service_settings import get_complass_service_settings

logger = logging.getLogger(__name__)


class RedisSessionStatus:
    WAITING_FOR_ACTION = "waiting_for_action"
    WAITING_FOR_SECOND_FILE = "waiting_for_second_file"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class RedisService:
    """Redis 服务类，封装飞书多轮会话所需的操作。"""

    SESSION_EXPIRE_SECONDS = 1800

    def __init__(self):
        settings = get_complass_service_settings()
        self._client = Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            decode_responses=True,
        )
        self._test_connection()

    def _test_connection(self):
        """测试 Redis 连接是否正常。"""
        try:
            self._client.ping()
            logger.info("[Redis] 连接成功")
        except RedisError as e:
            logger.error(f"[Redis] 连接失败: {e}")
            raise

    def _get_session_key(self, session_id: str) -> str:
        """获取会话的 Redis key。"""
        return f"feishu:session:{session_id}"

    def create_session(
        self,
        feishu_open_id: str,
        chat_id: str,
        message_id: str,
        feishu_user_id: Optional[str] = None,
        phone: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """
        创建新的会话。

        :param feishu_open_id: 飞书用户 open_id
        :param chat_id: 飞书会话 ID
        :param message_id: 原始消息 ID
        :param feishu_user_id: 飞书用户 ID
        :param phone: 手机号
        :param user_id: 系统用户 ID
        :return: session_id
        """
        session_id = str(uuid.uuid4())
        key = self._get_session_key(session_id)

        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=self.SESSION_EXPIRE_SECONDS)

        session_data = {
            "session_id": session_id,
            "platform": "feishu",
            "feishu_open_id": feishu_open_id,
            "feishu_user_id": feishu_user_id or "",
            "phone": phone or "",
            "user_id": user_id or "",
            "chat_id": chat_id,
            "message_id": message_id,
            "status": RedisSessionStatus.WAITING_FOR_ACTION,
            "files": "[]",
            "created_at": now.isoformat() + "+08:00",
            "expires_at": expires_at.isoformat() + "+08:00",
        }

        try:
            self._client.hset(key, mapping=session_data)
            self._client.expire(key, self.SESSION_EXPIRE_SECONDS)

            self._client.set(
                f"feishu:open_id:{feishu_open_id}:session",
                session_id,
                ex=self.SESSION_EXPIRE_SECONDS,
            )

            logger.info(f"[Redis] 创建会话: {session_id}, open_id: {feishu_open_id}")
            return session_id

        except RedisError as e:
            logger.error(f"[Redis] 创建会话失败: {e}")
            raise

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话数据。

        :param session_id: 会话 ID
        :return: 会话数据字典
        """
        key = self._get_session_key(session_id)
        try:
            data = self._client.hgetall(key)
            if not data:
                return None

            data["files"] = json.loads(data.get("files", "[]"))
            return data

        except (RedisError, json.JSONDecodeError) as e:
            logger.error(f"[Redis] 获取会话失败: {e}")
            return None

    def get_session_by_open_id(self, feishu_open_id: str) -> Optional[Dict[str, Any]]:
        """
        通过 open_id 获取当前会话。

        :param feishu_open_id: 飞书用户 open_id
        :return: 会话数据字典
        """
        session_id = self._client.get(f"feishu:open_id:{feishu_open_id}:session")
        if not session_id:
            return None
        return self.get_session(session_id)

    def update_session_status(self, session_id: str, status: str) -> bool:
        """
        更新会话状态。

        :param session_id: 会话 ID
        :param status: 新状态
        :return: 是否成功
        """
        key = self._get_session_key(session_id)
        try:
            if self._client.exists(key):
                self._client.hset(key, "status", status)
                logger.debug(f"[Redis] 更新会话状态: {session_id} -> {status}")
                return True
            return False

        except RedisError as e:
            logger.error(f"[Redis] 更新会话状态失败: {e}")
            return False

    def add_file_to_session(
        self,
        session_id: str,
        file_info: Dict[str, Any],
        role: str = "first",
    ) -> bool:
        """
        添加文件到会话。

        :param session_id: 会话 ID
        :param file_info: 文件信息
        :param role: first 或 second
        :return: 是否成功
        """
        key = self._get_session_key(session_id)
        try:
            data = self._client.hgetall(key)
            if not data:
                return False

            files = json.loads(data.get("files", "[]"))

            file_entry = {
                "role": role,
                "file_name": file_info.get("file_name", "unknown"),
                "content_type": file_info.get("content_type", ""),
                "file_path": file_info.get("file_path", ""),
                "source_file_key": file_info.get("file_key", ""),
                "message_id": file_info.get("message_id", ""),
                "uploaded_at": datetime.utcnow().isoformat() + "+08:00",
            }
            files.append(file_entry)

            self._client.hset(key, "files", json.dumps(files, ensure_ascii=False))
            logger.debug(
                f"[Redis] 添加文件到会话: {session_id}, file: {file_info.get('file_name')}"
            )
            return True

        except (RedisError, json.JSONDecodeError) as e:
            logger.error(f"[Redis] 添加文件到会话失败: {e}")
            return False

    def get_session_files(self, session_id: str) -> List[Dict[str, Any]]:
        """
        获取会话中的文件列表。

        :param session_id: 会话 ID
        :return: 文件列表
        """
        session = self.get_session(session_id)
        if not session:
            return []
        return session.get("files", [])

    def delete_session(self, session_id: str) -> bool:
        """
        删除会话。

        :param session_id: 会话 ID
        :return: 是否成功
        """
        key = self._get_session_key(session_id)
        try:
            session = self.get_session(session_id)
            if session:
                self._client.delete(
                    f"feishu:open_id:{session['feishu_open_id']}:session"
                )
            self._client.delete(key)
            logger.debug(f"[Redis] 删除会话: {session_id}")
            return True

        except RedisError as e:
            logger.error(f"[Redis] 删除会话失败: {e}")
            return False

    def mark_message(self, message_id: str, expire_seconds: int = 300) -> bool:
        """
        标记消息已处理，防止重复处理。

        :param message_id: 消息 ID
        :param expire_seconds: 过期时间
        :return: 如果是新消息返回 True，已存在返回 False
        """
        key = f"feishu:msg:{message_id}"
        try:
            result = self._client.set(key, "1", nx=True, ex=expire_seconds)
            return result is not None

        except RedisError as e:
            logger.error(f"[Redis] 标记消息失败: {e}")
            return False

    def is_message_processed(self, message_id: str) -> bool:
        """
        检查消息是否已处理。

        :param message_id: 消息 ID
        :return: 是否已处理
        """
        key = f"feishu:msg:{message_id}"
        try:
            return self._client.exists(key) == 1

        except RedisError as e:
            logger.error(f"[Redis] 检查消息状态失败: {e}")
            return False

    def extend_session_expire(self, session_id: str) -> bool:
        """
        延长会话过期时间。

        :param session_id: 会话 ID
        :return: 是否成功
        """
        key = self._get_session_key(session_id)
        try:
            if self._client.exists(key):
                self._client.expire(key, self.SESSION_EXPIRE_SECONDS)

                session = self.get_session(session_id)
                if session:
                    self._client.set(
                        f"feishu:open_id:{session['feishu_open_id']}:session",
                        session_id,
                        ex=self.SESSION_EXPIRE_SECONDS,
                    )
                return True
            return False

        except RedisError as e:
            logger.error(f"[Redis] 延长会话过期时间失败: {e}")
            return False

    def set_oauth_state(
        self, state: str, payload: dict, expire_seconds: int = 300
    ) -> bool:
        key = f"feishu:oauth:state:{state}"
        try:
            self._client.set(
                key, json.dumps(payload, ensure_ascii=False), ex=expire_seconds
            )
            return True
        except RedisError as e:
            logger.error(f"[Redis] 写入 OAuth state 失败: {e}")
            return False

    def pop_oauth_state(self, state: str) -> Optional[dict]:
        key = f"feishu:oauth:state:{state}"
        try:
            value = self._client.get(key)
            if not value:
                return None
            self._client.delete(key)
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        except RedisError as e:
            logger.error(f"[Redis] 读取 OAuth state 失败: {e}")
            return None


_redis_service: Optional[RedisService] = None


def get_redis_service() -> RedisService:
    """获取 Redis 服务单例。"""
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService()
    return _redis_service
