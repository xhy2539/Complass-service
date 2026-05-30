"""飞书 API 封装：获取 tenant token、下载文件、发送消息。"""

import json
import logging
import os
import time
from typing import Any

import httpx

from app.core.complass_service_settings import get_complass_service_settings

logger = logging.getLogger(__name__)

# 简单内存缓存 tenant token（不需要 Redis）
_cached_token: str = ""
_cached_token_expire: float = 0.0
TOKEN_REFRESH_MARGIN = 300  # 提前 5 分钟刷新


def _settings():
    return get_complass_service_settings()


# ---- Tenant Access Token ----


async def get_tenant_access_token() -> str:
    """获取飞书 tenant_access_token，带简单内存缓存。"""
    global _cached_token, _cached_token_expire

    now = time.time()
    if _cached_token and now < _cached_token_expire - TOKEN_REFRESH_MARGIN:
        return _cached_token

    s = _settings()
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            url,
            json={"app_id": s.feishu_app_id, "app_secret": s.feishu_app_secret},
        )
        r.raise_for_status()
        data = r.json()
        code = data.get("code")
        if code != 0:
            raise RuntimeError(f"获取飞书 token 失败: {data.get('msg')}")

        _cached_token = data["tenant_access_token"]
        _cached_token_expire = now + data.get("expire", 7200)
        logger.info("[Feishu] tenant_access_token 已刷新")
        return _cached_token


# ---- 文件下载 ----


async def download_file(message_id: str, file_key: str, save_path: str) -> int:
    """从飞书下载文件到本地路径，返回文件大小。"""
    token = await get_tenant_access_token()
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{file_key}?type=file"
    headers = {"Authorization": f"Bearer {token}"}

    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        with open(save_path, "wb") as f:
            f.write(r.content)
        logger.info(f"[Feishu] 文件已下载: {save_path} ({len(r.content)} bytes)")
        return len(r.content)


# ---- 发送消息 ----


async def send_card_message(chat_id: str, card: dict[str, Any]) -> dict[str, Any]:
    """发送飞书卡片消息。"""
    token = await get_tenant_access_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    body = {
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"发送飞书消息失败: {data.get('msg')}")
        logger.info(f"[Feishu] 卡片已发送到 chat_id={chat_id}")
        return data


async def send_text_message(chat_id: str, text: str) -> dict[str, Any]:
    """发送飞书文本消息。"""
    token = await get_tenant_access_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    body = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"发送飞书消息失败: {data.get('msg')}")
        logger.info(f"[Feishu] 文本已发送到 chat_id={chat_id}")
        return data


# ---- 卡片构建 ----


def build_action_card(session_id: str, file_name: str) -> dict[str, Any]:
    """构建 [审查] [比对] 选择卡片。"""
    return {
        "header": {"title": {"content": "合同审查", "tag": "plain_text"}},
        "elements": [
            {
                "tag": "div",
                "text": {
                    "content": f"已收到文件：**{file_name}**\n请选择操作：",
                    "tag": "lark_md",
                },
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"content": "📋 审查", "tag": "plain_text"},
                        "type": "primary",
                        "value": {"session_id": session_id, "action": "review"},
                    },
                    {
                        "tag": "button",
                        "text": {"content": "🔍 比对", "tag": "plain_text"},
                        "type": "default",
                        "value": {"session_id": session_id, "action": "compare"},
                    },
                ],
            },
        ],
    }


def build_result_card(task_id: str, task_type: str, file_name: str) -> dict[str, Any]:
    """构建结果链接卡片。"""
    view = "review" if task_type == "review" else "comparison"
    url = f"http://82.156.132.43/?task_id={task_id}&view={view}"
    return {
        "header": {"title": {"content": "审查完成", "tag": "plain_text"}},
        "elements": [
            {
                "tag": "div",
                "text": {
                    "content": f"**{file_name}** 已处理完成",
                    "tag": "lark_md",
                },
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"content": "查看结果", "tag": "plain_text"},
                        "type": "primary",
                        "url": url,
                    }
                ],
            },
            {"tag": "hr"},
            {"tag": "div", "text": {"content": url, "tag": "lark_md"}},
        ],
    }
