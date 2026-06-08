"""合同版本比对路由，支持双文件上传、任务创建、diff 计算和 Coze 语义增强。"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Annotated
from typing import Optional

from fastapi import APIRouter
from fastapi import BackgroundTasks
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
from app.models.database_connection import SessionLocal
from app.models.database_connection import get_db
from app.schemas.comparison import ComparisonRiskPointSchema
from app.schemas.comparison import ComparisonTaskSchema
from app.schemas.review import ComparisonRiskListResponse
from app.schemas.review import ComparisonTaskListResponse
from app.schemas.review import RiskStatsSchema
from app.services.coze_service import get_coze_service
from app.services.document_parser import DocumentParser
from app.services.rule_service import build_enabled_rules_snapshot
from app.services.rule_service import find_rule_snapshot
from app.services.sanitization_service import apply_sanitization_mappings
from app.services.sanitization_service import restore_text_from_mapping
from app.services.sanitization_service import sanitize_contract_text
from app.services.task_file_storage import read_task_upload
from app.services.task_file_storage import save_task_upload
from app.services.text_diff import sentence_diff_with_positions
from app.services.text_diff import summarize_diff

logger = logging.getLogger(__name__)

contract_comparison_router = APIRouter(tags=["合同版本比对"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _uuid() -> str:
    """生成 UUID。"""
    return str(uuid.uuid4())


def _ensure_list(value) -> list:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


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
    background_tasks: BackgroundTasks,
    old_file: Annotated[UploadFile, File(description="旧版本合同")],
    new_file: Annotated[UploadFile, File(description="新版本合同")],
    enhance: bool = True,
    contract_type: str = "通用",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """创建版本比对任务并异步执行处理。"""
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

    task_id = _uuid()
    old_file_path = save_task_upload(
        task_id, "old", old_file.filename or "old_contract", old_content
    )
    new_file_path = save_task_upload(
        task_id, "new", new_file.filename or "new_contract", new_content
    )
    task = ComparisonTask(
        id=task_id,
        user_id=current_user.id,
        old_file_name=old_file.filename or "unknown",
        new_file_name=new_file.filename or "unknown",
        old_file_type=(
            old_file.filename.rsplit(".", 1)[-1].lower()
            if old_file.filename and "." in old_file.filename
            else "unknown"
        ),
        new_file_type=(
            new_file.filename.rsplit(".", 1)[-1].lower()
            if new_file.filename and "." in new_file.filename
            else "unknown"
        ),
        old_file_size=len(old_content),
        new_file_size=len(new_content),
        old_file_path=old_file_path,
        new_file_path=new_file_path,
        sanitization_status="not_required",
        diff_details_json=[],
        rules_snapshot_json=[],
        contract_type=contract_type,
        enhance=enhance,
        status=TaskStatus.PENDING,
    )

    db.add(task)
    db.commit()
    background_tasks.add_task(
        _process_comparison_task_background,
        task_id,
        current_user.id,
        old_file.filename or "unknown",
        new_file.filename or "unknown",
        old_file_path,
        new_file_path,
        enhance,
        contract_type,
    )

    return {
        "success": True,
        "task_id": task_id,
        "message": "版本比对任务已提交",
    }


def _process_comparison_task_background(
    task_id: str,
    user_id: str,
    old_file_name: str,
    new_file_name: str,
    old_file_path: str,
    new_file_path: str,
    enhance: bool,
    contract_type: str,
) -> None:
    """后台处理比对任务，独立管理事务。"""
    db = SessionLocal()
    try:
        asyncio.run(
            _run_comparison_task_async(
                db=db,
                task_id=task_id,
                user_id=user_id,
                old_file_name=old_file_name,
                new_file_name=new_file_name,
                old_file_path=old_file_path,
                new_file_path=new_file_path,
                enhance=enhance,
                contract_type=contract_type,
            )
        )
        db.commit()
        try:
            current_user = db.query(User).filter(User.id == user_id).first()
            open_id = (
                (current_user.feishu_open_id or "").strip() if current_user else ""
            )
            if open_id:
                task = (
                    db.query(ComparisonTask)
                    .filter(
                        ComparisonTask.id == task_id, ComparisonTask.user_id == user_id
                    )
                    .first()
                )
                from app.services.feishu_bot import send_comparison_completed_card

                send_comparison_completed_card(
                    open_id,
                    task_id,
                    (
                        task.old_file_name
                        if task and task.old_file_name
                        else old_file_name
                    ),
                    (
                        task.new_file_name
                        if task and task.new_file_name
                        else new_file_name
                    ),
                )
        except Exception as e:
            logger.error(
                "[Comparison] 发送飞书比对完成卡片失败 task_id=%s: %s", task_id, e
            )
    except Exception as e:
        db.rollback()
        task = db.query(ComparisonTask).filter(ComparisonTask.id == task_id).first()
        if task:
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.utcnow()
            task.sanitization_error = str(e)
            db.commit()
        logger.exception("[Comparison] 后台任务失败 task_id=%s", task_id)
    finally:
        db.close()


async def _run_comparison_task_async(
    db: Session,
    task_id: str,
    user_id: str,
    old_file_name: str,
    new_file_name: str,
    old_file_path: str,
    new_file_path: str,
    enhance: bool,
    contract_type: str,
) -> None:
    """后台执行比对任务主流程。"""
    task = (
        db.query(ComparisonTask)
        .filter(ComparisonTask.id == task_id, ComparisonTask.user_id == user_id)
        .first()
    )
    current_user = db.query(User).filter(User.id == user_id).first()
    if not task or not current_user:
        raise RuntimeError("任务或用户不存在")
    task.status = TaskStatus.PROCESSING
    db.commit()

    old_content = read_task_upload(old_file_path)
    new_content = read_task_upload(new_file_path)
    old_doc = DocumentParser.parse(old_content, old_file_name)
    new_doc = DocumentParser.parse(new_content, new_file_name)
    old_sanitization = sanitize_contract_text(old_doc.text)
    new_sanitization = sanitize_contract_text(new_doc.text)
    sanitization_errors = old_sanitization.errors + new_sanitization.errors
    if sanitization_errors:
        raise RuntimeError("; ".join(sanitization_errors))

    rule_version = None
    rules_snapshot: list[dict] = []
    if enhance:
        rule_version, rules_snapshot = build_enabled_rules_snapshot(db, contract_type)
        if not rules_snapshot:
            raise RuntimeError("当前合同类型没有可用的启用规则")

    db.query(ComparisonRiskPoint).filter(
        ComparisonRiskPoint.comparison_task_id == task_id
    ).delete()
    for doc in (
        db.query(ComparisonDocument)
        .filter(ComparisonDocument.comparison_task_id == task_id)
        .all()
    ):
        db.query(ComparisonSentence).filter(
            ComparisonSentence.comparison_document_id == doc.id
        ).delete()
    db.query(ComparisonDocument).filter(
        ComparisonDocument.comparison_task_id == task_id
    ).delete()
    db.commit()

    task.old_file_name = old_doc.file_name
    task.new_file_name = new_doc.file_name
    task.old_file_type = old_doc.file_type
    task.new_file_type = new_doc.file_type
    task.old_file_path = old_file_path
    task.new_file_path = new_file_path
    task.old_char_count = old_doc.char_count
    task.new_char_count = new_doc.char_count
    task.old_page_count = old_doc.page_count
    task.new_page_count = new_doc.page_count
    task.old_paragraph_count = len(old_doc.paragraphs)
    task.new_paragraph_count = len(new_doc.paragraphs)
    task.old_text = old_doc.text
    task.new_text = new_doc.text
    task.old_sanitized_text = old_sanitization.sanitized_text
    task.new_sanitized_text = new_sanitization.sanitized_text
    task.old_sanitization_mapping_json = old_sanitization.mappings
    task.new_sanitization_mapping_json = new_sanitization.mappings
    task.sanitization_status = "completed"
    task.rule_version_id = None
    task.rules_snapshot_json = rules_snapshot

    old_doc_id = _uuid()
    new_doc_id = _uuid()
    db.add(
        ComparisonDocument(
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
    )
    db.add(
        ComparisonDocument(
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
    )

    old_sentences_info = {}
    new_sentences_info = {}
    for idx, s in enumerate(old_doc.sentences):
        sentence_id = _uuid()
        db.add(
            ComparisonSentence(
                id=sentence_id,
                comparison_document_id=old_doc_id,
                index=idx,
                text=s.get("text", ""),
                char_offset_start=s.get("char_offset_start"),
                char_offset_end=s.get("char_offset_end"),
                paragraph_index=s.get("paragraph_index"),
            )
        )
        old_sentences_info[idx] = {"id": sentence_id, "text": s.get("text", "")}
    for idx, s in enumerate(new_doc.sentences):
        sentence_id = _uuid()
        db.add(
            ComparisonSentence(
                id=sentence_id,
                comparison_document_id=new_doc_id,
                index=idx,
                text=s.get("text", ""),
                char_offset_start=s.get("char_offset_start"),
                char_offset_end=s.get("char_offset_end"),
                paragraph_index=s.get("paragraph_index"),
            )
        )
        new_sentences_info[idx] = {"id": sentence_id, "text": s.get("text", "")}
    db.flush()

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
    diffs = sentence_diff_with_positions(old_comparison_data, new_comparison_data)
    summary = summarize_diff(diffs)
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

    if enhance:
        if (
            current_user.token_quota > 0
            and current_user.token_used >= current_user.token_quota
        ):
            raise RuntimeError("Token 配额已用完，请联系管理员升级")
        try:
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
                    content = f"新增内容：{apply_sanitization_mappings(d.new_text or '', new_sanitization.mappings)}"
                elif d.change_type == "deleted":
                    content = f"删除内容：{apply_sanitization_mappings(d.old_text or '', old_sanitization.mappings)}"
                else:
                    continue
                diff_texts.append({"type": d.change_type, "content": content})

            coze_service = get_coze_service()
            coze_result, usage = await coze_service.enhance_diff_result(
                {
                    "old_text": old_sanitization.sanitized_text,
                    "new_text": new_sanitization.sanitized_text,
                    "diff_stats": task.diff_stats,
                    "diff_texts": diff_texts,
                    "rules": rules_snapshot,
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

            for enhanced in coze_result.get("enhanced", []):
                rule_code = enhanced.get("rule_code") or enhanced.get("rule_id")
                diff_item = None
                coze_old_quote = enhanced.get("old_quote", "")
                coze_new_quote = enhanced.get("new_quote", "")
                for d in diffs:
                    if d.change_type != enhanced.get("change_type"):
                        continue
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
                change_type = enhanced.get("change_type", "modified")
                old_sentence_id = None
                new_sentence_id = None
                if diff_item and change_type in ("deleted", "modified"):
                    for info in old_sentences_info.values():
                        if info["text"] == diff_item.old_text:
                            old_sentence_id = info["id"]
                            break
                if diff_item and change_type in ("added", "modified"):
                    for info in new_sentences_info.values():
                        if info["text"] == diff_item.new_text:
                            new_sentence_id = info["id"]
                            break

                db.add(
                    ComparisonRiskPoint(
                        id=_uuid(),
                        comparison_task_id=task_id,
                        change_type=change_type,
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
                        rule_snapshot_json=find_rule_snapshot(
                            rules_snapshot, rule_code
                        ),
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
                )
        except Exception as e:
            logger.error("[Comparison] Coze 增强失败 task_id=%s: %s", task_id, e)
            task.coze_enhanced = []
            task.total_risks = 0

    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.utcnow()


def recover_pending_comparison_tasks() -> int:
    """恢复服务重启前未完成的比对任务。"""
    db = SessionLocal()
    recovered = 0
    try:
        tasks = (
            db.query(ComparisonTask)
            .filter(
                ComparisonTask.status.in_([TaskStatus.PENDING, TaskStatus.PROCESSING])
            )
            .all()
        )
        for task in tasks:
            if not task.old_file_path or not task.new_file_path:
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.utcnow()
                task.sanitization_error = "任务文件路径为空，无法恢复"
                continue
            asyncio.create_task(
                asyncio.to_thread(
                    _process_comparison_task_background,
                    task.id,
                    task.user_id,
                    task.old_file_name,
                    task.new_file_name,
                    task.old_file_path,
                    task.new_file_path,
                    bool(task.enhance),
                    task.contract_type,
                )
            )
            recovered += 1
        db.commit()
    finally:
        db.close()
    return recovered


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
        "diff_details": _ensure_list(task.diff_details_json),
        "risk_points": [rp.to_dict() for rp in risk_points],
        "coze_enhanced": _ensure_list(task.coze_enhanced),
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


# --- 删除任务 ---


@contract_comparison_router.delete("/comparisons/{task_id}")
def delete_comparison_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """删除比对任务（级联删除文档、风险点、句子）。"""
    task = (
        db.query(ComparisonTask)
        .filter(
            ComparisonTask.id == task_id,
            ComparisonTask.user_id == current_user.id,
        )
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    db.delete(task)
    db.commit()
    return {"detail": "任务已删除"}
