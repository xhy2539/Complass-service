"""数据库模型定义，包含审查任务、风险点、比任务等数据模型。"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey,
    Index, Integer, JSON, String, Text
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类。"""
    pass


class User(Base):
    """用户表。"""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)  # UUID
    email = Column(String(255), unique=True, nullable=False, index=True)
    nickname = Column(String(100), nullable=False)
    hashed_password = Column(String(255), nullable=False)

    # 用户状态
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)  # 邮箱是否验证

    # 审计字段
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        """转换为字典格式（不包含密码）。"""
        return {
            "id": self.id,
            "email": self.email,
            "nickname": self.nickname,
            "is_active": self.is_active,
            "is_verified": self.is_verified,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }


class TaskStatus(str, Enum):
    """任务状态枚举。"""
    PENDING = "pending"       # 待处理
    PROCESSING = "processing"  # 处理中
    COMPLETED = "completed"    # 已完成
    FAILED = "failed"         # 失败


class RiskLevel(str, Enum):
    """风险等级枚举。"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RiskStatus(str, Enum):
    """风险点状态枚举。"""
    PENDING = "pending"      # 待处理
    CONFIRMED = "confirmed"  # 已确认
    IGNORED = "ignored"      # 已忽略


class ReviewType(str, Enum):
    """审查类型枚举。"""
    SINGLE = "single"       # 单合同审查
    COMPARISON = "comparison"  # 版本比对


class ReviewTask(Base):
    """单合同审查任务表。"""
    __tablename__ = "review_tasks"

    id = Column(String(36), primary_key=True)  # UUID
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)  # 用户 ID
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(10), nullable=False)
    file_path = Column(String(500), nullable=True)  # 文件存储路径
    file_size = Column(Integer, nullable=True)

    # 文件解析结果
    text = Column(Text, nullable=True)           # 合同纯文本
    char_count = Column(Integer, nullable=True)
    page_count = Column(Integer, nullable=True)
    paragraph_count = Column(Integer, nullable=True)
    sentence_count = Column(Integer, nullable=True)
    sanitized_text = Column(Text, nullable=True)  # 脱敏后文本

    # 段落结构 JSON
    paragraphs_json = Column(JSON, nullable=True)
    sentences_json = Column(JSON, nullable=True)
    position_info_json = Column(JSON, nullable=True)
    comparison_data_json = Column(JSON, nullable=True)

    # AI 分析结果（来自 Coze）
    overall_conclusion = Column(Text, nullable=True)
    risk_summary = Column(JSON, nullable=True)  # {"high": 0, "medium": 0, "low": 0}
    suggest_deep_review = Column(Boolean, default=False)
    coze_message = Column(Text, nullable=True)

    # 任务状态
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    # 关联
    user = relationship("User")
    risk_points = relationship("RiskPoint", back_populates="review_task", cascade="all, delete-orphan")
    paragraphs = relationship("Paragraph", back_populates="review_task", cascade="all, delete-orphan")
    sentences = relationship("Sentence", back_populates="review_task", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "char_count": self.char_count,
            "page_count": self.page_count,
            "paragraph_count": self.paragraph_count,
            "sentence_count": self.sentence_count,
            "overall_conclusion": self.overall_conclusion,
            "risk_summary": self.risk_summary,
            "suggest_deep_review": self.suggest_deep_review,
            "status": self.status.value if self.status else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "risk_count": len(self.risk_points),
            "risk_stats": self._get_risk_stats(),
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "sentences": [s.to_dict() for s in self.sentences],
            "paragraphs_json": self.paragraphs_json
        }

    def _get_risk_stats(self) -> dict:
        """获取风险点统计。"""
        total = len(self.risk_points)
        confirmed = sum(1 for rp in self.risk_points if rp.status == RiskStatus.CONFIRMED)
        ignored = sum(1 for rp in self.risk_points if rp.status == RiskStatus.IGNORED)
        pending = total - confirmed - ignored
        return {
            "total": total,
            "confirmed": confirmed,
            "ignored": ignored,
            "pending": pending
        }


class Paragraph(Base):
    """段落表，替代 paragraphs_json"""
    __tablename__ = "paragraphs"

    id = Column(String(36), primary_key=True)
    review_task_id = Column(String(36), ForeignKey("review_tasks.id"), nullable=False, index=True)

    index = Column(Integer, nullable=False)           # 段落索引
    text = Column(Text, nullable=True)               # 段落文本
    char_offset_start = Column(Integer, nullable=True)
    char_offset_end = Column(Integer, nullable=True)
    page_number = Column(Integer, nullable=True)
    is_key_clause = Column(Boolean, default=False)    # 是否关键条款
    paragraph_type = Column(String(20), default="body")  # heading1/heading2/heading3/body
    paragraph_level = Column(Integer, default=0)      # 0=正文, 1-3=标题层级

    created_at = Column(DateTime, default=datetime.utcnow)

    # 关联
    review_task = relationship("ReviewTask", back_populates="paragraphs")

    def to_dict(self) -> dict:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "review_task_id": self.review_task_id,
            "index": self.index,
            "text": self.text,
            "char_offset_start": self.char_offset_start,
            "char_offset_end": self.char_offset_end,
            "page_number": self.page_number,
            "is_key_clause": self.is_key_clause,
            "paragraph_type": self.paragraph_type,
            "paragraph_level": self.paragraph_level,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class Sentence(Base):
    """句子表，替代 sentences_json"""
    __tablename__ = "sentences"

    id = Column(String(36), primary_key=True)
    review_task_id = Column(String(36), ForeignKey("review_tasks.id"), nullable=False, index=True)

    index = Column(Integer, nullable=False)
    text = Column(Text, nullable=True)
    char_offset_start = Column(Integer, nullable=True)
    char_offset_end = Column(Integer, nullable=True)
    paragraph_index = Column(Integer, nullable=True)  # 所属段落索引

    created_at = Column(DateTime, default=datetime.utcnow)

    # 关联
    review_task = relationship("ReviewTask", back_populates="sentences")

    def to_dict(self) -> dict:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "review_task_id": self.review_task_id,
            "index": self.index,
            "text": self.text,
            "char_offset_start": self.char_offset_start,
            "char_offset_end": self.char_offset_end,
            "paragraph_index": self.paragraph_index,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class RiskPoint(Base):
    """风险点表。"""
    __tablename__ = "risk_points"

    id = Column(String(36), primary_key=True)  # UUID
    review_task_id = Column(String(36), ForeignKey("review_tasks.id"), nullable=False, index=True)

    # 风险点基本信息
    title = Column(String(255), nullable=False)
    level = Column(SQLEnum(RiskLevel), nullable=False)
    reason = Column(Text, nullable=True)
    suggestion = Column(Text, nullable=True)

    # 风险分类（新增）
    category = Column(String(50), nullable=True)  # 如：付款条款、违约责任、终止条款、保密条款等

    # 证据材料（新增）
    evidence = Column(Text, nullable=True)  # 引用合同原文作为证据

    # 影响程度（新增）
    impact = Column(Text, nullable=True)  # 如：可能导致资金损失、权益受损等

    # Coze 可替换条款文本
    replace_text = Column(Text, nullable=True)

    # 原文位置信息（用于前端高亮定位）
    position = Column(JSON, nullable=True)  # {"paragraph_index": 0, "char_offset_start": 100, "char_offset_end": 200}
    original_text = Column(Text, nullable=True)  # 风险点所在原文

    # 状态
    status = Column(SQLEnum(RiskStatus), default=RiskStatus.PENDING, nullable=False)

    # 人工确认记录
    confirmed_at = Column(DateTime, nullable=True)
    confirmed_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)  # 确认人（真实外键）
    confirmed_by = Column(String(100), nullable=True)  # 确认人（兼容字段，仅作备份）
    ignore_reason = Column(Text, nullable=True)  # 忽略原因

    # 人工复核备注（新增）
    review_comment = Column(Text, nullable=True)

    # 来源标识（新增）
    source = Column(String(20), default="coze")  # 来源：coze=AI分析, manual=人工标记

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 关联审查任务
    review_task = relationship("ReviewTask", back_populates="risk_points")

    def to_dict(self) -> dict:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "title": self.title,
            "level": self.level.value if self.level else None,
            "reason": self.reason,
            "suggestion": self.suggestion,
            "category": self.category,
            "evidence": self.evidence,
            "impact": self.impact,
            "replace_text": self.replace_text,
            "position": self.position,
            "original_text": self.original_text,
            "status": self.status.value if self.status else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "confirmed_by_user_id": self.confirmed_by_user_id,
            "confirmed_by": self.confirmed_by,
            "ignore_reason": self.ignore_reason,
            "review_comment": self.review_comment,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class ComparisonTask(Base):
    """版本比对任务表。"""
    __tablename__ = "comparison_tasks"

    id = Column(String(36), primary_key=True)  # UUID
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)  # 用户 ID
    old_file_name = Column(String(255), nullable=False)
    new_file_name = Column(String(255), nullable=False)
    old_file_type = Column(String(10), nullable=False)
    new_file_type = Column(String(10), nullable=False)
    old_file_path = Column(String(500), nullable=True)
    new_file_path = Column(String(500), nullable=True)
    old_file_size = Column(Integer, nullable=True)
    new_file_size = Column(Integer, nullable=True)

    # 文件统计
    old_char_count = Column(Integer, nullable=True)
    new_char_count = Column(Integer, nullable=True)
    old_page_count = Column(Integer, nullable=True)
    new_page_count = Column(Integer, nullable=True)
    old_paragraph_count = Column(Integer, nullable=True)
    new_paragraph_count = Column(Integer, nullable=True)

    # 合同完整文本（用于前端左右分栏展示）
    old_text = Column(Text, nullable=True)           # 旧合同纯文本
    new_text = Column(Text, nullable=True)          # 新合同纯文本
    old_sanitized_text = Column(Text, nullable=True)  # 旧合同脱敏后文本
    new_sanitized_text = Column(Text, nullable=True)  # 新合同脱敏后文本

    # diff 结果
    diff_stats = Column(JSON, nullable=True)  # {"total": 0, "added": 0, "deleted": 0, "modified": 0}
    diff_details_json = Column(JSON, nullable=True)  # 差异详情
    position_info_json = Column(JSON, nullable=True)  # 位置信息

    # Coze 增强结果
    coze_enhanced = Column(JSON, nullable=True)
    total_risks = Column(Integer, default=0)

    # 任务状态
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    # 关联
    user = relationship("User")
    risk_points = relationship("ComparisonRiskPoint", back_populates="comparison_task", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "old_file_name": self.old_file_name,
            "new_file_name": self.new_file_name,
            "old_file_type": self.old_file_type,
            "new_file_type": self.new_file_type,
            "old_char_count": self.old_char_count,
            "new_char_count": self.new_char_count,
            "old_paragraph_count": self.old_paragraph_count,
            "new_paragraph_count": self.new_paragraph_count,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "diff_stats": self.diff_stats,
            "total_risks": self.total_risks,
            "status": self.status.value if self.status else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "risk_count": len(self.risk_points),
            "risk_stats": self._get_risk_stats()
        }

    def _get_risk_stats(self) -> dict:
        """获取风险点统计。"""
        total = len(self.risk_points)
        confirmed = sum(1 for rp in self.risk_points if rp.status == RiskStatus.CONFIRMED)
        ignored = sum(1 for rp in self.risk_points if rp.status == RiskStatus.IGNORED)
        pending = total - confirmed - ignored
        return {
            "total": total,
            "confirmed": confirmed,
            "ignored": ignored,
            "pending": pending
        }


class ComparisonRiskPoint(Base):
    """版本比对中的风险点表。"""
    __tablename__ = "comparison_risk_points"

    id = Column(String(36), primary_key=True)  # UUID
    comparison_task_id = Column(String(36), ForeignKey("comparison_tasks.id"), nullable=False, index=True)

    # 差异信息
    change_type = Column(String(20), nullable=False)  # added, deleted, modified
    old_text = Column(Text, nullable=True)
    new_text = Column(Text, nullable=True)
    similarity = Column(Integer, nullable=True)  # 0-100

    # Coze 增强
    summary = Column(Text, nullable=True)
    risk_level = Column(SQLEnum(RiskLevel), nullable=True)
    suggestion = Column(Text, nullable=True)

    # 风险分类（新增）
    category = Column(String(50), nullable=True)
    evidence = Column(Text, nullable=True)  # 证据材料
    impact = Column(Text, nullable=True)  # 影响程度

    # 原文位置
    old_position = Column(JSON, nullable=True)
    new_position = Column(JSON, nullable=True)

    # 来源
    source = Column(String(20), default="coze")

    # 状态
    status = Column(SQLEnum(RiskStatus), default=RiskStatus.PENDING, nullable=False)

    # 人工确认记录
    confirmed_at = Column(DateTime, nullable=True)
    confirmed_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    ignore_reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 关联
    comparison_task = relationship("ComparisonTask", back_populates="risk_points")

    def to_dict(self) -> dict:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "change_type": self.change_type,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "similarity": self.similarity,
            "summary": self.summary,
            "risk_level": self.risk_level.value if self.risk_level else None,
            "suggestion": self.suggestion,
            "category": self.category,
            "evidence": self.evidence,
            "impact": self.impact,
            "old_position": self.old_position,
            "new_position": self.new_position,
            "source": self.source,
            "status": self.status.value if self.status else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "confirmed_by_user_id": self.confirmed_by_user_id,
            "ignore_reason": self.ignore_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
