"""合同版本比对路由，支持双文件上传、任务创建、diff 计算和 Coze 语义增强。"""

import uuid
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.models.database import (
    ComparisonTask, ComparisonRiskPoint, TaskStatus, RiskLevel, RiskStatus, User
)
from app.models.database_connection import get_db
from app.services.document_parser import DocumentParseError, DocumentParser
from app.services.text_diff import sentence_diff_with_positions, summarize_diff
from app.services.coze_service import CozeServiceError, get_coze_service

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
            detail=f"不支持的文件格式，仅支持: {', '.join(DocumentParser.SUPPORTED_EXTENSIONS)}"
        )


@contract_comparison_router.post("/comparisons", response_model=dict)
async def create_comparison_task(
    old_file: Annotated[UploadFile, File(description="旧版本合同")],
    new_file: Annotated[UploadFile, File(description="新版本合同")],
    enhance: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> dict:
    """
    创建版本比对任务。

    流程：上传两个文件 → 创建任务 → 解析 → diff → Coze增强（如启用）→ 保存结果
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
        old_sanitized_text=old_doc.sanitized_text,
        new_sanitized_text=new_doc.sanitized_text,
        status=TaskStatus.PROCESSING
    )

    db.add(task)

    # 构建旧文档比对数据
    old_comparison_data = {
        "sentences": [
            {
                "index": idx,
                "text": s["text"],
                "char_offset_start": s["char_offset_start"],
                "char_offset_end": s["char_offset_end"],
                "paragraph_index": s["paragraph_index"]
            }
            for idx, s in enumerate(old_doc.sentences)
        ],
        "key_clauses": [p for p in old_doc.paragraphs if p.is_key_clause]
    }

    # 构建新文档比对数据
    new_comparison_data = {
        "sentences": [
            {
                "index": idx,
                "text": s["text"],
                "char_offset_start": s["char_offset_start"],
                "char_offset_end": s["char_offset_end"],
                "paragraph_index": s["paragraph_index"]
            }
            for idx, s in enumerate(new_doc.sentences)
        ],
        "key_clauses": [p for p in new_doc.paragraphs if p.is_key_clause]
    }

    # 使用带位置的句子级 diff
    diffs = sentence_diff_with_positions(old_comparison_data, new_comparison_data)
    summary = summarize_diff(diffs)

    # 保存 diff 结果
    task.diff_stats = {
        "total": summary["total"],
        "added": summary["added"],
        "deleted": summary["deleted"],
        "modified": summary["modified"]
    }
    task.diff_details_json = [
        {
            "index": d.index,
            "change_type": d.change_type,
            "old_text": d.old_text,
            "new_text": d.new_text,
            "similarity": round(d.similarity, 2),
            "old_position": d.old_position,
            "new_position": d.new_position
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
                "is_key_clause": p.is_key_clause
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
                "is_key_clause": p.is_key_clause
            }
            for p in new_doc.paragraphs
        ]
    }

    # Coze 语义增强
    if enhance:
        try:
            coze_service = get_coze_service()
            coze_result = await coze_service.enhance_diff_result({
                "old_text": old_doc.sanitized_text,
                "new_text": new_doc.sanitized_text,
                **summary
            })

            task.coze_enhanced = coze_result.get("enhanced", [])
            task.total_risks = coze_result.get("total_risks", 0)
            coze_stats = coze_result.get("stats") or {}
            if coze_stats:
                task.diff_stats = {
                    "total": sum(coze_stats.values()),
                    "added": coze_stats.get("added", 0),
                    "deleted": coze_stats.get("deleted", 0),
                    "modified": coze_stats.get("modified", 0)
                }

            # 创建比对风险点
            for enhanced in coze_result.get("enhanced", []):
                # 找到对应的 diff 项
                diff_index = None
                for d in diffs:
                    if d.change_type == enhanced.get("change_type"):
                        if enhanced.get("original") in (d.old_text or "") or enhanced.get("original") in (d.new_text or ""):
                            diff_index = d.index
                            break

                risk_point = ComparisonRiskPoint(
                    id=_uuid(),
                    comparison_task_id=task_id,
                    change_type=enhanced.get("change_type", "modified"),
                    old_text=diffs[diff_index].old_text if diff_index is not None else enhanced.get("old"),
                    new_text=diffs[diff_index].new_text if diff_index is not None else enhanced.get("new") or enhanced.get("original"),
                    similarity=int(diffs[diff_index].similarity * 100) if diff_index is not None else 0,
                    summary=enhanced.get("summary", ""),
                    risk_level=RiskLevel(enhanced.get("risk_level", "low")),
                    category=enhanced.get("category"),
                    evidence=enhanced.get("evidence"),
                    impact=enhanced.get("impact"),
                    suggestion=enhanced.get("suggestion", ""),
                    old_position=diffs[diff_index].old_position if diff_index is not None else None,
                    new_position=diffs[diff_index].new_position if diff_index is not None else None,
                    source="coze"
                )
                db.add(risk_point)

        except CozeServiceError as e:
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
            "paragraph_count": len(old_doc.paragraphs)
        },
        "new_file": {
            "name": new_doc.file_name,
            "type": new_doc.file_type,
            "char_count": new_doc.char_count,
            "page_count": new_doc.page_count,
            "paragraph_count": len(new_doc.paragraphs)
        },
        "diff_stats": task.diff_stats
    }


@contract_comparison_router.get("/comparisons/{task_id}")
async def get_comparison_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> dict:
    """查询版本比对任务详情，包括差异列表和风险点。"""
    task = db.query(ComparisonTask).filter(
        ComparisonTask.id == task_id,
        ComparisonTask.user_id == current_user.id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail=f"比对任务 {task_id} 不存在或无权访问")

    # 获取风险点
    risk_points = db.query(ComparisonRiskPoint).filter(
        ComparisonRiskPoint.comparison_task_id == task_id
    ).all()

    return {
        "success": True,
        "task": task.to_dict(),
        "diff_details": task.diff_details_json,
        "risk_points": [rp.to_dict() for rp in risk_points],
        "coze_enhanced": task.coze_enhanced,
        "message": "查询成功"
    }


@contract_comparison_router.get("/comparisons")
async def list_comparison_tasks(
    skip: int = 0,
    limit: int = 20,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> dict:
    """查询当前用户的版本比对任务列表（支持分页和状态筛选）。"""
    query = db.query(ComparisonTask).filter(ComparisonTask.user_id == current_user.id)

    if status:
        try:
            status_enum = TaskStatus(status)
            query = query.filter(ComparisonTask.status == status_enum)
        except ValueError:
            pass

    tasks = query.order_by(ComparisonTask.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "success": True,
        "tasks": [t.to_dict() for t in tasks],
        "total": len(tasks)
    }
