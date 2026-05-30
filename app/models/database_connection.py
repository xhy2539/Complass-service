"""数据库连接和会话管理模块。"""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.core.complass_service_settings import get_complass_service_settings
from app.models.database import Base

settings = get_complass_service_settings()

# 创建数据库引擎
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # 连接前测试
    pool_size=10,
    max_overflow=20,
    echo=False,  # 调试时可改为 True
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """初始化数据库，创建所有表。"""
    Base.metadata.create_all(bind=engine)
    _ensure_schema_updates()


def _ensure_schema_updates() -> None:
    """补齐轻量字段迁移，避免已有开发库缺少新增列。"""
    _add_column_if_missing("risk_points", "replace_text", "TEXT")
    _add_column_if_missing("review_tasks", "rule_version_id", "VARCHAR(36)")
    _add_column_if_missing("review_tasks", "file_path", "VARCHAR(500)")
    _add_column_if_missing("review_tasks", "rules_snapshot_json", "JSON")
    _add_column_if_missing(
        "review_tasks", "contract_type", "VARCHAR(50) NOT NULL DEFAULT '通用'"
    )
    _add_column_if_missing("review_tasks", "sanitization_mapping_json", "JSON")
    _add_column_if_missing(
        "review_tasks",
        "sanitization_status",
        "VARCHAR(20) NOT NULL DEFAULT 'not_required'",
    )
    _add_column_if_missing("review_tasks", "sanitization_error", "TEXT")
    _add_column_if_missing("risk_points", "rule_code", "VARCHAR(50)")
    _add_column_if_missing("risk_points", "rule_snapshot_json", "JSON")
    _add_column_if_missing("comparison_tasks", "rule_version_id", "VARCHAR(36)")
    _add_column_if_missing("comparison_tasks", "old_file_path", "VARCHAR(500)")
    _add_column_if_missing("comparison_tasks", "new_file_path", "VARCHAR(500)")
    _add_column_if_missing("comparison_tasks", "rules_snapshot_json", "JSON")
    _add_column_if_missing(
        "comparison_tasks", "contract_type", "VARCHAR(50) NOT NULL DEFAULT '通用'"
    )
    _add_column_if_missing("comparison_tasks", "old_sanitization_mapping_json", "JSON")
    _add_column_if_missing("comparison_tasks", "new_sanitization_mapping_json", "JSON")
    _add_column_if_missing(
        "comparison_tasks",
        "sanitization_status",
        "VARCHAR(20) NOT NULL DEFAULT 'not_required'",
    )
    _add_column_if_missing("comparison_tasks", "sanitization_error", "TEXT")
    _add_column_if_missing("comparison_risk_points", "rule_code", "VARCHAR(50)")
    _add_column_if_missing("comparison_risk_points", "rule_snapshot_json", "JSON")
    _add_column_if_missing("users", "phone", "VARCHAR(20) NOT NULL DEFAULT ''")
    _add_column_if_missing("users", "token_quota", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing("users", "token_used", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing("review_tasks", "token_cost", "INTEGER")
    _add_column_if_missing("comparison_tasks", "token_cost", "INTEGER")
    _add_column_if_missing("review_tasks", "use_coze", "BOOLEAN NOT NULL DEFAULT TRUE")
    _add_column_if_missing(
        "comparison_tasks", "enhance", "BOOLEAN NOT NULL DEFAULT TRUE"
    )


def _add_column_if_missing(table_name: str, column_name: str, ddl: str) -> None:
    """在开发库缺列时补齐字段。"""
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name not in columns:
        with engine.begin() as connection:
            connection.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")
            )


def get_db() -> Generator[Session, None, None]:
    """获取数据库会话的依赖项。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """上下文管理器方式的数据库会话。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
