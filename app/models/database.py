"""数据库模型定义，包含审查任务、风险点、比任务等数据模型。"""

from datetime import datetime
from enum import Enum

from sqlalchemy import JSON
from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import relationship


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类。"""

    pass


class User(Base):
    """用户表。"""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True)  # UUID
    email = Column(String(255), unique=True, nullable=False, index=True)
    phone = Column(String(20), nullable=False, default="")
    nickname = Column(String(100), nullable=False)
    hashed_password = Column(String(255), nullable=False)

    # 用户状态
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)  # 邮箱是否验证

    # 审计字段
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    last_login_at = Column(DateTime, nullable=True)

    # Token quota & usage (0 = unlimited)
    token_quota = Column(Integer, default=0, nullable=False)
    token_used = Column(Integer, default=0, nullable=False)

    def to_dict(self) -> dict:
        """转换为字典格式（不包含密码）。"""
        return {
            "id": self.id,
            "email": self.email,
            "phone": self.phone,
            "nickname": self.nickname,
            "is_active": self.is_active,
            "is_verified": self.is_verified,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat()
            if self.last_login_at
            else None,
            "token_quota": self.token_quota,
            "token_used": self.token_used,
        }


class TaskStatus(str, Enum):
    """任务状态枚举。"""

    PENDING = "pending"  # 待处理
    PROCESSING = "processing"  # 处理中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败


class RiskLevel(str, Enum):
    """风险等级枚举。"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RiskStatus(str, Enum):
    """风险点状态枚举。"""

    PENDING = "pending"  # 待处理
    CONFIRMED = "confirmed"  # 已确认
    IGNORED = "ignored"  # 已忽略


class ReviewType(str, Enum):
    """审查类型枚举。"""

    SINGLE = "single"  # 单合同审查
    COMPARISON = "comparison"  # 版本比对


class RuleVersionStatus(str, Enum):
    """规则版本状态枚举。"""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ReviewRuleVersion(Base):
    """规则版本表，用于锁定每次审查使用的规则集合。"""

    __tablename__ = "review_rule_versions"

    id = Column(String(36), primary_key=True)
    version_no = Column(Integer, unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(
        SQLEnum(RuleVersionStatus), default=RuleVersionStatus.DRAFT, nullable=False
    )
    created_by_user_id = Column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    activated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    rules = relationship(
        "ReviewRule", back_populates="version", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        """转换为接口响应字典。"""
        return {
            "id": self.id,
            "version_no": self.version_no,
            "name": self.name,
            "description": self.description,
            "status": self.status.value if self.status else None,
            "activated_at": self.activated_at.isoformat()
            if self.activated_at
            else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "rule_count": len(self.rules),
        }


class ReviewRule(Base):
    """审核规则明细表。"""

    __tablename__ = "review_rules"

    id = Column(String(36), primary_key=True)
    version_id = Column(
        String(36), ForeignKey("review_rule_versions.id"), nullable=False, index=True
    )
    rule_code = Column(String(50), nullable=False)
    contract_type = Column(String(50), nullable=False)
    review_module = Column(String(50), nullable=False)
    risk_name = Column(String(100), nullable=False)
    check_point = Column(Text, nullable=True)
    trigger_condition = Column(Text, nullable=True)
    default_risk_level = Column(String(20), nullable=False)
    suggestion_template = Column(Text, nullable=True)
    example_clause = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    version = relationship("ReviewRuleVersion", back_populates="rules")

    __table_args__ = (
        Index(
            "ix_review_rules_version_rule_code", "version_id", "rule_code", unique=True
        ),
    )

    def to_dict(self) -> dict:
        """转换为接口响应字典。"""
        return {
            "id": self.id,
            "version_id": self.version_id,
            "rule_code": self.rule_code,
            "contract_type": self.contract_type,
            "review_module": self.review_module,
            "risk_name": self.risk_name,
            "check_point": self.check_point,
            "trigger_condition": self.trigger_condition,
            "default_risk_level": self.default_risk_level,
            "suggestion_template": self.suggestion_template,
            "example_clause": self.example_clause,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ReviewTask(Base):
    """单合同审查任务表。"""

    __tablename__ = "review_tasks"

    id = Column(String(36), primary_key=True)  # UUID
    user_id = Column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )  # 用户 ID
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(10), nullable=False)
    file_path = Column(String(500), nullable=True)  # 文件存储路径
    file_size = Column(Integer, nullable=True)

    # 文件解析结果
    text = Column(Text, nullable=True)  # 合同纯文本
    char_count = Column(Integer, nullable=True)
    page_count = Column(Integer, nullable=True)
    paragraph_count = Column(Integer, nullable=True)
    sentence_count = Column(Integer, nullable=True)
    sanitized_text = Column(Text, nullable=True)  # 脱敏后文本
    sanitization_mapping_json = Column(JSON, nullable=True)
    sanitization_status = Column(String(20), default="not_required", nullable=False)
    sanitization_error = Column(Text, nullable=True)

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
    token_cost = Column(Integer, nullable=True)
    use_coze = Column(Boolean, default=True, nullable=False)

    # 规则版本快照
    rule_version_id = Column(
        String(36), ForeignKey("review_rule_versions.id"), nullable=True, index=True
    )
    rules_snapshot_json = Column(JSON, nullable=True)
    contract_type = Column(String(50), default="通用", nullable=False)

    # 任务状态
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    completed_at = Column(DateTime, nullable=True)

    # 关联
    user = relationship("User")
    risk_points = relationship(
        "RiskPoint", back_populates="review_task", cascade="all, delete-orphan"
    )
    paragraphs = relationship(
        "Paragraph", back_populates="review_task", cascade="all, delete-orphan"
    )
    sentences = relationship(
        "Sentence", back_populates="review_task", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "sanitized_text": self.sanitized_text,
            "sanitization_status": self.sanitization_status,
            "sanitization_error": self.sanitization_error,
            "rule_version_id": self.rule_version_id,
            "contract_type": self.contract_type,
            "char_count": self.char_count,
            "page_count": self.page_count,
            "paragraph_count": self.paragraph_count,
            "sentence_count": self.sentence_count,
            "overall_conclusion": self.overall_conclusion,
            "risk_summary": self.risk_summary,
            "suggest_deep_review": self.suggest_deep_review,
            "token_cost": self.token_cost,
            "use_coze": self.use_coze,
            "status": self.status.value if self.status else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
            "risk_count": len(self.risk_points),
            "risk_stats": self._get_risk_stats(),
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "sentences": [s.to_dict() for s in self.sentences],
            "paragraphs_json": self.paragraphs_json,
        }

    def _get_risk_stats(self) -> dict:
        """获取风险点统计。"""
        total = len(self.risk_points)
        confirmed = sum(
            1 for rp in self.risk_points if rp.status == RiskStatus.CONFIRMED
        )
        ignored = sum(1 for rp in self.risk_points if rp.status == RiskStatus.IGNORED)
        pending = total - confirmed - ignored
        return {
            "total": total,
            "confirmed": confirmed,
            "ignored": ignored,
            "pending": pending,
        }


class Paragraph(Base):
    """段落表，替代 paragraphs_json"""

    __tablename__ = "paragraphs"

    id = Column(String(36), primary_key=True)
    review_task_id = Column(
        String(36), ForeignKey("review_tasks.id"), nullable=False, index=True
    )

    index = Column(Integer, nullable=False)  # 段落索引
    text = Column(Text, nullable=True)  # 段落文本
    char_offset_start = Column(Integer, nullable=True)
    char_offset_end = Column(Integer, nullable=True)
    page_number = Column(Integer, nullable=True)
    is_key_clause = Column(Boolean, default=False)  # 是否关键条款
    paragraph_type = Column(
        String(20), default="body"
    )  # heading1/heading2/heading3/body
    paragraph_level = Column(Integer, default=0)  # 0=正文, 1-3=标题层级

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
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Sentence(Base):
    """句子表，替代 sentences_json"""

    __tablename__ = "sentences"

    id = Column(String(36), primary_key=True)
    review_task_id = Column(
        String(36), ForeignKey("review_tasks.id"), nullable=False, index=True
    )

    index = Column(Integer, nullable=False)
    text = Column(Text, nullable=True)
    char_offset_start = Column(Integer, nullable=True)
    char_offset_end = Column(Integer, nullable=True)
    paragraph_index = Column(Integer, nullable=True)  # 所属段落索引

    created_at = Column(DateTime, default=datetime.utcnow)

    # 关联
    review_task = relationship("ReviewTask", back_populates="sentences")
    risk_points = relationship("RiskPoint", back_populates="sentence")

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
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RiskPoint(Base):
    """风险点表。"""

    __tablename__ = "risk_points"

    id = Column(String(36), primary_key=True)  # UUID
    review_task_id = Column(
        String(36), ForeignKey("review_tasks.id"), nullable=False, index=True
    )

    # 风险点基本信息
    title = Column(String(255), nullable=False)
    level = Column(SQLEnum(RiskLevel), nullable=False)
    reason = Column(Text, nullable=True)
    suggestion = Column(Text, nullable=True)

    # 风险分类
    category = Column(
        String(50), nullable=True
    )  # 如：付款条款、违约责任、终止条款、保密条款等

    # 证据材料
    evidence = Column(Text, nullable=True)  # 引用合同原文作为证据

    # 影响程度
    impact = Column(Text, nullable=True)  # 如：可能导致资金损失、权益受损等

    # Coze 建议替换文本
    replace_text = Column(Text, nullable=True)
    action_type = Column(String(20), nullable=False, default="manual")
    rule_code = Column(String(50), nullable=True, index=True)
    rule_snapshot_json = Column(JSON, nullable=True)

    # 原文位置信息（用于前端高亮定位）
    position = Column(
        JSON, nullable=True
    )  # {"paragraph_index": 0, "char_offset_start": 100, "char_offset_end": 200}

    # 关联句子（一个风险点对应一个句子）
    sentence_id = Column(
        String(36), ForeignKey("sentences.id"), nullable=True, index=True
    )

    # 状态
    status = Column(SQLEnum(RiskStatus), default=RiskStatus.PENDING, nullable=False)

    # 人工确认记录
    confirmed_at = Column(DateTime, nullable=True)
    confirmed_by_user_id = Column(
        String(36), ForeignKey("users.id"), nullable=True
    )  # 确认人（真实外键）
    confirmed_by = Column(String(100), nullable=True)  # 确认人（兼容字段，仅作备份）
    ignore_reason = Column(Text, nullable=True)  # 忽略原因

    # 人工复核备注
    review_comment = Column(Text, nullable=True)

    # 来源标识
    source = Column(String(20), default="coze")  # 来源：coze=AI分析, manual=人工标记

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # 关联
    review_task = relationship("ReviewTask", back_populates="risk_points")
    sentence = relationship("Sentence", back_populates="risk_points")

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
            "action_type": self.action_type,
            "rule_code": self.rule_code,
            "rule_snapshot_json": self.rule_snapshot_json,
            "position": self.position,
            "sentence_id": self.sentence_id,
            "status": self.status.value if self.status else None,
            "confirmed_at": self.confirmed_at.isoformat()
            if self.confirmed_at
            else None,
            "confirmed_by_user_id": self.confirmed_by_user_id,
            "confirmed_by": self.confirmed_by,
            "ignore_reason": self.ignore_reason,
            "review_comment": self.review_comment,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            # 外键关联的句子信息
            "sentence_text": self.sentence.text if self.sentence else None,
        }


class ComparisonDocVersion(str, Enum):
    """对比合同版本枚举。"""

    OLD = "old"
    NEW = "new"


class ComparisonTask(Base):
    """版本比对任务表。"""

    __tablename__ = "comparison_tasks"

    id = Column(String(36), primary_key=True)  # UUID
    user_id = Column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )  # 用户 ID
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
    old_text = Column(Text, nullable=True)  # 旧合同纯文本
    new_text = Column(Text, nullable=True)  # 新合同纯文本
    old_sanitized_text = Column(Text, nullable=True)  # 旧合同脱敏后文本
    new_sanitized_text = Column(Text, nullable=True)  # 新合同脱敏后文本
    old_sanitization_mapping_json = Column(JSON, nullable=True)
    new_sanitization_mapping_json = Column(JSON, nullable=True)
    sanitization_status = Column(String(20), default="not_required", nullable=False)
    sanitization_error = Column(Text, nullable=True)

    # diff 结果
    diff_stats = Column(
        JSON, nullable=True
    )  # {"total": 0, "added": 0, "deleted": 0, "modified": 0}
    diff_details_json = Column(JSON, nullable=True)  # 差异详情
    position_info_json = Column(JSON, nullable=True)  # 位置信息

    # Coze 增强结果
    coze_enhanced = Column(JSON, nullable=True)
    total_risks = Column(Integer, default=0)
    token_cost = Column(Integer, nullable=True)
    enhance = Column(Boolean, default=True, nullable=False)

    # 规则版本快照
    rule_version_id = Column(
        String(36), ForeignKey("review_rule_versions.id"), nullable=True, index=True
    )
    rules_snapshot_json = Column(JSON, nullable=True)
    contract_type = Column(String(50), default="通用", nullable=False)

    # 任务状态
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    completed_at = Column(DateTime, nullable=True)

    # 关联
    user = relationship("User")
    documents = relationship(
        "ComparisonDocument",
        back_populates="comparison_task",
        cascade="all, delete-orphan",
    )
    risk_points = relationship(
        "ComparisonRiskPoint",
        back_populates="comparison_task",
        cascade="all, delete-orphan",
    )

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
            "sanitization_status": self.sanitization_status,
            "sanitization_error": self.sanitization_error,
            "rule_version_id": self.rule_version_id,
            "contract_type": self.contract_type,
            "diff_stats": self.diff_stats,
            "total_risks": self.total_risks,
            "token_cost": self.token_cost,
            "enhance": self.enhance,
            "status": self.status.value if self.status else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
            "risk_count": len(self.risk_points),
            "risk_stats": self._get_risk_stats(),
        }

    def _get_risk_stats(self) -> dict:
        """获取风险点统计。"""
        total = len(self.risk_points)
        confirmed = sum(
            1 for rp in self.risk_points if rp.status == RiskStatus.CONFIRMED
        )
        ignored = sum(1 for rp in self.risk_points if rp.status == RiskStatus.IGNORED)
        pending = total - confirmed - ignored
        return {
            "total": total,
            "confirmed": confirmed,
            "ignored": ignored,
            "pending": pending,
        }


class ComparisonDocument(Base):
    """对比合同子表，存储比对任务中的两个合同文档。"""

    __tablename__ = "comparison_documents"

    id = Column(String(36), primary_key=True)  # UUID
    comparison_task_id = Column(
        String(36), ForeignKey("comparison_tasks.id"), nullable=False, index=True
    )
    version = Column(SQLEnum(ComparisonDocVersion), nullable=False)  # old / new

    file_name = Column(String(255), nullable=False)
    file_type = Column(String(10), nullable=False)
    file_size = Column(Integer, nullable=True)

    text = Column(Text, nullable=True)  # 合同纯文本
    char_count = Column(Integer, nullable=True)
    page_count = Column(Integer, nullable=True)
    paragraph_count = Column(Integer, nullable=True)
    sentence_count = Column(Integer, nullable=True)
    sanitized_text = Column(Text, nullable=True)  # 脱敏后文本

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # 关联
    comparison_task = relationship("ComparisonTask", back_populates="documents")
    sentences = relationship(
        "ComparisonSentence", back_populates="document", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "comparison_task_id": self.comparison_task_id,
            "version": self.version.value if self.version else None,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "char_count": self.char_count,
            "page_count": self.page_count,
            "paragraph_count": self.paragraph_count,
            "sentence_count": self.sentence_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ComparisonSentence(Base):
    """对比任务的句子表，存储每个合同的句子级结构。"""

    __tablename__ = "comparison_sentences"

    id = Column(String(36), primary_key=True)  # UUID
    comparison_document_id = Column(
        String(36), ForeignKey("comparison_documents.id"), nullable=False, index=True
    )

    index = Column(Integer, nullable=False)  # 句子在合同中的索引
    text = Column(Text, nullable=True)
    char_offset_start = Column(Integer, nullable=True)  # 字符起始位置
    char_offset_end = Column(Integer, nullable=True)  # 字符结束位置
    paragraph_index = Column(Integer, nullable=True)  # 所属段落索引

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 关联
    document = relationship("ComparisonDocument", back_populates="sentences")

    def to_dict(self) -> dict:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "comparison_document_id": self.comparison_document_id,
            "index": self.index,
            "text": self.text,
            "char_offset_start": self.char_offset_start,
            "char_offset_end": self.char_offset_end,
            "paragraph_index": self.paragraph_index,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ComparisonRiskPoint(Base):
    """版本比对中的风险点表。"""

    __tablename__ = "comparison_risk_points"

    id = Column(String(36), primary_key=True)  # UUID
    comparison_task_id = Column(
        String(36), ForeignKey("comparison_tasks.id"), nullable=False, index=True
    )

    # 差异信息
    change_type = Column(String(20), nullable=False)  # added, deleted, modified
    old_text = Column(Text, nullable=True)
    new_text = Column(Text, nullable=True)
    similarity = Column(Integer, nullable=True)  # 0-100

    # Coze 增强
    summary = Column(Text, nullable=True)
    risk_level = Column(SQLEnum(RiskLevel), nullable=True)
    suggestion = Column(Text, nullable=True)
    rule_code = Column(String(50), nullable=True, index=True)
    rule_snapshot_json = Column(JSON, nullable=True)

    # 风险分类
    category = Column(String(50), nullable=True)
    evidence = Column(Text, nullable=True)  # 证据材料
    impact = Column(Text, nullable=True)  # 影响程度

    # 原文位置
    old_position = Column(JSON, nullable=True)
    new_position = Column(JSON, nullable=True)

    # 句子级定位（新增）
    old_sentence_id = Column(
        String(36), ForeignKey("comparison_sentences.id"), nullable=True, index=True
    )
    new_sentence_id = Column(
        String(36), ForeignKey("comparison_sentences.id"), nullable=True, index=True
    )

    # 来源
    source = Column(String(20), default="coze")

    # 状态
    status = Column(SQLEnum(RiskStatus), default=RiskStatus.PENDING, nullable=False)

    # 人工确认记录
    confirmed_at = Column(DateTime, nullable=True)
    confirmed_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    ignore_reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # 关联
    comparison_task = relationship("ComparisonTask", back_populates="risk_points")
    old_sentence = relationship("ComparisonSentence", foreign_keys=[old_sentence_id])
    new_sentence = relationship("ComparisonSentence", foreign_keys=[new_sentence_id])

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
            "rule_code": self.rule_code,
            "rule_snapshot_json": self.rule_snapshot_json,
            "category": self.category,
            "evidence": self.evidence,
            "impact": self.impact,
            "old_position": self.old_position,
            "new_position": self.new_position,
            "old_sentence_id": self.old_sentence_id,
            "new_sentence_id": self.new_sentence_id,
            "source": self.source,
            "status": self.status.value if self.status else None,
            "confirmed_at": self.confirmed_at.isoformat()
            if self.confirmed_at
            else None,
            "confirmed_by_user_id": self.confirmed_by_user_id,
            "ignore_reason": self.ignore_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class OptimizedContractVersion(Base):
    """优化后合同版本表。"""

    __tablename__ = "optimized_contract_versions"

    id = Column(String(36), primary_key=True)
    review_task_id = Column(
        String(36), ForeignKey("review_tasks.id"), nullable=False, index=True
    )
    version_no = Column(Integer, nullable=False)
    title = Column(String(255), nullable=False)
    text = Column(Text, nullable=False)
    accepted_risk_ids_json = Column(JSON, nullable=True)
    created_by_user_id = Column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    review_task = relationship("ReviewTask")

    __table_args__ = (
        Index(
            "ix_optimized_versions_task_version",
            "review_task_id",
            "version_no",
            unique=True,
        ),
    )

    def to_dict(self) -> dict:
        """转换为接口响应字典。"""
        return {
            "id": self.id,
            "review_task_id": self.review_task_id,
            "version_no": self.version_no,
            "title": self.title,
            "text": self.text,
            "accepted_risk_ids": self.accepted_risk_ids_json or [],
            "created_by_user_id": self.created_by_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AcceptedSuggestion(Base):
    """采纳建议记录表。"""

    __tablename__ = "accepted_suggestions"

    id = Column(String(36), primary_key=True)
    optimized_version_id = Column(
        String(36),
        ForeignKey("optimized_contract_versions.id"),
        nullable=False,
        index=True,
    )
    risk_point_id = Column(
        String(36), ForeignKey("risk_points.id"), nullable=False, index=True
    )
    original_text = Column(Text, nullable=True)
    replace_text = Column(Text, nullable=False)
    position = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
