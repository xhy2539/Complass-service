"""规则逆向解析任务服务。"""

import logging

from sqlalchemy.orm import Session

from app.models.database import ReverseRuleCandidate
from app.models.database import ReverseRuleTask
from app.models.database import ReviewRule
from app.models.database_connection import SessionLocal

logger = logging.getLogger(__name__)


def run_reverse_rule_workflow(contract_pairs: list[dict]) -> dict:
    """调用 reverse_rule_workflow 子项目的核心流程。"""
    import sys

    _rw_path = "/reverse_rule_workflow"
    if _rw_path not in sys.path:
        sys.path.insert(0, _rw_path)
    from reverse_rule_workflow.app.chains.reverse_rule_graph import (
        run_reverse_rule_extraction,
    )

    return run_reverse_rule_extraction(contract_pairs)


def process_task_async(task_id: str) -> None:
    """在后台执行逆向解析任务。"""
    db = SessionLocal()
    try:
        task = db.query(ReverseRuleTask).filter(ReverseRuleTask.id == task_id).first()
        if not task:
            return

        task.status = "processing"
        task.progress = 10
        db.commit()

        pairs = task.contract_pairs_json or []
        if not pairs:
            task.status = "failed"
            task.error_message = "没有合同数据"
            db.commit()
            return

        inputs = [
            {
                "pair_id": p.get("pair_name", f"pair_{i}"),
                "before_text": p["before_text"],
                "after_text": p["after_text"],
                "contract_type": task.contract_type,
                "review_role": task.review_role,
            }
            for i, p in enumerate(pairs)
        ]

        task.progress = 30
        db.commit()

        result = run_reverse_rule_workflow(inputs)

        # 保存原始结果
        task.result_json = result
        task.progress = 80
        db.commit()

        # 写入候选规则
        rules = result.get("rules", [])
        stats = {
            "total": len(rules),
            "included": 0,
            "ignored": 0,
            "pending": len(rules),
        }
        for i, rule in enumerate(rules):
            candidate = ReverseRuleCandidate(
                id=_uuid(),
                task_id=task_id,
                contract_type=rule.get("contract_type", "通用"),
                review_module=rule.get("review_module", ""),
                risk_name=rule.get("risk_name", "")[:100],
                check_point=rule.get("check_point", ""),
                trigger_condition=rule.get("trigger_condition", ""),
                default_risk_level=rule.get("default_risk_level", "中"),
                suggestion_template=rule.get("suggestion_template", ""),
                example_clause=rule.get("example_clause", ""),
                review_perspective=rule.get("review_perspective", "通用"),
                traces_json=rule.get("traces", []),
                source_pair_index=i,
                decision="pending",
                confidence=rule.get("confidence"),
            )
            db.add(candidate)

        task.status = "completed"
        task.progress = 100
        task.stats_json = stats
        db.commit()

        logger.info(
            "[ReverseRule] 任务 %s 完成，生成 %d 条候选规则", task_id, len(rules)
        )

    except Exception as e:
        db.rollback()
        task = db.query(ReverseRuleTask).filter(ReverseRuleTask.id == task_id).first()
        if task:
            task.status = "failed"
            task.error_message = str(e)
            db.commit()
        logger.exception("[ReverseRule] 任务 %s 失败", task_id)
    finally:
        db.close()


def import_candidates(db: Session, task_id: str, candidate_ids: list[str]) -> dict:
    """将已纳入的候选规则写入正式规则库。"""
    candidates = (
        db.query(ReverseRuleCandidate)
        .filter(
            ReverseRuleCandidate.task_id == task_id,
            ReverseRuleCandidate.id.in_(candidate_ids),
            ReverseRuleCandidate.decision == "included",
        )
        .all()
    )

    imported = []
    for c in candidates:
        rule = ReviewRule(
            id=_uuid(),
            rule_code=_generate_rule_code(c),
            contract_type=c.contract_type,
            review_module=c.review_module,
            risk_name=c.risk_name,
            check_point=c.check_point,
            trigger_condition=c.trigger_condition,
            default_risk_level=c.default_risk_level,
            suggestion_template=c.suggestion_template,
            example_clause=c.example_clause,
            review_perspective=c.review_perspective,
            enabled=True,
        )
        db.add(rule)
        db.flush()
        c.imported_rule_id = rule.id
        imported.append(rule.to_dict())

    # 更新任务统计
    task = db.query(ReverseRuleTask).filter(ReverseRuleTask.id == task_id).first()
    if task and task.stats_json:
        task.stats_json = {**task.stats_json, "imported_included": len(imported)}

    db.commit()
    return {"imported": len(imported), "imported_rules": imported}


def _generate_rule_code(candidate: ReverseRuleCandidate) -> str:
    """生成规则编号。"""
    prefix_map = {"财务": "REV-FIN", "法务": "REV-LAW", "履约": "REV-PER"}
    prefix = prefix_map.get(candidate.review_module, "REV-OTH")
    return f"{prefix}-{_uuid()[:8]}"


def _uuid() -> str:
    import uuid as _uuid_mod

    return str(_uuid_mod.uuid4())
