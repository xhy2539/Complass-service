"""规则逆向解析任务路由。"""

import csv
import io
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import File
from fastapi import HTTPException
from fastapi import UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.models.database import ReverseRuleCandidate
from app.models.database import ReverseRuleTask
from app.models.database import User
from app.models.database_connection import get_db
from app.schemas.reverse_rule import CandidateListResponse
from app.schemas.reverse_rule import CandidateRuleResponse
from app.schemas.reverse_rule import DecideRequest
from app.schemas.reverse_rule import DecideResponse
from app.schemas.reverse_rule import ImportRequest
from app.schemas.reverse_rule import ImportResponse
from app.schemas.reverse_rule import TaskListResponse
from app.schemas.reverse_rule import TaskResponse
from app.services.document_parser import DocumentParser
from app.services.reverse_rule_task_service import import_candidates
from app.services.reverse_rule_task_service import process_task_async

reverse_rule_router = APIRouter(prefix="/reverse-rule-tasks", tags=["规则逆向解析"])


def _uuid() -> str:
    return str(uuid.uuid4())


def _get_user_task(db: Session, task_id: str, user_id: str) -> ReverseRuleTask:
    """获取用户的任务，校验所有权。"""
    task = (
        db.query(ReverseRuleTask)
        .filter(ReverseRuleTask.id == task_id, ReverseRuleTask.user_id == user_id)
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


# --- 任务创建 ---


@reverse_rule_router.post("/tasks", response_model=TaskResponse)
async def create_reverse_rule_task(
    background_tasks: BackgroundTasks,
    task_name: str = "逆向解析任务",
    contract_type: Optional[str] = "通用",
    review_role: Optional[str] = "通用",
    pair1_before: UploadFile = File(...),
    pair1_after: UploadFile = File(...),
    pair2_before: UploadFile = File(None),
    pair2_after: UploadFile = File(None),
    pair3_before: UploadFile = File(None),
    pair3_after: UploadFile = File(None),
    pair4_before: UploadFile = File(None),
    pair4_after: UploadFile = File(None),
    pair5_before: UploadFile = File(None),
    pair5_after: UploadFile = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskResponse:
    """创建逆向解析任务。支持 1-5 组修改前/后合同文件。"""

    upload_pairs = [
        (pair1_before, pair1_after, "pair1"),
        (pair2_before, pair2_after, "pair2"),
        (pair3_before, pair3_after, "pair3"),
        (pair4_before, pair4_after, "pair4"),
        (pair5_before, pair5_after, "pair5"),
    ]

    contract_pairs = []
    for before, after, name in upload_pairs:
        if before is None or after is None:
            continue
        contract_pairs.append(
            {
                "pair_name": name,
                "before_text": await _read_upload_text(before),
                "after_text": await _read_upload_text(after),
            }
        )

    if len(contract_pairs) < 1:
        raise HTTPException(status_code=400, detail="请至少上传一组合同文件")

    task_id = _uuid()
    task = ReverseRuleTask(
        id=task_id,
        user_id=current_user.id,
        task_name=task_name,
        contract_type=contract_type,
        review_role=review_role,
        status="pending",
        contract_pairs_json=contract_pairs,
        progress=0,
    )
    db.add(task)
    db.commit()

    background_tasks.add_task(process_task_async, task_id)

    return TaskResponse.model_validate(task.to_dict())


async def _read_upload_text(file: UploadFile) -> str:
    content = await file.read()
    try:
        return DocumentParser.parse(content, file.filename or "file").text
    except Exception:
        return content.decode("utf-8", errors="replace")


def recover_pending_reverse_rule_tasks() -> int:
    """启动时将处于 processing 的逆向解析任务标记为 failed。"""
    from sqlalchemy.orm import Session as _Session

    from app.models.database import ReverseRuleTask as _Task
    from app.models.database_connection import SessionLocal as _Local

    db: _Session = _Local()
    try:
        count = (
            db.query(_Task)
            .filter(_Task.status == "processing")
            .update(
                {"status": "failed", "error_message": "服务重启，任务中断"},
                synchronize_session=False,
            )
        )
        db.commit()
        return count
    except Exception:
        db.rollback()
        return 0
    finally:
        db.close()


# --- 任务列表 ---


@reverse_rule_router.get("/tasks", response_model=TaskListResponse)
def list_reverse_rule_tasks(
    skip: int = 0,
    limit: int = 20,
    status: Optional[str] = None,
    contract_type: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskListResponse:
    """查询逆向解析任务列表。"""
    query = db.query(ReverseRuleTask).filter(ReverseRuleTask.user_id == current_user.id)
    if status:
        query = query.filter(ReverseRuleTask.status == status)
    if contract_type:
        query = query.filter(ReverseRuleTask.contract_type == contract_type)
    if created_from:
        query = query.filter(
            ReverseRuleTask.created_at >= datetime.fromisoformat(created_from)
        )
    if created_to:
        query = query.filter(
            ReverseRuleTask.created_at <= datetime.fromisoformat(created_to)
        )

    total = query.count()
    tasks = (
        query.order_by(ReverseRuleTask.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return TaskListResponse(
        tasks=[TaskResponse.model_validate(t.to_dict()) for t in tasks],
        total=total,
        skip=skip,
        limit=limit,
    )


# --- 任务详情 ---


@reverse_rule_router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_reverse_rule_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskResponse:
    """查询逆向解析任务详情。"""
    task = _get_user_task(db, task_id, current_user.id)
    return TaskResponse.model_validate(task.to_dict())


# --- 候选规则列表 ---


@reverse_rule_router.get(
    "/tasks/{task_id}/candidates", response_model=CandidateListResponse
)
def list_candidates(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateListResponse:
    """查询任务的候选规则。"""
    task = _get_user_task(db, task_id, current_user.id)

    candidates = (
        db.query(ReverseRuleCandidate)
        .filter(ReverseRuleCandidate.task_id == task_id)
        .all()
    )

    return CandidateListResponse(
        task=TaskResponse.model_validate(task.to_dict()),
        candidates=[
            CandidateRuleResponse.model_validate(c.to_dict()) for c in candidates
        ],
    )


# --- 候选规则决策 ---


@reverse_rule_router.patch(
    "/tasks/{task_id}/candidates/decide", response_model=DecideResponse
)
def decide_candidates(
    task_id: str,
    request: DecideRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DecideResponse:
    """批量设置候选规则决策状态。"""
    task = _get_user_task(db, task_id, current_user.id)

    if request.decision not in ("included", "ignored", "pending"):
        raise HTTPException(status_code=400, detail="无效的 decision 值")

    updated = (
        db.query(ReverseRuleCandidate)
        .filter(
            ReverseRuleCandidate.task_id == task_id,
            ReverseRuleCandidate.id.in_(request.candidate_ids),
        )
        .update({"decision": request.decision}, synchronize_session=False)
    )
    db.commit()

    # 刷新任务统计
    candidates = (
        db.query(ReverseRuleCandidate)
        .filter(ReverseRuleCandidate.task_id == task_id)
        .all()
    )
    task.stats_json = {
        "total": len(candidates),
        "included": sum(1 for c in candidates if c.decision == "included"),
        "ignored": sum(1 for c in candidates if c.decision == "ignored"),
        "pending": sum(1 for c in candidates if c.decision == "pending"),
    }
    db.commit()

    return DecideResponse(updated=updated, decision=request.decision)


# --- 确认入库 ---


@reverse_rule_router.post("/tasks/{task_id}/import", response_model=ImportResponse)
def import_to_rule_library(
    task_id: str,
    request: ImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ImportResponse:
    """将已纳入的候选规则写入正式规则库。"""
    _get_user_task(db, task_id, current_user.id)
    result = import_candidates(db, task_id, request.candidate_ids)
    return ImportResponse(**result)


# --- 重试 ---


@reverse_rule_router.post("/tasks/{task_id}/retry", response_model=TaskResponse)
def retry_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskResponse:
    """重试失败的任务。"""
    task = _get_user_task(db, task_id, current_user.id)
    if task.status != "failed":
        raise HTTPException(status_code=400, detail="只能重试失败的任务")

    task.status = "pending"
    task.progress = 0
    task.error_message = None
    db.commit()

    background_tasks.add_task(process_task_async, task_id)
    return TaskResponse.model_validate(task.to_dict())


# --- 导出 ---


_EXPORT_HEADERS = [
    "decision",
    "contract_type",
    "review_module",
    "risk_name",
    "check_point",
    "trigger_condition",
    "default_risk_level",
    "suggestion_template",
    "example_clause",
    "review_perspective",
    "confidence",
    "source_pair_index",
]


@reverse_rule_router.get("/tasks/{task_id}/export")
def export_candidates(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """导出候选规则为 CSV 文件（UTF-8 BOM）。"""
    _get_user_task(db, task_id, current_user.id)

    candidates = (
        db.query(ReverseRuleCandidate)
        .filter(ReverseRuleCandidate.task_id == task_id)
        .all()
    )

    buf = io.StringIO()
    buf.write("﻿")  # UTF-8 BOM for Excel
    writer = csv.DictWriter(buf, fieldnames=_EXPORT_HEADERS, extrasaction="ignore")
    writer.writeheader()
    for c in candidates:
        writer.writerow(
            {
                "decision": c.decision,
                "contract_type": c.contract_type,
                "review_module": c.review_module,
                "risk_name": c.risk_name,
                "check_point": c.check_point,
                "trigger_condition": c.trigger_condition,
                "default_risk_level": c.default_risk_level,
                "suggestion_template": c.suggestion_template,
                "example_clause": c.example_clause,
                "review_perspective": c.review_perspective,
                "confidence": c.confidence,
                "source_pair_index": c.source_pair_index,
            }
        )

    buf.seek(0)
    filename = f"reverse_rules_{task_id[:8]}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
