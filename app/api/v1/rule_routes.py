"""规则库管理路由，提供规则 CRUD、版本和 CSV 导入能力。"""

from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import HTTPException
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.models.database import User
from app.models.database_connection import get_db
from app.schemas.rule import CsvImportResponse
from app.schemas.rule import RuleCreateRequest
from app.schemas.rule import RuleEnabledRequest
from app.schemas.rule import RuleListResponse
from app.schemas.rule import RuleResponse
from app.schemas.rule import RuleUpdateRequest
from app.schemas.rule import RuleVersionCreateRequest
from app.schemas.rule import RuleVersionResponse
from app.services.rule_importer import parse_rules_csv
from app.services.rule_service import activate_rule_version
from app.services.rule_service import create_rule
from app.services.rule_service import create_rule_version
from app.services.rule_service import delete_rule
from app.services.rule_service import get_active_rule_version
from app.services.rule_service import list_rule_versions
from app.services.rule_service import list_rules
from app.services.rule_service import update_rule

rule_router = APIRouter(tags=["规则库管理"])


@rule_router.get("/rules", response_model=RuleListResponse)
async def get_rules(
    skip: int = 0,
    limit: int = 100,
    version_id: Optional[str] = None,
    contract_type: Optional[str] = None,
    enabled: Optional[bool] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RuleListResponse:
    """查询规则列表。"""
    rules, total = list_rules(db, version_id, contract_type, enabled, skip, limit)
    return RuleListResponse(
        rules=[RuleResponse.model_validate(rule.to_dict()) for rule in rules],
        total=total,
        skip=skip,
        limit=limit,
    )


@rule_router.post("/rules", response_model=RuleResponse)
async def add_rule(
    request: RuleCreateRequest,
    version_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RuleResponse:
    """创建规则。"""
    target_version_id = version_id
    if not target_version_id:
        active_version = get_active_rule_version(db)
        if not active_version:
            raise HTTPException(status_code=400, detail="当前没有激活的规则版本")
        target_version_id = active_version.id

    try:
        rule = create_rule(db, target_version_id, request.model_dump())
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    return RuleResponse.model_validate(rule.to_dict())


@rule_router.patch("/rules/{rule_id}", response_model=RuleResponse)
async def edit_rule(
    rule_id: str,
    request: RuleUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RuleResponse:
    """编辑规则。"""
    try:
        rule = update_rule(db, rule_id, request.model_dump(exclude_unset=True))
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return RuleResponse.model_validate(rule.to_dict())


@rule_router.delete("/rules/{rule_id}")
async def remove_rule(
    rule_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """删除规则。"""
    try:
        delete_rule(db, rule_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    return {"success": True, "message": "规则已删除"}


@rule_router.patch("/rules/{rule_id}/enabled", response_model=RuleResponse)
async def set_rule_enabled(
    rule_id: str,
    request: RuleEnabledRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RuleResponse:
    """启用或停用规则。"""
    try:
        rule = update_rule(db, rule_id, {"enabled": request.enabled})
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return RuleResponse.model_validate(rule.to_dict())


@rule_router.post("/rules/import-csv", response_model=CsvImportResponse)
async def import_rules_csv(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CsvImportResponse:
    """导入规则 CSV 并创建草稿版本。"""
    content = await file.read()
    rules, errors = parse_rules_csv(content)
    if errors:
        return CsvImportResponse(success=False, imported_count=0, errors=errors)

    try:
        version = create_rule_version(
            db,
            name=file.filename or "CSV 导入规则版本",
            description="CSV 导入",
            user_id=current_user.id,
        )
        for rule_data in rules:
            create_rule(db, version.id, rule_data | {"enabled": True})
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    return CsvImportResponse(
        success=True,
        version_id=version.id,
        version_no=version.version_no,
        imported_count=len(rules),
        errors=[],
    )


@rule_router.get("/rule-versions", response_model=list[RuleVersionResponse])
async def get_rule_versions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RuleVersionResponse]:
    """查询规则版本列表。"""
    return [
        RuleVersionResponse.model_validate(version.to_dict())
        for version in list_rule_versions(db)
    ]


@rule_router.post("/rule-versions", response_model=RuleVersionResponse)
async def add_rule_version(
    request: RuleVersionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RuleVersionResponse:
    """创建规则版本。"""
    version = create_rule_version(
        db, request.name, request.description, current_user.id
    )
    db.commit()
    return RuleVersionResponse.model_validate(version.to_dict())


@rule_router.post(
    "/rule-versions/{version_id}/activate", response_model=RuleVersionResponse
)
async def activate_version(
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RuleVersionResponse:
    """激活规则版本。"""
    try:
        version = activate_rule_version(db, version_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    return RuleVersionResponse.model_validate(version.to_dict())
