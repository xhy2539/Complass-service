"""IM 会话管理服务，基于 Redis 存储临时文件交互状态。"""

import json
import uuid
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from redis import Redis

SESSION_TTL = 1800  # 30 分钟
KEY_PREFIX_SESSION = "feishu:session"
KEY_PREFIX_OPEN_ID = "feishu:open_id"
TMP_DIR = "/tmp/complass-im"


class IMSessionService:
    """管理飞书/IM 临时会话的文件、状态和上下文字段。"""

    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client
        self.ttl = SESSION_TTL

    # ---- public helpers ----

    @staticmethod
    def new_session_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def expires_iso() -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=SESSION_TTL)).isoformat()

    # ---- core API ----

    def create(self, session_id: str, data: dict[str, Any]) -> None:
        """创建新会话。"""
        data.setdefault("session_id", session_id)
        data.setdefault("created_at", self.now_iso())
        data.setdefault("expires_at", self.expires_iso())
        data.setdefault("status", "waiting_for_action")
        data.setdefault("files", [])
        self.redis.setex(
            f"{KEY_PREFIX_SESSION}:{session_id}",
            self.ttl,
            json.dumps(data, ensure_ascii=False),
        )

    def get(self, session_id: str) -> dict[str, Any] | None:
        raw = self.redis.get(f"{KEY_PREFIX_SESSION}:{session_id}")
        if not raw:
            return None
        return json.loads(raw)

    def update(self, session_id: str, **kwargs: Any) -> None:
        data = self.get(session_id)
        if not data:
            return
        data.update(kwargs)
        self.redis.setex(
            f"{KEY_PREFIX_SESSION}:{session_id}",
            self.ttl,
            json.dumps(data, ensure_ascii=False),
        )

    def add_file(self, session_id: str, file_info: dict[str, Any]) -> None:
        data = self.get(session_id)
        if not data:
            return
        data["files"].append(file_info)
        self.redis.setex(
            f"{KEY_PREFIX_SESSION}:{session_id}",
            self.ttl,
            json.dumps(data, ensure_ascii=False),
        )

    def delete(self, session_id: str) -> None:
        self.redis.delete(f"{KEY_PREFIX_SESSION}:{session_id}")

    # ---- open_id mapping ----

    def set_open_id_mapping(self, open_id: str, session_id: str) -> None:
        self.redis.setex(f"{KEY_PREFIX_OPEN_ID}:{open_id}", self.ttl, session_id)

    def get_by_open_id(self, open_id: str) -> str | None:
        v = self.redis.get(f"{KEY_PREFIX_OPEN_ID}:{open_id}")
        return v if v else None
