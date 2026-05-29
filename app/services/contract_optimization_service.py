"""合同优化版本生成服务。"""

import uuid
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.database import AcceptedSuggestion
from app.models.database import OptimizedContractVersion
from app.models.database import ReviewTask
from app.models.database import RiskPoint


def build_replacements(risk_points: list[Any]) -> list[dict]:
    """从风险点构造替换项。"""
    replacements: list[dict] = []
    for risk in risk_points:
        replace_text = getattr(risk, "replace_text", None)
        if not replace_text:
            continue

        position = getattr(risk, "position", None) or {}
        start = position.get("char_offset_start")
        end = position.get("char_offset_end")
        original_text = position.get("original_text") or getattr(risk, "evidence", None)

        sentence = getattr(risk, "sentence", None)
        if (start is None or end is None) and sentence is not None:
            start = getattr(sentence, "char_offset_start", None)
            end = getattr(sentence, "char_offset_end", None)
            original_text = getattr(sentence, "text", None)
            position = {"char_offset_start": start, "char_offset_end": end}

        if start is None or end is None:
            continue

        replacements.append(
            {
                "risk_id": risk.id,
                "start": int(start),
                "end": int(end),
                "original_text": original_text,
                "replace_text": replace_text,
                "position": position,
            }
        )

    validate_replacements(replacements)
    return replacements


def validate_replacements(replacements: list[dict]) -> None:
    """校验替换区间是否重叠。"""
    sorted_items = sorted(replacements, key=lambda item: item["start"])
    previous_end: int | None = None
    for item in sorted_items:
        start = item["start"]
        end = item["end"]
        if start < 0 or end < start:
            raise ValueError("采纳建议存在无效替换区间")
        if previous_end is not None and start < previous_end:
            raise ValueError("采纳建议存在重叠替换区间")
        previous_end = end


def apply_replacements(original_text: str, replacements: list[dict]) -> str:
    """按位置从后往前替换合同文本。"""
    validate_replacements(replacements)
    result = original_text
    for item in sorted(replacements, key=lambda value: value["start"], reverse=True):
        result = result[: item["start"]] + item["replace_text"] + result[item["end"] :]
    return result


def create_optimized_version(
    db: Session,
    review_task: ReviewTask,
    risk_points: list[RiskPoint],
    user_id: str,
    title: str | None,
) -> OptimizedContractVersion:
    """生成并保存优化后合同版本。"""
    replacements = build_replacements(risk_points)
    if not replacements:
        raise ValueError("没有可采纳的替换建议")

    optimized_text = apply_replacements(review_task.text or "", replacements)
    max_version_no = (
        db.query(func.max(OptimizedContractVersion.version_no))
        .filter(OptimizedContractVersion.review_task_id == review_task.id)
        .scalar()
        or 0
    )

    version = OptimizedContractVersion(
        id=_uuid(),
        review_task_id=review_task.id,
        version_no=max_version_no + 1,
        title=title or f"{review_task.file_name}_优化版_v{max_version_no + 1}",
        text=optimized_text,
        accepted_risk_ids_json=[item["risk_id"] for item in replacements],
        created_by_user_id=user_id,
    )
    db.add(version)
    db.flush()

    for item in replacements:
        db.add(
            AcceptedSuggestion(
                id=_uuid(),
                optimized_version_id=version.id,
                risk_point_id=item["risk_id"],
                original_text=item.get("original_text"),
                replace_text=item["replace_text"],
                position=item.get("position"),
            )
        )

    db.flush()
    return version


def _uuid() -> str:
    """生成 UUID。"""
    return str(uuid.uuid4())
