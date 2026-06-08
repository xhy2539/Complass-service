"""规则逆向解析任务服务。"""

import logging

from sqlalchemy.orm import Session

from app.models.database import ReverseRuleCandidate
from app.models.database import ReverseRuleTask
from app.models.database import ReviewRule
from app.models.database_connection import SessionLocal
from app.services.sanitization_service import restore_text_from_mapping
from app.services.sanitization_service import sanitize_contract_text

logger = logging.getLogger(__name__)


def run_reverse_rule_workflow(contract_pairs: list[dict]) -> dict:
    """调用 reverse_rule_workflow 子项目的核心流程。"""
    import sys

    _rw_path = "/rw_src"
    if _rw_path not in sys.path:
        sys.path.insert(0, _rw_path)
    from rw.chains.reverse_rule_graph import run_reverse_rule_extraction

    return run_reverse_rule_extraction(contract_pairs)


def process_task_async(task_id: str) -> None:
    """在后台执行逆向解析任务。"""
    db = SessionLocal()
    try:
        task = db.query(ReverseRuleTask).filter(ReverseRuleTask.id == task_id).first()
        if not task:
            return

        task.status = "parsing"
        task.progress = 10
        db.commit()

        pairs = task.contract_pairs_json or []
        if not pairs:
            task.status = "failed"
            task.error_message = "没有合同数据"
            db.commit()
            return

        # 脱敏：替换公司名、电话、邮箱等敏感信息
        all_mappings: list[dict] = []
        sanitized_pairs = []
        for p in pairs:
            before_san = sanitize_contract_text(p["before_text"])
            after_san = sanitize_contract_text(p["after_text"])
            all_mappings.extend(before_san.mappings)
            all_mappings.extend(after_san.mappings)
            sanitized_pairs.append(
                {
                    "pair_name": p.get("pair_name", ""),
                    "before_text": before_san.sanitized_text,
                    "after_text": after_san.sanitized_text,
                }
            )
        task.sanitization_mapping_json = all_mappings
        db.commit()

        inputs = [
            {
                "pair_id": p["pair_name"],
                "before_text": p["before_text"],
                "after_text": p["after_text"],
                "contract_type": task.contract_type,
                "review_role": task.review_role,
            }
            for p in sanitized_pairs
        ]

        task.progress = 30
        db.commit()

        result = run_reverse_rule_workflow(inputs)

        # 保存原始结果
        task.result_json = result
        task.progress = 80
        db.commit()

        # 写入候选规则（还原脱敏证据文本）
        rules = result.get("rules", [])
        stats = {
            "total": len(rules),
            "included": 0,
            "ignored": 0,
            "pending": len(rules),
        }
        pair_name_to_index: dict[str, int] = {}
        for idx, p in enumerate(pairs):
            pair_name_to_index[p.get("pair_name", f"pair_{idx}")] = idx

        for rule in rules:
            traces = rule.get("traces", [])
            for trace in traces:
                if trace.get("evidence_before"):
                    trace["evidence_before"] = restore_text_from_mapping(
                        trace["evidence_before"], all_mappings
                    )
                if trace.get("evidence_after"):
                    trace["evidence_after"] = restore_text_from_mapping(
                        trace["evidence_after"], all_mappings
                    )
            # 从 traces 中提取来源合同组序号
            source_index = pair_name_to_index.get(
                traces[0].get("pair_id", "") if traces else "",
                0,
            )
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
                example_clause=restore_text_from_mapping(
                    rule.get("example_clause", ""), all_mappings
                ),
                review_perspective=rule.get("review_perspective", "通用"),
                traces_json=traces,
                source_pair_index=source_index,
                decision="pending",
                confidence=rule.get("confidence"),
            )
            db.add(candidate)

        task.status = "pending_confirm"
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
    ignored_rules = []
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

    if candidate_ids:
        all_requested = (
            db.query(ReverseRuleCandidate)
            .filter(ReverseRuleCandidate.id.in_(candidate_ids))
            .all()
        )
        for c in all_requested:
            if c.decision != "included":
                ignored_rules.append(c.to_dict())

    # 更新任务统计和状态
    task = db.query(ReverseRuleTask).filter(ReverseRuleTask.id == task_id).first()
    # 来源合同组数 = 实际产出候选规则的合同组数，非上传总数
    all_candidates = (
        db.query(ReverseRuleCandidate)
        .filter(ReverseRuleCandidate.task_id == task_id)
        .all()
    )
    unique_pairs = {c.source_pair_index for c in all_candidates}
    pair_count = len(unique_pairs)
    if task:
        if task.stats_json:
            task.stats_json = {**task.stats_json, "imported_included": len(imported)}
        task.status = "completed"

    db.commit()
    return {
        "imported": len(imported),
        "ignored": len(ignored_rules),
        "imported_rules": imported,
        "ignored_rules": ignored_rules,
        "pair_count": pair_count,
    }


def _generate_rule_code(candidate: ReverseRuleCandidate) -> str:
    """生成规则编号。"""
    prefix_map = {"财务": "REV-FIN", "法务": "REV-LAW", "履约": "REV-PER"}
    prefix = prefix_map.get(candidate.review_module, "REV-OTH")
    return f"{prefix}-{_uuid()[:8]}"


def _uuid() -> str:
    import uuid as _uuid_mod

    return str(_uuid_mod.uuid4())
