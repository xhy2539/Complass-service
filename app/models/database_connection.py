"""数据库连接和会话管理模块。"""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.complass_service_settings import get_complass_service_settings
from app.models.database import Base

settings = get_complass_service_settings()

# 创建数据库引擎
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # 连接前测试
    pool_size=10,
    max_overflow=20,
    echo=False  # 调试时可改为 True
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """初始化数据库，创建所有表。"""
    Base.metadata.create_all(bind=engine)


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