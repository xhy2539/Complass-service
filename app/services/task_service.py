"""任务服务模块，提供任务创建和查询功能。"""

import logging
import uuid

import httpx

from app.models.database import ComparisonTask
from app.models.database import ReviewTask
from app.models.database import TaskStatus
from app.models.database_connection import get_db_session

logger = logging.getLogger(__name__)


def download_file_from_feishu(
    file_key: str, access_token: str, file_name: str, message_id: str
) -> tuple[bytes, str, str]:
    """从飞书下载文件。

    Args:
        file_key: 文件 key
        access_token: 飞书访问令牌
        file_name: 文件名
        message_id: 消息 ID

    Returns:
        (文件内容, 文件名, 内容类型)
    """
    im_resource_url = ""
    if message_id and file_key:
        im_resource_url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{file_key}?type=file"
    drive_url = f"https://open.feishu.cn/open-apis/drive/v1/files/{file_key}/download"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        if im_resource_url:
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.get(im_resource_url, headers=headers)
                    response.raise_for_status()
                    content = response.content
                    content_type = response.headers.get(
                        "Content-Type", "application/octet-stream"
                    )
                logger.info(
                    f"[飞书文件下载] 成功下载文件(消息资源): {file_name}, 大小: {len(content)} bytes"
                )
                return content, file_name, content_type
            except Exception:
                pass

        with httpx.Client(timeout=30.0) as client:
            response = client.get(drive_url, headers=headers)
            response.raise_for_status()
            content = response.content
            content_type = response.headers.get(
                "Content-Type", "application/octet-stream"
            )

        logger.info(
            f"[飞书文件下载] 成功下载文件(云盘): {file_name}, 大小: {len(content)} bytes"
        )
        return content, file_name, content_type

    except Exception as e:
        status_code = getattr(getattr(e, "response", None), "status_code", None)
        resp_text = getattr(getattr(e, "response", None), "text", "")
        resp_text = (resp_text or "")[:300]
        if status_code:
            logger.error(
                f"[飞书文件下载] 下载文件失败: {status_code} {e} resp={resp_text}"
            )
        else:
            logger.error(f"[飞书文件下载] 下载文件失败: {e}")
        raise


async def create_review_task(
    file_content: bytes, file_name: str, content_type: str
) -> ReviewTask:
    """创建审查任务。

    Args:
        file_content: 文件内容
        file_name: 文件名
        content_type: 内容类型

    Returns:
        创建的审查任务对象
    """
    db = get_db_session()
    try:
        task_id = str(uuid.uuid4())

        file_type = (
            file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "unknown"
        )

        task = ReviewTask(
            id=task_id,
            user_id="feishu_bot",
            file_name=file_name,
            file_type=file_type,
            file_size=len(file_content),
            status=TaskStatus.PENDING,
            sanitization_status="not_required",
            use_coze=True,
            contract_type="通用",
        )

        db.add(task)
        db.commit()
        db.refresh(task)

        logger.info(f"[任务服务] 创建审查任务成功: {task_id}, 文件: {file_name}")

        return task

    except Exception as e:
        db.rollback()
        logger.error(f"[任务服务] 创建审查任务失败: {e}")
        raise
    finally:
        db.close()


async def create_comparison_task(
    old_content: bytes, old_name: str, new_content: bytes, new_name: str
) -> ComparisonTask:
    """创建比对任务。

    Args:
        old_content: 旧版本文件内容
        old_name: 旧版本文件名
        new_content: 新版本文件内容
        new_name: 新版本文件名

    Returns:
        创建的比对任务对象
    """
    db = get_db_session()
    try:
        task_id = str(uuid.uuid4())

        old_file_type = (
            old_name.rsplit(".", 1)[-1].lower() if "." in old_name else "unknown"
        )
        new_file_type = (
            new_name.rsplit(".", 1)[-1].lower() if "." in new_name else "unknown"
        )

        task = ComparisonTask(
            id=task_id,
            user_id="feishu_bot",
            old_file_name=old_name,
            new_file_name=new_name,
            old_file_type=old_file_type,
            new_file_type=new_file_type,
            old_file_size=len(old_content),
            new_file_size=len(new_content),
            status=TaskStatus.PENDING,
            enhance=True,
            contract_type="通用",
        )

        db.add(task)
        db.commit()
        db.refresh(task)

        logger.info(
            f"[任务服务] 创建比对任务成功: {task_id}, 旧文件: {old_name}, 新文件: {new_name}"
        )

        return task

    except Exception as e:
        db.rollback()
        logger.error(f"[任务服务] 创建比对任务失败: {e}")
        raise
    finally:
        db.close()


def get_review_task_by_id(task_id: str) -> ReviewTask | None:
    """根据 ID 获取审查任务。

    Args:
        task_id: 任务 ID

    Returns:
        审查任务对象，如果不存在则返回 None
    """
    db = get_db_session()
    try:
        task = db.query(ReviewTask).filter(ReviewTask.id == task_id).first()
        return task
    except Exception as e:
        logger.error(f"[任务服务] 查询审查任务失败: {e}")
        return None
    finally:
        db.close()


def get_comparison_task_by_id(task_id: str) -> ComparisonTask | None:
    """根据 ID 获取比对任务。

    Args:
        task_id: 任务 ID

    Returns:
        比对任务对象，如果不存在则返回 None
    """
    db = get_db_session()
    try:
        task = db.query(ComparisonTask).filter(ComparisonTask.id == task_id).first()
        return task
    except Exception as e:
        logger.error(f"[任务服务] 查询比对任务失败: {e}")
        return None
    finally:
        db.close()
