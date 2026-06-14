"""规则逆向解析任务路由。"""

import csv
import io
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
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
from app.schemas.reverse_rule import ImportRequest
from app.schemas.reverse_rule import ImportResponse
from app.schemas.reverse_rule import TaskListResponse
from app.schemas.reverse_rule import TaskResponse
from app.services.document_parser import DocumentParser
from app.services.reverse_rule_task_service import import_candidates
from app.services.reverse_rule_task_service import process_task_async
from app.services.reverse_rule_task_service import run_reverse_rule_workflow

reverse_rule_router = APIRouter(prefix="/reverse-rule-tasks", tags=["规则逆向解析"])
reverse_rule_candidate_router = APIRouter(
    prefix="/reverse-rule-candidates", tags=["规则逆向解析"]
)


def _uuid() -> str:
    return str(uuid.uuid4())


def _get_user_task(db: Session, task_id: str, user_id: str) -> ReverseRuleTask:
    """获取用户的任务，校验所有权。"""
    import logging

    _log = logging.getLogger(__name__)
    # debug: count all
    all_count = db.query(ReverseRuleTask).count()
    _log.info("[ReverseRule] total tasks in DB: %d", all_count)
    task = (
        db.query(ReverseRuleTask)
        .filter(ReverseRuleTask.id == task_id, ReverseRuleTask.user_id == user_id)
        .first()
    )
    if not task:
        any_task = (
            db.query(ReverseRuleTask).filter(ReverseRuleTask.id == task_id).first()
        )
        _log.warning(
            "[ReverseRule] task=%s exists=%s req_user=%s db_user=%s total_tasks=%d",
            task_id,
            bool(any_task),
            user_id,
            any_task.user_id if any_task else "N/A",
            all_count,
        )
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


# --- 任务创建 ---


@reverse_rule_router.post("", response_model=TaskResponse)
async def create_reverse_rule_task(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskResponse:
    """创建逆向解析任务。支持 1-5 组修改前/后合同文件。"""
    form = await request.form()
    task_name = form.get("task_name", "逆向解析任务")
    contract_type = form.get("contract_type", "通用")
    review_role = form.get("review_role", "通用")

    # 解析 pairs[N][pair_name], pairs[N][before_file], pairs[N][after_file]
    pairs_by_index: dict[int, dict] = {}
    for key in form:
        if key.startswith("pairs["):
            # pairs[0][before_file] → idx=0, field=before_file
            rest = key[6:]  # remove "pairs["
            idx_str, field = rest.split("][", 1)
            idx = int(idx_str)
            field = field.rstrip("]")  # remove trailing "]"
            if idx not in pairs_by_index:
                pairs_by_index[idx] = {}
            pairs_by_index[idx][field] = form[key]

    contract_pairs = []
    for idx in sorted(pairs_by_index.keys()):
        entry = pairs_by_index[idx]
        pair_name = str(entry.get("pair_name", f"pair{idx + 1}"))
        before_file = entry.get("before_file")
        after_file = entry.get("after_file")
        if before_file is None or after_file is None:
            continue
        before_text = await _read_upload_text(before_file)
        after_text = await _read_upload_text(after_file)
        contract_pairs.append(
            {
                "pair_name": pair_name,
                "before_text": before_text,
                "after_text": after_text,
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
        status="parsing",
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
    """启动时将处于 parsing 的逆向解析任务标记为 failed。"""
    from sqlalchemy.orm import Session as _Session

    from app.models.database import ReverseRuleTask as _Task
    from app.models.database_connection import SessionLocal as _Local

    db: _Session = _Local()
    try:
        count = (
            db.query(_Task)
            .filter(_Task.status == "parsing")
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


@reverse_rule_router.get("", response_model=TaskListResponse)
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


@reverse_rule_router.get("/{task_id}", response_model=TaskResponse)
def get_reverse_rule_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskResponse:
    """查询逆向解析任务详情。"""
    task = _get_user_task(db, task_id, current_user.id)
    return TaskResponse.model_validate(task.to_dict())


# --- 候选规则列表 ---


@reverse_rule_router.get("/{task_id}/candidates", response_model=CandidateListResponse)
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
    "/{task_id}/candidates/decision", response_model=CandidateListResponse
)
def decide_candidates(
    task_id: str,
    request: DecideRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateListResponse:
    """批量设置候选规则决策状态。"""
    task = _get_user_task(db, task_id, current_user.id)

    if request.decision not in ("included", "ignored", "pending"):
        raise HTTPException(status_code=400, detail="无效的 decision 值")

    db.query(ReverseRuleCandidate).filter(
        ReverseRuleCandidate.task_id == task_id,
        ReverseRuleCandidate.id.in_(request.candidate_ids),
    ).update({"decision": request.decision}, synchronize_session=False)
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

    return CandidateListResponse(
        task=TaskResponse.model_validate(task.to_dict()),
        candidates=[
            CandidateRuleResponse.model_validate(c.to_dict()) for c in candidates
        ],
    )


# --- 确认入库 ---


@reverse_rule_router.post("/{task_id}/confirm-import", response_model=ImportResponse)
def import_to_rule_library(
    task_id: str,
    request: ImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ImportResponse:
    """将已纳入的候选规则写入正式规则库。"""
    _get_user_task(db, task_id, current_user.id)
    result = import_candidates(db, task_id, request.candidate_ids)
    return ImportResponse(
        task_id=task_id,
        included_count=result["imported"],
        ignored_count=result["ignored"],
        imported_rules=result["imported_rules"],
        ignored_rules=result["ignored_rules"],
        pair_count=result["pair_count"],
    )


# --- 重试 ---


@reverse_rule_router.post("/{task_id}/retry", response_model=TaskResponse)
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

    task.status = "parsing"
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


@reverse_rule_router.post("/{task_id}/export")
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


# --- 单条候选规则决策 ---


@reverse_rule_candidate_router.patch(
    "/{candidate_id}/decision", response_model=CandidateRuleResponse
)
def decide_single_candidate(
    candidate_id: str,
    request: DecideRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateRuleResponse:
    """设置单条候选规则决策状态。"""
    candidate = (
        db.query(ReverseRuleCandidate)
        .filter(ReverseRuleCandidate.id == candidate_id)
        .first()
    )
    if not candidate:
        raise HTTPException(status_code=404, detail="候选规则不存在")

    if request.decision not in ("included", "ignored", "pending"):
        raise HTTPException(status_code=400, detail="无效的 decision 值")

    candidate.decision = request.decision
    db.commit()

    return CandidateRuleResponse.model_validate(candidate.to_dict())


# --- 删除任务 ---


@reverse_rule_router.delete("/{task_id}")
def delete_reverse_rule_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """删除逆向解析任务（级联删除候选规则）。"""
    task = _get_user_task(db, task_id, current_user.id)
    db.delete(task)
    db.commit()
    return {"detail": "任务已删除"}


# --- 直接提取端点（无需任务管理） ---

reverse_rule_extract_router = APIRouter(prefix="/reverse-rule", tags=["规则逆向解析"])


@reverse_rule_extract_router.post("/extract")
def extract_reverse_rules(contract_pairs: list[dict]) -> dict:
    """直接提交合同对进行逆向规则提取。

    contract_pairs: [{"before_text": "...", "after_text": "...",
                       "contract_type": "...", "review_role": "..."}]
    返回: {"summary": "...", "rules": [...], "filtered_out": [...], "feedback_result": {...}}
    """
    if not 1 <= len(contract_pairs) <= 5:
        raise HTTPException(
            status_code=400, detail="contract_pairs 必须包含 1-5 组合同"
        )
    for pair in contract_pairs:
        if not pair.get("before_text") or not pair.get("after_text"):
            raise HTTPException(
                status_code=400, detail="before_text 和 after_text 不能为空"
            )

    try:
        return run_reverse_rule_workflow(contract_pairs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
