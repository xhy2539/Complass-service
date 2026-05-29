"""合同版本比对路由，支持双文件上传、任务创建、diff 计算和 Coze 语义增强。"""

import logging
import uuid
from datetime import datetime
from typing import Annotated
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import HTTPException
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.models.database import ComparisonDocument
from app.models.database import ComparisonDocVersion
from app.models.database import ComparisonRiskPoint
from app.models.database import ComparisonSentence
from app.models.database import ComparisonTask
from app.models.database import RiskLevel
from app.models.database import TaskStatus
from app.models.database import User
from app.models.database_connection import get_db
from app.schemas.comparison import ComparisonRiskPointSchema
from app.schemas.comparison import ComparisonTaskSchema
from app.schemas.review import ComparisonRiskListResponse
from app.schemas.review import ComparisonTaskListResponse
from app.schemas.review import RiskStatsSchema
from app.services.coze_service import get_coze_service
from app.services.document_parser import DocumentParseError
from app.services.document_parser import DocumentParser
from app.services.rule_service import build_enabled_rules_snapshot
from app.services.rule_service import find_rule_snapshot
from app.services.sanitization_service import apply_sanitization_mappings
from app.services.sanitization_service import restore_text_from_mapping
from app.services.sanitization_service import sanitize_contract_text
from app.services.text_diff import sentence_diff_with_positions
from app.services.text_diff import summarize_diff

logger = logging.getLogger(__name__)

contract_comparison_router = APIRouter(tags=["合同版本比对"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _uuid() -> str:
    """生成 UUID。"""
    return str(uuid.uuid4())


def validate_file(file: UploadFile) -> None:
    """验证文件是否有效。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    if not DocumentParser.is_supported(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式，仅支持: {', '.join(DocumentParser.SUPPORTED_EXTENSIONS)}",
        )


@contract_comparison_router.post("/comparisons", response_model=dict)
async def create_comparison_task(
    old_file: Annotated[UploadFile, File(description="旧版本合同")],
    new_file: Annotated[UploadFile, File(description="新版本合同")],
    enhance: bool = True,
    contract_type: str = "通用",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    创建版本比对任务。

    流程：上传两个文件 → 创建任务 → 解析 → 创建文档和句子记录 → diff → Coze增强（如启用）→ 保存结果
    返回 task_id 供后续查询。
    """
    # 验证文件
    validate_file(old_file)
    validate_file(new_file)

    # 读取文件内容
    old_content = await old_file.read()
    new_content = await new_file.read()

    if len(old_content) == 0:
        raise HTTPException(status_code=400, detail="旧版本文件内容为空")
    if len(new_content) == 0:
        raise HTTPException(status_code=400, detail="新版本文件内容为空")

    if len(old_content) > MAX_FILE_SIZE or len(new_content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过 10MB 限制")

    # 解析文档
    try:
        old_doc = DocumentParser.parse(old_content, old_file.filename)
        new_doc = DocumentParser.parse(new_content, new_file.filename)
    except DocumentParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    old_sanitization = sanitize_contract_text(old_doc.text)
    new_sanitization = sanitize_contract_text(new_doc.text)
    sanitization_errors = old_sanitization.errors + new_sanitization.errors
    if sanitization_errors:
        raise HTTPException(status_code=422, detail="; ".join(sanitization_errors))

    rule_version = None
    rules_snapshot: list[dict] = []
    if enhance:
        try:
            rule_version, rules_snapshot = build_enabled_rules_snapshot(
                db, contract_type
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not rules_snapshot:
            raise HTTPException(
                status_code=400, detail="当前合同类型没有可用的启用规则"
            )

    # 创建比对任务
    task_id = _uuid()
    task = ComparisonTask(
        id=task_id,
        user_id=current_user.id,
        old_file_name=old_doc.file_name,
        new_file_name=new_doc.file_name,
        old_file_type=old_doc.file_type,
        new_file_type=new_doc.file_type,
        old_file_size=len(old_content),
        new_file_size=len(new_content),
        old_char_count=old_doc.char_count,
        new_char_count=new_doc.char_count,
        old_page_count=old_doc.page_count,
        new_page_count=new_doc.page_count,
        old_paragraph_count=len(old_doc.paragraphs),
        new_paragraph_count=len(new_doc.paragraphs),
        old_text=old_doc.text,
        new_text=new_doc.text,
        old_sanitized_text=old_sanitization.sanitized_text,
        new_sanitized_text=new_sanitization.sanitized_text,
        old_sanitization_mapping_json=old_sanitization.mappings,
        new_sanitization_mapping_json=new_sanitization.mappings,
        sanitization_status="completed",
        rule_version_id=rule_version.id if rule_version else None,
        rules_snapshot_json=rules_snapshot,
        contract_type=contract_type,
        status=TaskStatus.PROCESSING,
    )

    db.add(task)

    # 创建旧合同文档记录
    old_doc_id = _uuid()
    old_document = ComparisonDocument(
        id=old_doc_id,
        comparison_task_id=task_id,
        version=ComparisonDocVersion.OLD,
        file_name=old_doc.file_name,
        file_type=old_doc.file_type,
        file_size=len(old_content),
        text=old_doc.text,
        char_count=old_doc.char_count,
        page_count=old_doc.page_count,
        paragraph_count=len(old_doc.paragraphs),
        sentence_count=len(old_doc.sentences),
        sanitized_text=old_sanitization.sanitized_text,
    )
    db.add(old_document)

    # 创建新合同文档记录
    new_doc_id = _uuid()
    new_document = ComparisonDocument(
        id=new_doc_id,
        comparison_task_id=task_id,
        version=ComparisonDocVersion.NEW,
        file_name=new_doc.file_name,
        file_type=new_doc.file_type,
        file_size=len(new_content),
        text=new_doc.text,
        char_count=new_doc.char_count,
        page_count=new_doc.page_count,
        paragraph_count=len(new_doc.paragraphs),
        sentence_count=len(new_doc.sentences),
        sanitized_text=new_sanitization.sanitized_text,
    )
    db.add(new_document)

    # 创建旧合同句子记录
    old_sentences_info = {}
    for idx, s in enumerate(old_doc.sentences):
        sentence_id = _uuid()
        sentence = ComparisonSentence(
            id=sentence_id,
            comparison_document_id=old_doc_id,
            index=idx,
            text=s.get("text", ""),
            char_offset_start=s.get("char_offset_start"),
            char_offset_end=s.get("char_offset_end"),
            paragraph_index=s.get("paragraph_index"),
        )
        db.add(sentence)
        old_sentences_info[idx] = {"id": sentence_id, "text": s.get("text", "")}

    # 创建新合同句子记录
    new_sentences_info = {}
    for idx, s in enumerate(new_doc.sentences):
        sentence_id = _uuid()
        sentence = ComparisonSentence(
            id=sentence_id,
            comparison_document_id=new_doc_id,
            index=idx,
            text=s.get("text", ""),
            char_offset_start=s.get("char_offset_start"),
            char_offset_end=s.get("char_offset_end"),
            paragraph_index=s.get("paragraph_index"),
        )
        db.add(sentence)
        new_sentences_info[idx] = {"id": sentence_id, "text": s.get("text", "")}

    # 立即 flush，确保句子写入数据库，获取真实 ID
    db.flush()

    # 构建用于 diff 比对的句子数据
    old_comparison_data = {
        "sentences": [
            {
                "index": idx,
                "text": s["text"],
                "char_offset_start": s["char_offset_start"],
                "char_offset_end": s["char_offset_end"],
                "paragraph_index": s["paragraph_index"],
            }
            for idx, s in enumerate(old_doc.sentences)
        ],
        "key_clauses": [p for p in old_doc.paragraphs if p.is_key_clause],
    }

    new_comparison_data = {
        "sentences": [
            {
                "index": idx,
                "text": s["text"],
                "char_offset_start": s["char_offset_start"],
                "char_offset_end": s["char_offset_end"],
                "paragraph_index": s["paragraph_index"],
            }
            for idx, s in enumerate(new_doc.sentences)
        ],
        "key_clauses": [p for p in new_doc.paragraphs if p.is_key_clause],
    }

    # 使用带位置的句子级 diff
    diffs = sentence_diff_with_positions(old_comparison_data, new_comparison_data)
    summary = summarize_diff(diffs)

    # 构建 Coze 新版格式的 diff_texts（脱敏后）
    diff_texts = []
    for d in diffs:
        if d.change_type == "modified":
            old_text = apply_sanitization_mappings(
                d.old_text or "", old_sanitization.mappings
            )
            new_text = apply_sanitization_mappings(
                d.new_text or "", new_sanitization.mappings
            )
            content = f"修改内容：{old_text} → {new_text}"
        elif d.change_type == "added":
            new_text = apply_sanitization_mappings(
                d.new_text or "", new_sanitization.mappings
            )
            content = f"新增内容：{new_text}"
        elif d.change_type == "deleted":
            old_text = apply_sanitization_mappings(
                d.old_text or "", old_sanitization.mappings
            )
            content = f"删除内容：{old_text}"
        else:
            continue
        diff_texts.append({"type": d.change_type, "content": content})

    # 保存 diff 结果
    task.diff_stats = {
        "total": summary["total"],
        "added": summary["added"],
        "deleted": summary["deleted"],
        "modified": summary["modified"],
    }
    task.diff_details_json = [
        {
            "index": d.index,
            "change_type": d.change_type,
            "old_text": d.old_text,
            "new_text": d.new_text,
            "similarity": round(d.similarity, 2),
            "old_position": d.old_position,
            "new_position": d.new_position,
        }
        for d in diffs
    ]
    task.position_info_json = {
        "old_paragraphs": [
            {
                "index": p.index,
                "text": p.text,
                "char_offset_start": p.char_offset_start,
                "char_offset_end": p.char_offset_end,
                "page_number": p.page_number,
                "is_key_clause": p.is_key_clause,
            }
            for p in old_doc.paragraphs
        ],
        "new_paragraphs": [
            {
                "index": p.index,
                "text": p.text,
                "char_offset_start": p.char_offset_start,
                "char_offset_end": p.char_offset_end,
                "page_number": p.page_number,
                "is_key_clause": p.is_key_clause,
            }
            for p in new_doc.paragraphs
        ],
    }

    # Coze 语义增强
    if enhance:
        if (
            current_user.token_quota > 0
            and current_user.token_used >= current_user.token_quota
        ):
            raise HTTPException(
                status_code=402, detail="Token 配额已用完，请联系管理员升级"
            )

        try:
            coze_service = get_coze_service()
            coze_result, usage = await coze_service.enhance_diff_result(
                {
                    "old_text": old_sanitization.sanitized_text,
                    "new_text": new_sanitization.sanitized_text,
                    "diff_stats": task.diff_stats,
                    "diff_texts": diff_texts,
                    "rules": rules_snapshot,
                    "rule_version_id": rule_version.id if rule_version else None,
                    "contract_type": contract_type,
                }
            )

            task.coze_enhanced = coze_result.get("enhanced", [])
            task.total_risks = coze_result.get("total_risks", 0)
            task.token_cost = usage.get("token_count", 0)
            current_user.token_used = current_user.token_used + usage.get(
                "token_count", 0
            )
            coze_stats = coze_result.get("stats") or {}
            if coze_stats:
                task.diff_stats = {
                    "total": sum(coze_stats.values()),
                    "added": coze_stats.get("added", 0),
                    "deleted": coze_stats.get("deleted", 0),
                    "modified": coze_stats.get("modified", 0),
                }

            # 创建比对风险点
            for enhanced in coze_result.get("enhanced", []):
                rule_code = enhanced.get("rule_code") or enhanced.get("rule_id")
                # Coze 返回字段: category, change_type, evidence, impact,
                #               new_quote, old_quote, original, risk_level, suggestion, summary
                # 找到对应的 diff 项（通过 new_quote/old_quote 匹配）
                diff_item = None
                coze_old_quote = enhanced.get("old_quote", "")
                coze_new_quote = enhanced.get("new_quote", "")

                for d in diffs:
                    if d.change_type == enhanced.get("change_type"):
                        # 用 Coze 的 old_quote/new_quote 匹配 diff 的文本
                        if coze_old_quote and coze_old_quote in (d.old_text or ""):
                            diff_item = d
                            break
                        if coze_new_quote and coze_new_quote in (d.new_text or ""):
                            diff_item = d
                            break
                        if enhanced.get("original") and (
                            enhanced.get("original") in (d.old_text or "")
                            or enhanced.get("original") in (d.new_text or "")
                        ):
                            diff_item = d
                            break

                # 根据 diff 类型确定 sentence 外键
                change_type = enhanced.get("change_type", "modified")
                old_sentence_id = None
                new_sentence_id = None

                if diff_item:
                    if change_type == "deleted":
                        # deleted: 只有旧合同有句子
                        for idx, info in old_sentences_info.items():
                            if info["text"] == diff_item.old_text:
                                old_sentence_id = info["id"]
                                break
                    elif change_type == "added":
                        # added: 只有新合同有句子
                        for idx, info in new_sentences_info.items():
                            if info["text"] == diff_item.new_text:
                                new_sentence_id = info["id"]
                                break
                    else:
                        # modified: 旧新都有
                        if diff_item.old_text:
                            for idx, info in old_sentences_info.items():
                                if info["text"] == diff_item.old_text:
                                    old_sentence_id = info["id"]
                                    break
                        if diff_item.new_text:
                            for idx, info in new_sentences_info.items():
                                if info["text"] == diff_item.new_text:
                                    new_sentence_id = info["id"]
                                    break

                risk_point = ComparisonRiskPoint(
                    id=_uuid(),
                    comparison_task_id=task_id,
                    change_type=change_type,
                    # 优先用 diff_item 的文本，其次用 Coze 的 old_quote/new_quote
                    old_text=diff_item.old_text if diff_item else coze_old_quote,
                    new_text=diff_item.new_text
                    if diff_item
                    else coze_new_quote or enhanced.get("original", ""),
                    similarity=int(diff_item.similarity * 100) if diff_item else 0,
                    summary=restore_text_from_mapping(
                        enhanced.get("summary") or "", new_sanitization.mappings
                    ),
                    risk_level=RiskLevel(enhanced.get("risk_level", "low")),
                    rule_code=rule_code,
                    rule_snapshot_json=find_rule_snapshot(rules_snapshot, rule_code),
                    category=enhanced.get("category"),
                    evidence=restore_text_from_mapping(
                        enhanced.get("evidence") or "",
                        old_sanitization.mappings + new_sanitization.mappings,
                    ),
                    impact=restore_text_from_mapping(
                        enhanced.get("impact") or "", new_sanitization.mappings
                    ),
                    suggestion=restore_text_from_mapping(
                        enhanced.get("suggestion") or "", new_sanitization.mappings
                    ),
                    old_position=diff_item.old_position if diff_item else None,
                    new_position=diff_item.new_position if diff_item else None,
                    old_sentence_id=old_sentence_id,
                    new_sentence_id=new_sentence_id,
                    source="coze",
                )
                db.add(risk_point)

        except Exception as e:
            logger.error(f"[Comparison] Coze 增强失败: {type(e).__name__}: {e}")
            task.coze_enhanced = []
            task.total_risks = 0

    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.utcnow()
    db.commit()

    return {
        "success": True,
        "task_id": task_id,
        "message": "版本比对任务创建成功",
        "old_file": {
            "name": old_doc.file_name,
            "type": old_doc.file_type,
            "char_count": old_doc.char_count,
            "page_count": old_doc.page_count,
            "paragraph_count": len(old_doc.paragraphs),
            "sentence_count": len(old_doc.sentences),
        },
        "new_file": {
            "name": new_doc.file_name,
            "type": new_doc.file_type,
            "char_count": new_doc.char_count,
            "page_count": new_doc.page_count,
            "paragraph_count": len(new_doc.paragraphs),
            "sentence_count": len(new_doc.sentences),
        },
        "diff_stats": task.diff_stats,
    }


@contract_comparison_router.get("/comparisons/{task_id}")
async def get_comparison_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """查询版本比对任务详情，包括差异列表、风险点和合同文档信息。"""
    task = (
        db.query(ComparisonTask)
        .filter(ComparisonTask.id == task_id, ComparisonTask.user_id == current_user.id)
        .first()
    )

    if not task:
        raise HTTPException(
            status_code=404, detail=f"比对任务 {task_id} 不存在或无权访问"
        )

    # 获取合同文档
    documents = (
        db.query(ComparisonDocument)
        .filter(ComparisonDocument.comparison_task_id == task_id)
        .all()
    )

    # 获取风险点
    risk_points = (
        db.query(ComparisonRiskPoint)
        .filter(ComparisonRiskPoint.comparison_task_id == task_id)
        .all()
    )

    return {
        "success": True,
        "task": task.to_dict(),
        "documents": [doc.to_dict() for doc in documents],
        "diff_details": task.diff_details_json,
        "risk_points": [rp.to_dict() for rp in risk_points],
        "coze_enhanced": task.coze_enhanced,
        "message": "查询成功",
    }


@contract_comparison_router.get(
    "/comparisons", response_model=ComparisonTaskListResponse
)
async def list_comparison_tasks(
    skip: int = 0,
    limit: int = 20,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ComparisonTaskListResponse:
    """查询当前用户的版本比对任务列表（支持分页和状态筛选）。"""
    query = db.query(ComparisonTask).filter(ComparisonTask.user_id == current_user.id)

    if status:
        try:
            status_enum = TaskStatus(status)
            query = query.filter(ComparisonTask.status == status_enum)
        except ValueError:
            pass

    total = query.count()
    tasks = (
        query.order_by(ComparisonTask.created_at.desc()).offset(skip).limit(limit).all()
    )

    return ComparisonTaskListResponse(
        tasks=[ComparisonTaskSchema.model_validate(t.to_dict()) for t in tasks],
        total=total,
        skip=skip,
        limit=limit,
    )


@contract_comparison_router.get(
    "/comparisons/{task_id}/risks", response_model=ComparisonRiskListResponse
)
async def get_comparison_task_risks(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ComparisonRiskListResponse:
    """查询指定比对任务的风险点列表。"""
    task = (
        db.query(ComparisonTask)
        .filter(ComparisonTask.id == task_id, ComparisonTask.user_id == current_user.id)
        .first()
    )

    if not task:
        raise HTTPException(
            status_code=404, detail=f"比对任务 {task_id} 不存在或无权访问"
        )

    risk_points = (
        db.query(ComparisonRiskPoint)
        .filter(ComparisonRiskPoint.comparison_task_id == task_id)
        .all()
    )

    total = len(risk_points)
    pending = sum(1 for rp in risk_points if rp.status == "pending")
    confirmed = sum(1 for rp in risk_points if rp.status == "confirmed")
    ignored = sum(1 for rp in risk_points if rp.status == "ignored")

    return ComparisonRiskListResponse(
        task_id=task_id,
        risk_points=[
            ComparisonRiskPointSchema.model_validate(rp.to_dict()) for rp in risk_points
        ],
        total=total,
        risk_stats=RiskStatsSchema(
            total=total, pending=pending, confirmed=confirmed, ignored=ignored
        ),
    )
