"""飞书 IM 机器人事件回调路由。"""

import json
import logging
import os
from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from redis import Redis
from sqlalchemy.orm import Session

from app.core.complass_service_settings import get_complass_service_settings
from app.models.database import ComparisonTask
from app.models.database import ReviewTask
from app.models.database import TaskStatus
from app.models.database_connection import get_db
from app.services.document_parser import DocumentParseError
from app.services.document_parser import DocumentParser
from app.services.feishu_service import build_action_card
from app.services.feishu_service import build_result_card
from app.services.feishu_service import download_file
from app.services.feishu_service import send_card_message
from app.services.feishu_service import send_text_message
from app.services.im_session_service import TMP_DIR
from app.services.im_session_service import IMSessionService
from app.services.sanitization_service import sanitize_contract_text

logger = logging.getLogger(__name__)

feishu_router = APIRouter(prefix="/feishu", tags=["飞书机器人"])

# ---- Redis 单例 ----


_redis_client: Redis | None = None


def _get_redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        s = get_complass_service_settings()
        _redis_client = Redis(
            host=s.redis_host, port=s.redis_port, db=s.redis_db, decode_responses=True
        )
    return _redis_client


_session_service: IMSessionService | None = None


def _get_session_service() -> IMSessionService:
    global _session_service
    if _session_service is None:
        _session_service = IMSessionService(_get_redis())
    return _session_service


# ---- 事件回调 ----


@feishu_router.post("/event")
async def feishu_event(
    request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """飞书事件回调入口。"""
    body = await request.json()
    logger.info(f"[Feishu] 收到事件: {json.dumps(body, ensure_ascii=False)[:2000]}")

    # 1. URL 验证（飞书首次配置）
    if body.get("type") == "url_verification":
        return {"challenge": body["challenge"]}

    # 2. 事件回调
    event_data = body.get("event", {})
    if not event_data:
        return {"code": 0}

    event_type = body.get("header", {}).get("event_type", "")

    if event_type == "im.message.receive_v1":
        return await _handle_file_message(event_data, db)

    if event_type == "card.action.trigger":
        return await _handle_card_action(event_data, db)

    # 其他事件忽略
    return {"code": 0}


# ---- 文件消息处理 ----


async def _handle_file_message(event: dict, db: Session) -> dict[str, Any]:
    """用户发送文件到机器人。"""
    message_id = event.get("message", {}).get("message_id", "")
    chat_id = event.get("message", {}).get("chat_id", "")
    sender = event.get("sender", {})
    open_id = sender.get("sender_id", {}).get("open_id", "")

    # 仅处理文件消息
    msg_type = event.get("message", {}).get("message_type", "")
    if msg_type != "file":
        return {"code": 0}

    file_key = event.get("message", {}).get("file_key", "")
    file_name = event.get("message", {}).get("file_name", "合同文件")
    content_type = "application/octet-stream"
    if file_name.endswith(".docx"):
        content_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    elif file_name.endswith(".pdf"):
        content_type = "application/pdf"
    elif file_name.endswith(".txt"):
        content_type = "text/plain"

    if not message_id or not file_key or not chat_id:
        logger.error(
            f"[Feishu] 缺少必要字段: message_id={message_id}, file_key={file_key}"
        )
        return {"code": 0}

    svc = _get_session_service()
    session_id = IMSessionService.new_session_id()

    # 下载文件
    save_dir = os.path.join(TMP_DIR, session_id)
    save_path = os.path.join(save_dir, file_name)
    try:
        size = await download_file(message_id, file_key, save_path)
        logger.info(f"[Feishu] 文件已保存: {save_path} ({size} bytes)")
    except Exception as e:
        logger.error(f"[Feishu] 文件下载失败: {e}")
        await send_text_message(chat_id, "文件下载失败，请稍后重试")
        return {"code": 0}

    # 匹配用户
    user_id = _match_user(db, open_id)

    # 检查是否有旧会话且正在等待第二个文件
    old_sid = svc.get_by_open_id(open_id)
    if old_sid:
        old_session = svc.get(old_sid)
        if old_session and old_session.get("status") == "waiting_for_second_file":
            # 这是比对流程的第二份文件，加到现有会话并立即创建比对
            svc.add_file(
                old_sid,
                {
                    "role": "second",
                    "file_name": file_name,
                    "content_type": content_type,
                    "file_path": save_path,
                    "source_file_key": file_key,
                },
            )
            svc.update(old_sid, status="processing")
            # 重新读取会话（包含第二份文件）
            updated = svc.get(old_sid)
            await _do_compare(updated, old_session["chat_id"], db, svc)
            return {"code": 0}
        svc.delete(old_sid)

    # 创建新会话
    svc.create(
        session_id,
        {
            "platform": "feishu",
            "feishu_open_id": open_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "status": "waiting_for_action",
            "files": [
                {
                    "role": "first",
                    "file_name": file_name,
                    "content_type": content_type,
                    "file_path": save_path,
                    "source_file_key": file_key,
                }
            ],
        },
    )
    svc.set_open_id_mapping(open_id, session_id)

    # 发卡片
    card = build_action_card(session_id, file_name)
    await send_card_message(chat_id, card)

    return {"code": 0}


# ---- 按钮回调 ----


async def _handle_card_action(event: dict, db: Session) -> dict[str, Any]:
    """用户点击卡片按钮。"""
    open_id = event.get("operator", {}).get("open_id", "")
    action_value_str = event.get("action", {}).get("value", "{}")
    try:
        action_value = json.loads(action_value_str)
    except (json.JSONDecodeError, TypeError):
        return {"code": 0}

    session_id = action_value.get("session_id", "")
    action_type = action_value.get("action", "")

    if not session_id or not action_type:
        return {"code": 0}

    svc = _get_session_service()
    session = svc.get(session_id)
    if not session:
        await send_text_message(
            event.get("context", {}).get("chat_id", ""), "会话已过期，请重新发送文件"
        )
        return {"code": 0}

    # 校验操作人
    if session.get("feishu_open_id") != open_id:
        return {"code": 0}

    chat_id = session.get("chat_id", "")

    if action_type == "review":
        return await _do_review(session, chat_id, db, svc)

    if action_type == "compare":
        return await _do_compare(session, chat_id, db, svc)

    return {"code": 0}


async def _do_review(
    session: dict, chat_id: str, db: Session, svc: IMSessionService
) -> dict[str, Any]:
    """创建审查任务并回复链接。"""
    if not session.get("user_id"):
        await send_text_message(chat_id, "请先在系统中绑定飞书账号后再使用审查功能。")
        return {"code": 0}

    file_a = session["files"][0]
    file_path = file_a["file_path"]
    file_name = file_a["file_name"]

    with open(file_path, "rb") as f:
        content = f.read()

    try:
        parse_result = DocumentParser.parse(content, file_name)
    except DocumentParseError as e:
        await send_text_message(chat_id, f"文件解析失败: {e}")
        _cleanup(svc, session)
        return {"code": 0}

    sanitization = sanitize_contract_text(parse_result.text)

    task_id = _uuid()
    task = ReviewTask(
        id=task_id,
        user_id=session.get("user_id"),
        file_name=file_name,
        file_type=parse_result.file_type,
        file_size=len(content),
        text=parse_result.text,
        char_count=parse_result.char_count,
        page_count=parse_result.page_count,
        paragraph_count=len(parse_result.paragraphs),
        sentence_count=len(parse_result.sentences),
        sanitized_text=sanitization.sanitized_text,
        sanitization_mapping_json=sanitization.mappings,
        sanitization_status="completed",
        contract_type="通用",
        paragraphs_json=[p.__dict__ for p in parse_result.paragraphs],
        sentences_json=parse_result.sentences,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.commit()

    card = build_result_card(task_id, "review", file_name)
    await send_card_message(chat_id, card)
    _cleanup(svc, session)
    return {"code": 0}


async def _do_compare(
    session: dict, chat_id: str, db: Session, svc: IMSessionService
) -> dict[str, Any]:
    """处理比对请求——单文件则提示发第二个，双文件则创建任务。"""
    if not session.get("user_id"):
        await send_text_message(chat_id, "请先在系统中绑定飞书账号后再使用比对功能。")
        return {"code": 0}

    files = session["files"]

    if len(files) < 2:
        svc.update(session["session_id"], status="waiting_for_second_file")
        await send_text_message(
            chat_id, "请发送**第二个合同文件**（新版本），用于版本比对"
        )
        return {"code": 0}

    # 双文件就绪，创建比对任务
    file_a, file_b = files[0], files[1]

    with open(file_a["file_path"], "rb") as f:
        content_a = f.read()
    with open(file_b["file_path"], "rb") as f:
        content_b = f.read()

    try:
        old_doc = DocumentParser.parse(content_a, file_a["file_name"])
        new_doc = DocumentParser.parse(content_b, file_b["file_name"])
    except DocumentParseError as e:
        await send_text_message(chat_id, f"文件解析失败: {e}")
        _cleanup(svc, session)
        return {"code": 0}

    task_id = _uuid()
    task = ComparisonTask(
        id=task_id,
        user_id=session.get("user_id"),
        old_file_name=file_a["file_name"],
        new_file_name=file_b["file_name"],
        old_file_type=old_doc.file_type,
        new_file_type=new_doc.file_type,
        old_file_size=len(content_a),
        new_file_size=len(content_b),
        old_char_count=old_doc.char_count,
        new_char_count=new_doc.char_count,
        old_paragraph_count=len(old_doc.paragraphs),
        new_paragraph_count=len(new_doc.paragraphs),
        old_text=old_doc.text,
        new_text=new_doc.text,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.commit()

    card = build_result_card(
        task_id, "comparison", f"{file_a['file_name']} vs {file_b['file_name']}"
    )
    await send_card_message(chat_id, card)
    _cleanup(svc, session)
    return {"code": 0}


# ---- 工具函数 ----


def _match_user(db: Session, open_id: str) -> str | None:
    """尝试用 open_id 匹配已有系统用户。未绑定则返回 None。"""
    from app.models.database import FeishuUser

    fu = db.query(FeishuUser).filter(FeishuUser.feishu_open_id == open_id).first()
    return fu.user_id if fu else None


def _cleanup(svc: IMSessionService, session: dict) -> None:
    """删除 Redis 会话和临时文件。"""
    sid = session.get("session_id", "")
    if sid:
        svc.delete(sid)
    for f in session.get("files", []):
        path = f.get("file_path", "")
        if path and os.path.exists(path):
            os.remove(path)


def _uuid() -> str:
    import uuid

    return str(uuid.uuid4())
