"""风险点人工确认路由，处理风险状态更新和查询。"""

from datetime import datetime
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.models.database import (
    RiskPoint, RiskStatus, ComparisonRiskPoint, User, ReviewTask, ComparisonTask
)
from app.models.database_connection import get_db
from app.schemas.review import (
    RiskStatusUpdateRequest,
    RiskStatusUpdateResponse,
    RiskListResponse,
    RiskPointSchema,
    RiskStatsSchema
)

risk_manual_decision_router = APIRouter(prefix="/risks", tags=["风险点人工确认"])


def _uuid() -> str:
    """生成 UUID。"""
    return str(uuid.uuid4())


def _get_task_user_id(risk_point, db: Session) -> Optional[str]:
    """获取风险点关联的任务的用户ID。"""
    if isinstance(risk_point, RiskPoint):
        task = db.query(ReviewTask).filter(ReviewTask.id == risk_point.review_task_id).first()
        return task.user_id if task else None
    elif isinstance(risk_point, ComparisonRiskPoint):
        task = db.query(ComparisonTask).filter(ComparisonTask.id == risk_point.comparison_task_id).first()
        return task.user_id if task else None
    return None


@risk_manual_decision_router.patch("/{risk_id}/status", response_model=RiskStatusUpdateResponse)
async def update_risk_status(
    risk_id: str,
    request: RiskStatusUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> RiskStatusUpdateResponse:
    """
    更新风险点状态。

    - risk_id: 风险点 ID
    - status: 新状态 (pending/confirmed/ignored)
    - ignore_reason: 忽略原因（当 status=ignored 时）
    """
    # 查找风险点（可能来自审查任务或比对任务）
    risk_point = db.query(RiskPoint).filter(RiskPoint.id == risk_id).first()
    is_comparison_risk = False

    if not risk_point:
        # 可能在比对任务中
        risk_point = db.query(ComparisonRiskPoint).filter(ComparisonRiskPoint.id == risk_id).first()
        is_comparison_risk = True

    if not risk_point:
        raise HTTPException(status_code=404, detail=f"风险点 {risk_id} 不存在")

    # 验证用户权限（必须是任务所有者）
    task_user_id = _get_task_user_id(risk_point, db)
    if task_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作此风险点")

    # 验证状态值
    try:
        new_status = RiskStatus(request.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的状态值: {request.status}，必须是 pending/confirmed/ignored")

    old_status = risk_point.status.value if risk_point.status else "pending"

    # 更新状态
    risk_point.status = new_status
    risk_point.updated_at = datetime.utcnow()

    if new_status == RiskStatus.CONFIRMED:
        risk_point.confirmed_at = datetime.utcnow()
        risk_point.confirmed_by_user_id = current_user.id
    elif new_status == RiskStatus.IGNORED:
        risk_point.ignore_reason = request.ignore_reason

    # 支持人工复核备注
    if request.review_comment:
        risk_point.review_comment = request.review_comment

    db.commit()

    return RiskStatusUpdateResponse(
        risk_id=risk_id,
        old_status=old_status,
        new_status=request.status,
        message=f"状态已更新为 {request.status}"
    )


@risk_manual_decision_router.get("/{risk_id}", response_model=RiskPointSchema)
async def get_risk_point(
    risk_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> RiskPointSchema:
    """获取单个风险点详情。"""
    risk_point = db.query(RiskPoint).filter(RiskPoint.id == risk_id).first()

    if not risk_point:
        risk_point = db.query(ComparisonRiskPoint).filter(ComparisonRiskPoint.id == risk_id).first()

    if not risk_point:
        raise HTTPException(status_code=404, detail=f"风险点 {risk_id} 不存在")

    # 验证用户权限
    task_user_id = _get_task_user_id(risk_point, db)
    if task_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此风险点")

    return RiskPointSchema.model_validate(risk_point.to_dict())