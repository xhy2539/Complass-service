"""合同优化版本路由，处理建议采纳、版本查询和导出。"""

from urllib.parse import quote

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload

from app.api.v1.auth import get_current_user
from app.models.database import OptimizedContractVersion
from app.models.database import ReviewTask
from app.models.database import RiskPoint
from app.models.database import User
from app.models.database_connection import get_db
from app.schemas.optimization import ApplySuggestionsRequest
from app.schemas.optimization import ApplySuggestionsResponse
from app.schemas.optimization import OptimizedContractVersionResponse
from app.services.contract_optimization_service import create_optimized_version
from app.services.document_exporter import DocumentExporter

optimization_router = APIRouter(tags=["合同优化"])


@optimization_router.post(
    "/reviews/{task_id}/suggestions/apply", response_model=ApplySuggestionsResponse
)
async def apply_review_suggestions(
    task_id: str,
    request: ApplySuggestionsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplySuggestionsResponse:
    """采纳风险建议并生成优化后合同版本。"""
    task = _get_owned_review_task(db, task_id, current_user.id)
    risk_points = (
        db.query(RiskPoint)
        .options(joinedload(RiskPoint.sentence))
        .filter(
            RiskPoint.id.in_(request.risk_ids),
            RiskPoint.review_task_id == task_id,
        )
        .all()
    )

    if len(risk_points) != len(set(request.risk_ids)):
        raise HTTPException(status_code=400, detail="存在不属于该任务的风险点")

    try:
        version = create_optimized_version(
            db, task, risk_points, current_user.id, request.title
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    return ApplySuggestionsResponse(
        success=True,
        version=OptimizedContractVersionResponse.model_validate(version.to_dict()),
    )


@optimization_router.get(
    "/reviews/{task_id}/optimized-versions",
    response_model=list[OptimizedContractVersionResponse],
)
async def list_optimized_versions(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[OptimizedContractVersionResponse]:
    """查询指定审查任务的优化合同版本列表。"""
    _get_owned_review_task(db, task_id, current_user.id)
    versions = (
        db.query(OptimizedContractVersion)
        .filter(OptimizedContractVersion.review_task_id == task_id)
        .order_by(OptimizedContractVersion.version_no.desc())
        .all()
    )
    return [
        OptimizedContractVersionResponse.model_validate(version.to_dict())
        for version in versions
    ]


@optimization_router.get(
    "/reviews/{task_id}/optimized-versions/{version_id}",
    response_model=OptimizedContractVersionResponse,
)
async def get_optimized_version(
    task_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OptimizedContractVersionResponse:
    """查询优化合同版本详情。"""
    _get_owned_review_task(db, task_id, current_user.id)
    version = _get_optimized_version(db, task_id, version_id)
    return OptimizedContractVersionResponse.model_validate(version.to_dict())


@optimization_router.post("/reviews/{task_id}/optimized-versions/{version_id}/export")
async def export_optimized_version(
    task_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """导出指定优化合同版本为 docx。"""
    _get_owned_review_task(db, task_id, current_user.id)
    version = _get_optimized_version(db, task_id, version_id)

    file_name = f"{version.title}.docx"
    docx_buffer = DocumentExporter.export_text_to_docx(
        text=version.text,
        file_name=file_name,
        title=version.title,
    )
    encoded_filename = quote(file_name)
    return StreamingResponse(
        docx_buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        },
    )


def _get_owned_review_task(db: Session, task_id: str, user_id: str) -> ReviewTask:
    """查询当前用户拥有的审查任务。"""
    task = (
        db.query(ReviewTask)
        .filter(
            ReviewTask.id == task_id,
            ReviewTask.user_id == user_id,
        )
        .first()
    )
    if not task:
        raise HTTPException(
            status_code=404, detail=f"审查任务 {task_id} 不存在或无权访问"
        )
    return task


def _get_optimized_version(
    db: Session, task_id: str, version_id: str
) -> OptimizedContractVersion:
    """查询优化合同版本。"""
    version = (
        db.query(OptimizedContractVersion)
        .filter(
            OptimizedContractVersion.id == version_id,
            OptimizedContractVersion.review_task_id == task_id,
        )
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="优化合同版本不存在")
    return version
