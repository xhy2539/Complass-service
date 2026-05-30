"""任务上传文件持久化工具。"""

from pathlib import Path

from app.core.complass_service_settings import get_complass_service_settings


def get_task_upload_root() -> Path:
    """返回任务上传文件根目录，并确保目录存在。"""
    root = Path(get_complass_service_settings().task_upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_task_upload(task_id: str, role: str, file_name: str, content: bytes) -> str:
    """保存任务上传文件，返回可持久化的绝对路径。"""
    suffix = Path(file_name).suffix.lower()
    safe_role = "".join(ch for ch in role if ch.isalnum() or ch in ("-", "_"))
    path = get_task_upload_root() / f"{task_id}_{safe_role}{suffix}"
    path.write_bytes(content)
    return str(path)


def read_task_upload(file_path: str) -> bytes:
    """读取已持久化的任务上传文件。"""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"任务文件不存在: {file_path}")
    return path.read_bytes()
