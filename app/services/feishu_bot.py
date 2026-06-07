"""飞书机器人服务模块。"""

import asyncio
import json
import logging
import secrets
import uuid
from datetime import datetime

import httpx
from fastapi import Request
from fastapi import Response

from app.core.complass_service_settings import get_complass_service_settings
from app.core.security import decrypt_feishu_data
from app.core.security import hash_password
from app.models.database import ComparisonTask
from app.models.database import ReviewTask
from app.models.database import TaskStatus
from app.models.database import User
from app.models.database_connection import get_db_session
from app.services.redis_service import RedisSessionStatus
from app.services.redis_service import get_redis_service
from app.services.task_file_storage import save_task_upload
from app.services.task_service import download_file_from_feishu

logger = logging.getLogger(__name__)

# 聚合窗口时间（秒）
_pending_aggregation_window_seconds = 10

_card_send_lock_seconds = 5


def _acquire_choice_card_lock(redis, open_id: str) -> bool:
    try:
        key = f"feishu:open_id:{open_id}:card_send_lock"
        return (
            redis._client.set(key, "1", nx=True, ex=_card_send_lock_seconds) is not None
        )
    except Exception:
        return True


def _build_choice_actions(session_id: str, file_count: int) -> list[dict]:
    actions: list[dict] = [
        {
            "tag": "button",
            "text": {"content": "🔍 合同审查", "tag": "plain_text"},
            "type": "primary",
            "value": {"session_id": session_id, "op": "review"},
            "style": {"height": "40px", "width": "140px"},
        }
    ]
    if file_count >= 2:
        actions.append(
            {
                "tag": "button",
                "text": {"content": "🔄 版本比对", "tag": "plain_text"},
                "type": "default",
                "value": {"session_id": session_id, "op": "comparison"},
                "style": {"height": "40px", "width": "140px"},
            }
        )
    return actions


def _get_comparison_diff_count(task: ComparisonTask | None) -> int:
    if not task:
        return 0
    details = (
        task.diff_details_json if isinstance(task.diff_details_json, list) else None
    )
    if details is not None:
        return len(details)
    diff_stats = task.diff_stats if isinstance(task.diff_stats, dict) else None
    if diff_stats:
        subtotal = 0
        has_parts = False
        for k in ("added", "deleted", "modified"):
            if k in diff_stats:
                has_parts = True
            try:
                subtotal += int(diff_stats.get(k) or 0)
            except (TypeError, ValueError):
                pass
        if has_parts and subtotal > 0:
            return subtotal
        try:
            total = int(diff_stats.get("total") or 0)
            if total > 0:
                return total
        except (TypeError, ValueError):
            pass
    return task.total_risks or 0


def _wait_for_comparison_task(
    task_id: str, timeout_seconds: int = 40
) -> ComparisonTask | None:
    deadline = datetime.now().timestamp() + timeout_seconds
    while datetime.now().timestamp() < deadline:
        db_session = get_db_session()
        try:
            task = (
                db_session.query(ComparisonTask)
                .filter(ComparisonTask.id == task_id)
                .first()
            )
            if task and task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
                return task
        finally:
            db_session.close()
        import time

        time.sleep(1)
    db_session = get_db_session()
    try:
        return (
            db_session.query(ComparisonTask)
            .filter(ComparisonTask.id == task_id)
            .first()
        )
    finally:
        db_session.close()


def _uuid() -> str:
    """生成唯一ID。"""
    return str(uuid.uuid4())


def decrypt_data(encrypt_str: str) -> dict:
    """解密飞书回调数据。"""
    settings = get_complass_service_settings()
    encrypt_key = settings.feishu_encrypt_key

    if not encrypt_key:
        raise Exception("缺少 FEISHU_ENCRYPT_KEY，无法解密飞书回调")

    return decrypt_feishu_data(encrypt_str, encrypt_key)


def _extract_file_info_list(message: dict) -> list:
    """从消息中提取文件信息列表。"""
    file_info_list = []
    message_id = message.get("message_id") or message.get("messageId")

    if message.get("message_type") == "file":
        file_key = message.get("file_key") or message.get("fileKey")
        file_name = message.get("file_name") or message.get("fileName")
        if not file_key and message.get("content"):
            try:
                content = json.loads(message["content"])
                if isinstance(content, dict):
                    file_key = content.get("file_key") or content.get("fileKey")
                    file_name = (
                        file_name
                        or content.get("file_name")
                        or content.get("fileName")
                        or content.get("name")
                    )
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        if file_key:
            file_info_list.append(
                {
                    "file_key": file_key,
                    "file_name": file_name,
                    "message_id": message_id,
                }
            )

    elif message.get("message_type") == "text":
        pass

    elif message.get("content"):
        try:
            content = json.loads(message["content"])
            if isinstance(content, dict):
                if content.get("files"):
                    for f in content["files"]:
                        file_key = f.get("file_key") or f.get("fileKey")
                        if not file_key:
                            continue
                        file_info_list.append(
                            {
                                "file_key": file_key,
                                "file_name": f.get("file_name")
                                or f.get("fileName")
                                or f.get("name"),
                                "message_id": message_id,
                            }
                        )
                else:
                    file_key = content.get("file_key") or content.get("fileKey")
                    if file_key:
                        file_info_list.append(
                            {
                                "file_key": file_key,
                                "file_name": content.get("file_name")
                                or content.get("fileName")
                                or content.get("name"),
                                "message_id": message_id,
                            }
                        )
        except (json.JSONDecodeError, ValueError):
            pass

    return file_info_list


def _get_frontend_base_url() -> str:
    settings = get_complass_service_settings()
    url = (
        getattr(settings, "frontend_base_url", "")
        or getattr(settings, "frontend_url", "")
        or ""
    ).strip()
    return url.rstrip("/")


def _get_or_create_feishu_user_id(open_id: str) -> str:
    deterministic_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"feishu:{open_id}")
    user_id = str(deterministic_uuid)

    db = get_db_session()
    try:
        user = db.query(User).filter(User.feishu_open_id == open_id).first()
        if user:
            return user.id

        user = db.query(User).filter(User.id == user_id).first()
        if user:
            if not user.feishu_open_id:
                user.feishu_open_id = open_id
                db.commit()
            return user_id

        email = f"{user_id}@feishu.local"
        existing_email = db.query(User).filter(User.email == email).first()
        if existing_email:
            return existing_email.id

        password = secrets.token_urlsafe(24)
        user = User(
            id=user_id,
            email=email,
            phone="",
            nickname=f"feishu_{open_id[-6:]}" if open_id else "feishu_user",
            hashed_password=hash_password(password),
            is_active=True,
            is_verified=True,
            token_quota=0,
            token_used=0,
            feishu_open_id=open_id,
        )
        db.add(user)
        db.commit()
        return user_id
    finally:
        db.close()


def _parse_card_action_payload(data: dict) -> tuple:
    """解析卡片动作载荷。"""
    action = data.get("action") or data.get("event", {}).get("action")
    if not action:
        return None, None, None

    value = action.get("value")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = {}

    pending_id = value.get("pending_id") or value.get("session_id") or ""
    op = value.get("op") or ""

    payload = action.get("payload") or {}
    operator_id = (
        payload.get("open_id")
        or payload.get("openId")
        or (payload.get("operator") or {}).get("open_id")
        or ""
    )

    if pending_id and op:
        return pending_id, op, operator_id
    return None, None, None


async def handle_feishu_callback(request: Request) -> Response:
    """处理飞书机器人回调请求。"""
    try:
        data = await request.json()
        try:
            if isinstance(data, dict) and "encrypt" in data:
                print(
                    f"[feishu] callback received: encrypted len={len(data.get('encrypt', ''))}"
                )
            else:
                print(
                    f"[feishu] callback received: keys={list(data.keys()) if isinstance(data, dict) else type(data)}"
                )
        except Exception:
            pass
        # 如果是加密数据，显示加密数据长度而不是内容
        if "encrypt" in data:
            encrypt_len = len(data.get("encrypt", ""))
            logger.info(f"[飞书机器人] 收到飞书加密请求，加密数据长度: {encrypt_len}")
        else:
            logger.info(
                f"[飞书机器人] 收到飞书请求: {json.dumps(data, ensure_ascii=False)[:500]}"
            )
        logger.debug(
            f"[飞书机器人] 请求完整数据: {json.dumps(data, ensure_ascii=False)}"
        )

        if data.get("type") == "url_verification":
            logger.info("[飞书机器人] 处理URL验证请求")
            return Response(
                content=json.dumps({"challenge": data["challenge"]}),
                media_type="application/json",
            )

        event_type = None
        if "encrypt" in data:
            logger.info("[飞书机器人] 数据已加密，开始解密")
            decrypted_data = decrypt_data(data["encrypt"])
            header = (
                decrypted_data.get("header") if isinstance(decrypted_data, dict) else {}
            )
            event_type = header.get("event_type") if isinstance(header, dict) else None
            logger.info(
                f"[飞书机器人] 解密后事件类型: {event_type or decrypted_data.get('type')}"
            )

            if isinstance(header, dict):
                event_id = header.get("event_id") or header.get("eventId") or ""
                if event_id:
                    redis = get_redis_service()
                    if not redis.mark_message(f"event:{event_id}"):
                        logger.info(f"[飞书机器人] 事件 {event_id} 已处理过，跳过")
                        return Response(
                            content=json.dumps({"code": 0, "msg": "ok"}),
                            media_type="application/json",
                        )

            data = decrypted_data

            if data.get("type") == "url_verification":
                return Response(
                    content=json.dumps({"challenge": data["challenge"]}),
                    media_type="application/json",
                )

        card_action = None
        if isinstance(data, dict) and (
            event_type or data.get("action") or data.get("event")
        ):
            if (
                event_type
                and isinstance(event_type, str)
                and event_type.startswith("card.action.trigger")
            ):
                card_action = _parse_card_action_payload(data)
            elif data.get("action") and not event_type:
                card_action = _parse_card_action_payload(data)

        async def _process_card_action(session_id: str, op: str) -> None:
            redis = get_redis_service()

            session = redis.get_session(session_id)
            if not session:
                return

            open_id = session.get("feishu_open_id")

            try:
                access_token = get_tenant_access_token()
                files = redis.get_session_files(session_id)

                if op == "comparison" and len(files) < 2:
                    await asyncio.sleep(_pending_aggregation_window_seconds)
                    files = redis.get_session_files(session_id)

                if op == "review":
                    results = []
                    for f in files:
                        file_content, name, content_type = await asyncio.to_thread(
                            download_file_from_feishu,
                            f.get("source_file_key") or "",
                            access_token,
                            f.get("file_name") or "unknown.docx",
                            f.get("message_id"),
                        )
                        task_id = await create_review_task_from_feishu(
                            file_content, name, content_type, open_id
                        )
                        results.append({"task_id": task_id, "file_name": name})

                    if len(results) == 1:
                        await asyncio.to_thread(
                            send_result_card,
                            open_id,
                            results[0]["task_id"],
                            results[0]["file_name"],
                        )
                    else:
                        await asyncio.to_thread(
                            send_review_batch_card, open_id, results
                        )

                elif op == "comparison":
                    if len(files) != 2:
                        await asyncio.to_thread(
                            send_error_card,
                            open_id,
                            "，".join((f.get("file_name") or "unknown") for f in files),
                            "对比需要 2 份文件，请重新发送 2 份文件后再选择对比",
                        )
                    else:
                        old_f, new_f = files[0], files[1]
                        old_content, old_name, _ = await asyncio.to_thread(
                            download_file_from_feishu,
                            old_f.get("source_file_key") or "",
                            access_token,
                            old_f.get("file_name") or "old.docx",
                            old_f.get("message_id"),
                        )
                        new_content, new_name, _ = await asyncio.to_thread(
                            download_file_from_feishu,
                            new_f.get("source_file_key") or "",
                            access_token,
                            new_f.get("file_name") or "new.docx",
                            new_f.get("message_id"),
                        )
                        task_id = await create_comparison_task_from_feishu(
                            old_content, old_name, new_content, new_name, open_id
                        )
                        await asyncio.to_thread(
                            send_comparison_card,
                            open_id,
                            task_id,
                            old_name,
                            new_name,
                        )

                redis.update_session_status(session_id, RedisSessionStatus.COMPLETED)

            except Exception as e:
                logger.error(f"[飞书机器人] 处理卡片按钮失败: {e}", exc_info=True)
                redis.update_session_status(session_id, RedisSessionStatus.FAILED)
                try:
                    await asyncio.to_thread(send_error_card, open_id, "unknown", str(e))
                except Exception:
                    pass

        async def _maybe_update_pending_choice_card(session_id: str) -> None:
            redis = get_redis_service()

            for _ in range(3):
                await asyncio.sleep(0.25)

                session = redis.get_session(session_id)
                if not session:
                    return

                status = session.get("status")
                if status != RedisSessionStatus.WAITING_FOR_ACTION:
                    return

                card_message_id = session.get("card_message_id")
                files = redis.get_session_files(session_id)

                if not card_message_id:
                    continue

                file_names = [
                    (f.get("file_name") or "unknown")
                    for f in files
                    if isinstance(f, dict)
                ]
                if not file_names:
                    return
                try:
                    await asyncio.to_thread(
                        update_operation_choice_card,
                        card_message_id,
                        session_id,
                        file_names,
                    )
                except Exception as e:
                    logger.error(f"[飞书机器人] 更新选择卡片失败: {e}", exc_info=True)
                return

        if card_action:
            session_id, op, operator_id = card_action

            if not session_id or not op:
                return Response(
                    content=json.dumps({"code": 0, "msg": "ok"}),
                    media_type="application/json",
                )

            redis = get_redis_service()
            session = redis.get_session(session_id)

            if not session:
                return Response(
                    content=json.dumps({"code": 0, "msg": "ok"}),
                    media_type="application/json",
                )

            open_id = session.get("feishu_open_id")
            if operator_id and open_id != operator_id:
                return Response(
                    content=json.dumps({"code": 0, "msg": "ok"}),
                    media_type="application/json",
                )

            status = session.get("status")
            if status == RedisSessionStatus.PROCESSING:
                return Response(
                    content=json.dumps({"code": 0, "msg": "ok"}),
                    media_type="application/json",
                )

            redis.update_session_status(session_id, RedisSessionStatus.PROCESSING)
            asyncio.create_task(_process_card_action(session_id, op))

            return Response(
                content=json.dumps({"code": 0, "msg": "ok"}),
                media_type="application/json",
            )

        if data.get("event") and data["event"].get("message"):
            logger.info("[飞书机器人] 检测到消息事件")
            event = data["event"]
            message = event["message"]
            sender_info = event.get("sender", {})
            sender_id = sender_info.get("sender_id", {})
            open_id = sender_id.get("open_id")

            msg_type = message.get("message_type")
            msg_id = message.get("message_id") or message.get("messageId") or ""

            logger.info(
                f"[飞书机器人] 消息类型: {msg_type}, open_id: {open_id}, msg_id: {msg_id}"
            )

            if msg_id:
                redis = get_redis_service()
                if not redis.mark_message(f"message:{msg_id}"):
                    logger.info(f"[飞书机器人] 消息 {msg_id} 已处理过，跳过")
                    return Response(
                        content=json.dumps({"code": 0, "msg": "ok"}),
                        media_type="application/json",
                    )

            file_info_list = _extract_file_info_list(message)
            logger.info(f"[飞书机器人] 提取到文件数量: {len(file_info_list)}")

            if file_info_list and open_id:
                logger.info(f"[飞书机器人] 开始处理文件，open_id: {open_id}")
                redis = get_redis_service()
                chat_id = message.get("chat_id") or message.get("chatId")

                existing_session = redis.get_session_by_open_id(open_id)
                logger.info(
                    f"[飞书机器人] 查找现有会话: {existing_session is not None}"
                )

                session_id = None
                status = None

                if existing_session:
                    session_id = existing_session.get("session_id")
                    status = existing_session.get("status")
                    logger.info(
                        f"[飞书机器人] 找到现有会话: {session_id}, 状态: {status}"
                    )

                if (not session_id) or (
                    status
                    in {
                        RedisSessionStatus.PROCESSING,
                        RedisSessionStatus.COMPLETED,
                        RedisSessionStatus.FAILED,
                    }
                ):
                    if status in {
                        RedisSessionStatus.PROCESSING,
                        RedisSessionStatus.COMPLETED,
                        RedisSessionStatus.FAILED,
                    }:
                        logger.info(f"[飞书机器人] 会话状态为 {status}，创建新会话")
                    else:
                        logger.info("[飞书机器人] 创建新会话")
                    session_id = redis.create_session(
                        feishu_open_id=open_id,
                        chat_id=chat_id or "",
                        message_id=msg_id,
                    )
                    for f in file_info_list:
                        if isinstance(f, dict):
                            redis.add_file_to_session(session_id, f, role="first")
                    logger.info(f"[飞书机器人] 新会话创建成功: {session_id}")
                else:
                    role = (
                        "second"
                        if status == RedisSessionStatus.WAITING_FOR_SECOND_FILE
                        else "first"
                    )
                    for f in file_info_list:
                        if isinstance(f, dict):
                            redis.add_file_to_session(session_id, f, role=role)
                    redis.extend_session_expire(session_id)
                    logger.info("[飞书机器人] 文件已添加到现有会话")

                if not session_id:
                    logger.warning("[飞书机器人] 无法创建或获取会话")
                    return Response(
                        content=json.dumps({"code": 0, "msg": "ok"}),
                        media_type="application/json",
                    )

                try:
                    session = redis.get_session(session_id)
                    status = session.get("status")
                    files = redis.get_session_files(session_id)
                    file_names = [f.get("file_name") or "unknown" for f in files]
                    logger.info(f"[飞书机器人] 会话文件列表: {file_names}")

                    if not _acquire_choice_card_lock(redis, open_id):
                        logger.info(
                            "[飞书机器人] 操作选择卡片发送锁已被占用，跳过本次发送，等待后续更新"
                        )
                        asyncio.create_task(
                            _maybe_update_pending_choice_card(session_id)
                        )
                        return Response(
                            content=json.dumps({"code": 0, "msg": "ok"}),
                            media_type="application/json",
                        )

                    card_message_id = (session.get("card_message_id") or "").strip()
                    if card_message_id:
                        logger.info("[飞书机器人] 检测到已有操作选择卡片，更新卡片内容")
                        await asyncio.to_thread(
                            update_operation_choice_card,
                            card_message_id,
                            session_id,
                            file_names,
                        )
                    else:
                        logger.info("[飞书机器人] 准备发送操作选择卡片")
                        card_message_id = await asyncio.to_thread(
                            send_operation_choice_card,
                            open_id,
                            session_id,
                            file_names,
                        )
                        logger.info(
                            f"[飞书机器人] 卡片发送结果: card_message_id={card_message_id}"
                        )
                        if card_message_id:
                            redis._client.hset(
                                redis._get_session_key(session_id),
                                "card_message_id",
                                card_message_id,
                            )

                    asyncio.create_task(_maybe_update_pending_choice_card(session_id))

                except Exception as e:
                    logger.error(f"[飞书机器人] 处理文件消息失败: {e}", exc_info=True)
                    try:
                        await asyncio.to_thread(
                            send_error_card, open_id, "unknown", str(e)
                        )
                    except Exception:
                        pass

        return Response(
            content=json.dumps({"code": 0, "msg": "ok"}), media_type="application/json"
        )

    except Exception as e:
        logger.error(f"[飞书机器人] 处理回调失败: {e}", exc_info=True)
        return Response(
            content=json.dumps({"code": 0, "msg": "ok"}), media_type="application/json"
        )


# ----------------------
# 发送操作选择卡片
# ----------------------
def send_operation_choice_card(open_id: str, session_id: str, file_names: list) -> str:
    """向用户发送操作选择卡片。"""
    access_token = get_tenant_access_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"

    title = f"收到 {len(file_names)} 份文件"
    if len(file_names) == 1:
        title = f"收到文件：{file_names[0]}"

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "📄 合同处理", "tag": "plain_text"},
            "template": "#1890ff",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"content": title, "tag": "lark_md"},
                "style": {"margin_bottom": 16},
            },
            {
                "tag": "div",
                "text": {"content": "请选择要执行的操作：", "tag": "lark_md"},
                "style": {"margin_bottom": 16},
            },
            {
                "tag": "action",
                "actions": _build_choice_actions(session_id, len(file_names)),
            },
        ],
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card),
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
        logger.info(f"[飞书机器人] 操作选择卡片发送成功: {result}")
        return result.get("data", {}).get("message_id")
    except Exception as e:
        logger.error(f"[飞书机器人] 发送操作选择卡片失败: {e}")
        return ""


def update_operation_choice_card(
    message_id: str, session_id: str, file_names: list
) -> None:
    """更新操作选择卡片的文件列表。"""
    access_token = get_tenant_access_token()
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}?receive_id_type=open_id"

    title = f"收到 {len(file_names)} 份文件"
    if len(file_names) == 1:
        title = f"收到文件：{file_names[0]}"

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "📄 合同处理", "tag": "plain_text"},
            "template": "#1890ff",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"content": title, "tag": "lark_md"},
                "style": {"margin_bottom": 16},
            },
            {
                "tag": "div",
                "text": {"content": "请选择要执行的操作：", "tag": "lark_md"},
                "style": {"margin_bottom": 16},
            },
            {
                "tag": "action",
                "actions": _build_choice_actions(session_id, len(file_names)),
            },
        ],
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {"content": json.dumps(card)}

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.patch(url, headers=headers, json=payload)
            response.raise_for_status()
        logger.info("[飞书机器人] 更新操作选择卡片成功")
    except Exception as e:
        logger.error(f"[飞书机器人] 更新操作选择卡片失败: {e}")


# ----------------------
# 发送错误提示卡片
# ----------------------
def send_error_card(open_id: str, file_name: str, error_msg: str):
    """向用户发送错误提示卡片。"""
    access_token = get_tenant_access_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "❌ 处理失败", "tag": "plain_text"},
            "template": "#FF4D4F",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"content": f"📄 **文件**：{file_name}", "tag": "lark_md"},
                "style": {"margin_bottom": 8},
            },
            {
                "tag": "div",
                "text": {
                    "content": f"⚠️ **错误信息**：{error_msg[:100]}",
                    "tag": "lark_md",
                },
                "style": {"margin_bottom": 16},
            },
            {
                "tag": "div",
                "text": {
                    "content": "请检查文件格式后重新发送，支持 docx、pdf、txt 格式",
                    "tag": "lark_md",
                },
            },
        ],
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card),
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        logger.info("[飞书机器人] 错误提示卡片发送成功")
    except Exception as e:
        logger.error(f"[飞书机器人] 发送错误卡片失败: {e}")


# ----------------------
# 发送审查结果卡片
# ----------------------
def send_result_card(
    open_id: str, task_id: str, file_name: str, risk_summary: str = None
):
    """向用户发送审查结果卡片。"""
    access_token = get_tenant_access_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"

    frontend_url = _get_frontend_base_url()
    review_url = f"{frontend_url}/reviews/{task_id}"

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "⏳ 审查处理中", "tag": "plain_text"},
            "template": "#1890ff",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"content": f"📄 **文件**：{file_name}", "tag": "lark_md"},
                "style": {"margin_bottom": 16},
            },
            {
                "tag": "div",
                "text": {"content": f"🆔 **任务ID**：{task_id}", "tag": "lark_md"},
                "style": {"margin_bottom": 16},
            },
            {
                "tag": "div",
                "text": {
                    "content": "任务已提交，稍后可查看审查结果",
                    "tag": "lark_md",
                },
                "style": {"margin_bottom": 16},
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"content": "🔗 查看详情", "tag": "plain_text"},
                        "type": "primary",
                        "url": review_url,
                        "style": {"height": "40px", "width": "140px"},
                    }
                ],
            },
        ],
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card),
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        logger.info("[飞书机器人] 审查结果卡片发送成功")
    except Exception as e:
        logger.error(f"[飞书机器人] 发送审查结果卡片失败: {e}")


def send_review_completed_card(open_id: str, task_id: str, file_name: str) -> None:
    access_token = get_tenant_access_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"

    frontend_url = _get_frontend_base_url()
    review_url = f"{frontend_url}/reviews/{task_id}"

    redis = get_redis_service()
    try:
        notify_key = f"feishu:notify:review:{task_id}:completed"
        if redis._client.set(notify_key, "1", nx=True, ex=24 * 3600) is None:
            return
    except Exception:
        pass

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "✅ 审查完成", "tag": "plain_text"},
            "template": "#52c41a",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"content": f"📄 **文件**：{file_name}", "tag": "lark_md"},
                "style": {"margin_bottom": 16},
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"content": "🔗 查看详情", "tag": "plain_text"},
                        "type": "primary",
                        "url": review_url,
                        "style": {"height": "40px", "width": "140px"},
                    }
                ],
            },
        ],
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card),
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        logger.info("[飞书机器人] 审查完成卡片发送成功")
    except Exception as e:
        logger.error(f"[飞书机器人] 发送审查完成卡片失败: {e}")


def send_review_batch_card(open_id: str, results: list):
    """向用户发送批量审查结果卡片。"""
    access_token = get_tenant_access_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"

    frontend_url = _get_frontend_base_url()

    elements = []
    for result in results:
        task_id = result["task_id"]
        file_name = result["file_name"]
        review_url = f"{frontend_url}/reviews/{task_id}"

        elements.append(
            {
                "tag": "div",
                "text": {"content": f"📄 **{file_name}**", "tag": "lark_md"},
                "style": {"margin_bottom": 8},
            }
        )
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"content": "查看详情", "tag": "plain_text"},
                        "type": "default",
                        "url": review_url,
                        "style": {"height": "32px", "width": "120px"},
                    }
                ],
            }
        )
        elements.append(
            {
                "tag": "div",
                "text": {"content": "", "tag": "plain_text"},
                "style": {"margin_bottom": 16},
            }
        )

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "content": f"⏳ 已提交 {len(results)} 份文件审查",
                "tag": "plain_text",
            },
            "template": "#1890ff",
        },
        "elements": elements,
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card),
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        logger.info("[飞书机器人] 批量审查结果卡片发送成功")
    except Exception as e:
        logger.error(f"[飞书机器人] 发送批量审查结果卡片失败: {e}")


# ----------------------
# 发送比对结果卡片
# ----------------------
def send_comparison_card(
    open_id: str, task_id: str, old_name: str, new_name: str, total_risks: int = 0
):
    """向用户发送比对结果卡片。"""
    access_token = get_tenant_access_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"

    frontend_url = _get_frontend_base_url()
    comparison_url = f"{frontend_url}/comparisons/{task_id}"

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "⏳ 比对处理中", "tag": "plain_text"},
            "template": "#1890ff",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"content": f"📄 **原始文件**：{old_name}", "tag": "lark_md"},
                "style": {"margin_bottom": 8},
            },
            {
                "tag": "div",
                "text": {"content": f"📄 **新版本**：{new_name}", "tag": "lark_md"},
                "style": {"margin_bottom": 16},
            },
            {
                "tag": "div",
                "text": {
                    "content": "任务已提交，稍后可查看比对结果",
                    "tag": "lark_md",
                },
                "style": {"margin_bottom": 16},
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"content": "🔗 查看详情", "tag": "plain_text"},
                        "type": "primary",
                        "url": comparison_url,
                        "style": {"height": "40px", "width": "140px"},
                    }
                ],
            },
        ],
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card),
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        logger.info("[飞书机器人] 比对结果卡片发送成功")
    except Exception as e:
        logger.error(f"[飞书机器人] 发送比对结果卡片失败: {e}")


def send_comparison_completed_card(
    open_id: str, task_id: str, old_name: str, new_name: str
) -> None:
    access_token = get_tenant_access_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"

    frontend_url = _get_frontend_base_url()
    comparison_url = f"{frontend_url}/comparisons/{task_id}"

    redis = get_redis_service()
    try:
        notify_key = f"feishu:notify:comparison:{task_id}:completed"
        if redis._client.set(notify_key, "1", nx=True, ex=24 * 3600) is None:
            return
    except Exception:
        pass

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "✅ 比对完成", "tag": "plain_text"},
            "template": "#52c41a",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"content": f"📄 **原始文件**：{old_name}", "tag": "lark_md"},
                "style": {"margin_bottom": 8},
            },
            {
                "tag": "div",
                "text": {"content": f"📄 **新版本**：{new_name}", "tag": "lark_md"},
                "style": {"margin_bottom": 16},
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"content": "🔗 查看详情", "tag": "plain_text"},
                        "type": "primary",
                        "url": comparison_url,
                        "style": {"height": "40px", "width": "140px"},
                    }
                ],
            },
        ],
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card),
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        logger.info("[飞书机器人] 比对完成卡片发送成功")
    except Exception as e:
        logger.error(f"[飞书机器人] 发送比对完成卡片失败: {e}")


# ----------------------
# 获取飞书 Tenant Access Token
# ----------------------
_tenant_access_token = None
_token_expire_time = 0


def get_tenant_access_token() -> str:
    """获取飞书 Tenant Access Token。"""
    global _tenant_access_token, _token_expire_time

    now = datetime.now().timestamp()
    if _tenant_access_token and now < _token_expire_time:
        return _tenant_access_token

    settings = get_complass_service_settings()
    app_id = settings.feishu_app_id
    app_secret = settings.feishu_app_secret

    if not app_id or not app_secret:
        raise Exception("缺少飞书 App ID 或 App Secret")

    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json"}
    payload = {"app_id": app_id, "app_secret": app_secret}

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()

        if result.get("code") == 0:
            _tenant_access_token = result.get("tenant_access_token")
            _token_expire_time = now + (result.get("expire", 7200) - 100)
            logger.info("[飞书机器人] 获取 Tenant Access Token 成功")
            return _tenant_access_token
        else:
            raise Exception(f"获取 Token 失败: {result.get('msg')}")
    except Exception as e:
        logger.error(f"[飞书机器人] 获取 Tenant Access Token 失败: {e}")
        raise


# ----------------------
# 创建任务辅助函数
# ----------------------
async def create_review_task_from_feishu(
    file_content: bytes, file_name: str, content_type: str, open_id: str
) -> str:
    """从飞书文件创建审查任务。"""
    from app.api.v1.contract_review_routes import _process_review_task_background

    user_id = _get_or_create_feishu_user_id(open_id)
    task_id = str(uuid.uuid4())
    file_path = save_task_upload(
        task_id, "review", file_name or "contract", file_content
    )

    db = get_db_session()
    try:
        file_type = (
            file_name.rsplit(".", 1)[-1].lower()
            if file_name and "." in file_name
            else "unknown"
        )
        task = ReviewTask(
            id=task_id,
            user_id=user_id,
            file_name=file_name or "unknown",
            file_type=file_type,
            file_path=file_path,
            file_size=len(file_content),
            sanitization_status="not_required",
            rule_version_id=None,
            rules_snapshot_json=[],
            contract_type="通用",
            use_coze=True,
            status=TaskStatus.PENDING,
        )
        db.add(task)
        db.commit()
    finally:
        db.close()

    asyncio.create_task(
        asyncio.to_thread(
            _process_review_task_background,
            task_id,
            user_id,
            file_name or "unknown",
            file_path,
            True,
        )
    )
    return task_id


async def create_comparison_task_from_feishu(
    old_content: bytes, old_name: str, new_content: bytes, new_name: str, open_id: str
) -> str:
    """从飞书文件创建比对任务。"""
    from app.api.v1.contract_comparison_routes import (
        _process_comparison_task_background,
    )

    user_id = _get_or_create_feishu_user_id(open_id)
    task_id = str(uuid.uuid4())
    old_file_path = save_task_upload(
        task_id, "old", old_name or "old_contract", old_content
    )
    new_file_path = save_task_upload(
        task_id, "new", new_name or "new_contract", new_content
    )

    db = get_db_session()
    try:
        old_file_type = (
            old_name.rsplit(".", 1)[-1].lower()
            if old_name and "." in old_name
            else "unknown"
        )
        new_file_type = (
            new_name.rsplit(".", 1)[-1].lower()
            if new_name and "." in new_name
            else "unknown"
        )
        task = ComparisonTask(
            id=task_id,
            user_id=user_id,
            old_file_name=old_name or "unknown",
            new_file_name=new_name or "unknown",
            old_file_type=old_file_type,
            new_file_type=new_file_type,
            old_file_size=len(old_content),
            new_file_size=len(new_content),
            old_file_path=old_file_path,
            new_file_path=new_file_path,
            sanitization_status="not_required",
            rules_snapshot_json=[],
            contract_type="通用",
            enhance=False,
            status=TaskStatus.PENDING,
        )
        db.add(task)
        db.commit()
    finally:
        db.close()

    asyncio.create_task(
        asyncio.to_thread(
            _process_comparison_task_background,
            task_id,
            user_id,
            old_name or "unknown",
            new_name or "unknown",
            old_file_path,
            new_file_path,
            False,
            "通用",
        )
    )
    return task_id
