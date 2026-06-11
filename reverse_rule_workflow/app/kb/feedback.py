"""规则反哺回路：输出过滤 + 知识库回流。

两个核心功能：
1. filter_against_kb — 返回用户前过滤 KB 已有规则 + 批内重复规则
2. feedback_rules_to_kb — 高置信度规则经 MiniMax 审核后回流知识库
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

import httpx

from app.kb.loader import load_reverse_rule_cases
from app.kb.retriever import DEFAULT_PERSIST_DIR
from app.kb.retriever import _cosine
from app.kb.retriever import embed_text
from app.kb.retriever import retrieve_reverse_rule_cases
from app.kb.schema import ReverseRuleCase
from app.models.reverse_rule import CandidateRuleForDB
from app.services.review_perspective import normalize_review_perspective

logger = logging.getLogger(__name__)

DEFAULT_CASES_PATH = Path("data/reverse_rule_cases.jsonl")
MIN_CONFIDENCE = float(os.getenv("REVERSE_RULE_FEEDBACK_MIN_CONFIDENCE", "0.75"))
FILTER_SIMILARITY_THRESHOLD = float(os.getenv("REVERSE_RULE_FILTER_SIMILARITY", "0.70"))

_jsonl_lock = threading.Lock()

# ---------------------------------------------------------------------------
# 模块名 → slug 映射（用于 case_id 生成）
# ---------------------------------------------------------------------------

MODULE_SLUG_MAP: dict[str, str] = {
    "付款条款": "payment_terms",
    "违约责任": "breach",
    "赔偿责任上限": "liability_cap",
    "解除条款": "termination",
    "保密条款": "confidentiality",
    "保密义务": "confidentiality",
    "知识产权": "ip",
    "服务水平": "sla",
    "交付验收": "acceptance",
    "验收条款": "acceptance",
    "押金退还": "deposit_refund",
    "数据安全": "data_security",
    "数据安全/个人信息": "data_security",
    "管辖法院": "jurisdiction",
    "通知条款": "notice",
    "不可抗力": "force_majeure",
    "转包/分包": "subcontract",
    "交付期限": "delivery",
    "质量保证": "quality",
    "单方免责": "unilateral_exemption",
    "竞业限制或不招揽": "non_solicit",
    "发票开具": "invoice",
    "审计权": "audit",
    "合同生效条件": "effectiveness",
    "合同标的": "contract_scope",
    "争议解决": "dispute_resolution",
    "所有权/风险转移": "risk_transfer",
}

# ---------------------------------------------------------------------------
# 1. 输出过滤：filter_against_kb
# ---------------------------------------------------------------------------


def filter_against_kb(
    rules: list[CandidateRuleForDB],
) -> tuple[list[CandidateRuleForDB], list[dict[str, Any]]]:
    """在返回用户前过滤 + 审核规则质量。

    三步：
      Step A: KB去重 — 去掉和已有案例重复的
      Step B: 批内去重 — 去掉同一批里互相重复的
      Step C: 质量审核 — MiniMax 检查规则是否达到交付标准

    Returns:
        (kept_rules, filtered_out): 保留的规则列表和被过滤的规则+原因列表
    """
    if not rules:
        logger.info("[Filter] 输入为空，跳过过滤")
        return [], []

    logger.info("[Filter] 开始过滤+审核 %d 条规则", len(rules))
    filtered_out: list[dict[str, Any]] = []
    remaining = list(rules)

    # Step A: 查 KB 去重
    logger.info("[Filter] Step A: KB去重 — 逐条对比同模块已有案例")
    remaining, kb_filtered = _filter_by_kb_dedup(remaining)
    filtered_out.extend(kb_filtered)
    logger.info(
        "[Filter] Step A 完成: 保留 %d 条, KB重复过滤 %d 条",
        len(remaining),
        len(kb_filtered),
    )

    # Step B: 批内语义去重
    logger.info(
        "[Filter] Step B: 批内去重 — 相似度>%.2f合并", FILTER_SIMILARITY_THRESHOLD
    )
    remaining, batch_filtered = _filter_by_batch_dedup(remaining)
    filtered_out.extend(batch_filtered)
    logger.info(
        "[Filter] Step B 完成: 保留 %d 条, 批内重复过滤 %d 条",
        len(remaining),
        len(batch_filtered),
    )

    # Step C: 质量审核 — MiniMax 检查规则是否达到交付标准
    logger.info("[Filter] Step C: 质量审核 — MiniMax检查规则质量")
    remaining, quality_filtered = _filter_by_quality_review(remaining)
    filtered_out.extend(quality_filtered)
    logger.info(
        "[Filter] Step C 完成: 保留 %d 条, 质量不达标过滤 %d 条",
        len(remaining),
        len(quality_filtered),
    )

    logger.info(
        "[Filter] 过滤总结: 输入 %d → 输出 %d (过滤 %d 条: KB重复%d + 批内重复%d + 质量不达标%d)",
        len(rules),
        len(remaining),
        len(filtered_out),
        len(kb_filtered),
        len(batch_filtered),
        len(quality_filtered),
    )
    return remaining, filtered_out


def _filter_by_kb_dedup(
    rules: list[CandidateRuleForDB],
) -> tuple[list[CandidateRuleForDB], list[dict[str, Any]]]:
    """Step A: 逐条查 KB 同模块案例，语义重复的移除。"""
    kept: list[CandidateRuleForDB] = []
    filtered: list[dict[str, Any]] = []

    for rule in rules:
        existing = _fetch_similar_kb_cases(rule)
        if _is_duplicate_in_cases(rule, existing):
            matched_id = (
                existing[0].get("case_id", "unknown")
                if isinstance(existing[0], dict)
                else getattr(existing[0], "case_id", "unknown")
            )
            logger.info(
                "[Filter KB去重] 规则「%s」与已有案例 %s 重复，过滤",
                rule.risk_name,
                matched_id,
            )
            filtered.append(
                {
                    "risk_name": rule.risk_name,
                    "review_module": rule.review_module,
                    "reason": "already_in_kb",
                    "matched_case_id": matched_id,
                }
            )
        else:
            kept.append(rule)

    return kept, filtered


def _filter_by_batch_dedup(
    rules: list[CandidateRuleForDB],
) -> tuple[list[CandidateRuleForDB], list[dict[str, Any]]]:
    """Step B: 同模块内语义重复的规则保留置信度最高的。"""
    if len(rules) <= 1:
        return rules, []

    # 按模块分组
    by_module: dict[str, list[CandidateRuleForDB]] = {}
    for rule in rules:
        by_module.setdefault(rule.review_module, []).append(rule)

    kept: list[CandidateRuleForDB] = []
    filtered: list[dict[str, Any]] = []

    for module_rules in by_module.values():
        if len(module_rules) <= 1:
            kept.extend(module_rules)
            continue

        removed_indices: set[int] = set()
        for i in range(len(module_rules)):
            if i in removed_indices:
                continue
            for j in range(i + 1, len(module_rules)):
                if j in removed_indices:
                    continue
                sim = _rule_pair_similarity(module_rules[i], module_rules[j])
                if sim >= FILTER_SIMILARITY_THRESHOLD:
                    # 保留平均置信度更高的
                    conf_i = _avg_trace_confidence(module_rules[i])
                    conf_j = _avg_trace_confidence(module_rules[j])
                    if conf_i >= conf_j:
                        removed_indices.add(j)
                        logger.info(
                            "[Filter 批内去重] 模块「%s」: 「%s」(conf=%.3f) 与「%s」(conf=%.3f) 重复(sim=%.3f)，保留前者",
                            module_rules[i].review_module,
                            module_rules[i].risk_name,
                            conf_i,
                            module_rules[j].risk_name,
                            conf_j,
                            sim,
                        )
                        filtered.append(
                            {
                                "risk_name": module_rules[j].risk_name,
                                "review_module": module_rules[j].review_module,
                                "reason": "batch_internal_dup",
                                "similar_to": module_rules[i].risk_name,
                                "similarity": round(sim, 4),
                            }
                        )
                    else:
                        removed_indices.add(i)
                        logger.info(
                            "[Filter 批内去重] 模块「%s」: 「%s」(conf=%.3f) 与「%s」(conf=%.3f) 重复(sim=%.3f)，保留后者",
                            module_rules[i].review_module,
                            module_rules[i].risk_name,
                            conf_i,
                            module_rules[j].risk_name,
                            conf_j,
                            sim,
                        )
                        filtered.append(
                            {
                                "risk_name": module_rules[i].risk_name,
                                "review_module": module_rules[i].review_module,
                                "reason": "batch_internal_dup",
                                "similar_to": module_rules[j].risk_name,
                                "similarity": round(sim, 4),
                            }
                        )
                        break  # i 被移除，跳到下一个 i

        for idx, rule in enumerate(module_rules):
            if idx not in removed_indices:
                kept.append(rule)

    return kept, filtered


def _fetch_similar_kb_cases(rule: CandidateRuleForDB) -> list[dict[str, Any]]:
    """查询同模块已有案例（最多 5 条）。"""
    try:
        query = f"{rule.risk_name} {rule.check_point}"
        return retrieve_reverse_rule_cases(
            query=query,
            review_module=rule.review_module,
            k=5,
        )
    except Exception:
        return []


def _is_duplicate_in_cases(
    rule: CandidateRuleForDB, existing_cases: list[dict[str, Any]]
) -> bool:
    """判断规则是否与已有案例语义重复。"""
    if not existing_cases:
        return False

    rule_text = f"{rule.risk_name} {rule.check_point} {rule.trigger_condition}"
    rule_vec = embed_text(rule_text)

    for case in existing_cases:
        case_check = case.get("check_point", "")
        case_trigger = case.get("trigger_condition", "")
        case_text = f"{case.get('risk_name', '')} {case_check} {case_trigger}"
        case_vec = embed_text(case_text)
        sim = _cosine(rule_vec, case_vec)
        if sim >= FILTER_SIMILARITY_THRESHOLD:
            return True
    return False


def _rule_pair_similarity(
    rule_a: CandidateRuleForDB, rule_b: CandidateRuleForDB
) -> float:
    """计算两条规则的语义相似度（基于 check_point + trigger_condition）。"""
    text_a = f"{rule_a.check_point} {rule_a.trigger_condition}"
    text_b = f"{rule_b.check_point} {rule_b.trigger_condition}"
    return _cosine(embed_text(text_a), embed_text(text_b))


def _avg_trace_confidence(rule: CandidateRuleForDB) -> float:
    if not rule.traces:
        return 0.0
    return sum(t.confidence for t in rule.traces) / len(rule.traces)


# ---------------------------------------------------------------------------
# 1.5 质量审核 Prompt & 过滤
# ---------------------------------------------------------------------------

QUALITY_REVIEW_PROMPT = """你是合同审核规则的质量审核员。

请逐条判断以下候选规则是否达到交付给用户的标准。

交付标准：
1. 逻辑闭环：风险识别→检查点→触发条件→修改建议 必须逻辑自洽
2. 建议可执行：suggestion_template 必须具体可落地，不能是废话
3. 风险等级合理：default_risk_level（低/中/高）判断恰当
4. 字段完整：risk_name/check_point/trigger_condition/suggestion_template 不能为空或只有几个字

候选规则列表：
{rules_json}

对每条规则输出一个判定。严格输出以下 JSON 数组，不要 Markdown，不要代码块，不要 <think> 推理：
[{{"rule_index": 0, "passed": true, "reason": "简短理由", "suggestion_fix": null}}, {{"rule_index": 1, "passed": false, "reason": "简短理由", "suggestion_fix": "修改建议"}}]"""


def _filter_by_quality_review(
    rules: list[CandidateRuleForDB],
) -> tuple[list[CandidateRuleForDB], list[dict[str, Any]]]:
    """Step C: 调用 MiniMax 审核规则质量，不达标的过滤掉。"""
    if not rules:
        return [], []

    # 检查是否启用
    enabled = os.getenv("REVERSE_RULE_QUALITY_REVIEW_ENABLED", "1") == "1"
    if not enabled:
        logger.info("[Filter 质量审核] 已禁用，跳过")
        return rules, []

    # 检查是否有 API key
    config = _resolve_judge_config()
    if not config["api_key"]:
        logger.info("[Filter 质量审核] 无API key，跳过质量审核")
        return rules, []

    rules_json = json.dumps(
        [
            {
                "rule_index": i,
                "review_module": r.review_module,
                "risk_name": r.risk_name,
                "check_point": r.check_point,
                "trigger_condition": r.trigger_condition,
                "default_risk_level": r.default_risk_level,
                "suggestion_template": r.suggestion_template,
            }
            for i, r in enumerate(rules)
        ],
        ensure_ascii=False,
        indent=2,
    )

    prompt = QUALITY_REVIEW_PROMPT.format(rules_json=rules_json)
    results = _call_judge(prompt)

    if results is None:
        logger.warning("[Filter 质量审核] API调用失败，保守放行全部规则")
        return rules, []

    # 构建结果映射
    passed_map: dict[int, bool] = {}
    reason_map: dict[int, str] = {}
    for jr in results:
        idx = jr.get("rule_index", -1)
        passed_map[idx] = jr.get("passed", True)
        reason_map[idx] = jr.get("reason", "")

    kept: list[CandidateRuleForDB] = []
    filtered: list[dict[str, Any]] = []

    for i, rule in enumerate(rules):
        passed = passed_map.get(i, True)  # 默认通过
        if passed:
            kept.append(rule)
        else:
            logger.info(
                "[Filter 质量审核] 过滤「%s」: %s",
                rule.risk_name,
                reason_map.get(i, "")[:80],
            )
            filtered.append(
                {
                    "risk_name": rule.risk_name,
                    "review_module": rule.review_module,
                    "reason": f"quality_fail: {reason_map.get(i, '未说明')}",
                }
            )

    return kept, filtered


# ---------------------------------------------------------------------------
# 2. 转换器：CandidateRuleForDB → ReverseRuleCase
# ---------------------------------------------------------------------------


def _slugify(review_module: str) -> str:
    """将中文模块名转为英文 slug。"""
    if review_module in MODULE_SLUG_MAP:
        return MODULE_SLUG_MAP[review_module]
    # fallback: ASCII 安全转换
    slug = review_module.lower().encode("ascii", errors="ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    return slug or "general"


def _generate_case_id(rule: CandidateRuleForDB) -> str:
    """基于规则内容生成稳定的 case_id。"""
    content = f"{rule.risk_name}|{rule.check_point}|{rule.trigger_condition}"
    content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()[:8]
    module_slug = _slugify(rule.review_module)
    return f"auto_{module_slug}_{content_hash}"


def _derive_change_pattern(rule: CandidateRuleForDB) -> str:
    if not rule.traces:
        return "基于合同修改行为反推"
    summaries = [t.diff_summary for t in rule.traces if t.diff_summary.strip()]
    combined = "；".join(summaries)
    return combined[:200] if combined else "基于合同修改行为反推"


def _derive_tags(
    rule: CandidateRuleForDB,
    judge_tags: list[str] | None = None,
) -> list[str]:
    """生成 tags：Judge 建议 > 自动生成。"""
    if judge_tags:
        tags = list(judge_tags)
    else:
        tags = [rule.review_module, rule.contract_type]

    if rule.default_risk_level == "高":
        tags.append("高风险")
    if "自动生成" not in tags:
        tags.append("自动生成")

    # 去重保序
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        tag = tag.strip()
        if tag and tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def candidate_rule_to_reverse_rule_case(
    rule: CandidateRuleForDB,
    judge_result: dict[str, Any] | None = None,
) -> ReverseRuleCase:
    """将生成的候选规则转换为知识库案例。

    Args:
        rule: 生成的候选规则
        judge_result: MiniMax Judge 的判定结果（含 tags, risk_level_override）
    """
    # review_role 映射："通用" → ["甲方", "乙方"]
    perspective = normalize_review_perspective(rule.review_perspective)
    review_roles = [perspective] if perspective != "通用" else ["甲方", "乙方"]

    # 从 traces 提取 before/after/diff_summary/user_intent
    before_example = ""
    after_example = ""
    diff_summary = ""
    user_intent = ""
    if rule.traces:
        first = rule.traces[0]
        before_example = first.evidence_before
        after_example = first.evidence_after
        diff_summary = first.diff_summary
        user_intent = first.user_intent

    # 多 trace 时合并 diff_summary
    if len(rule.traces) > 1:
        summaries = [t.diff_summary for t in rule.traces if t.diff_summary.strip()]
        diff_summary = "；".join(summaries)[:500]

    # Judge 覆盖 risk_level
    risk_level = rule.default_risk_level
    judge_tags = None
    if judge_result:
        override = judge_result.get("risk_level_override")
        if override in ("低", "中", "高"):
            risk_level = override
        judge_tags = judge_result.get("tags")

    return ReverseRuleCase(
        case_id=_generate_case_id(rule),
        contract_type=[rule.contract_type],
        review_role=review_roles,
        review_module=rule.review_module,
        change_pattern=_derive_change_pattern(rule),
        before_example=before_example,
        after_example=after_example,
        diff_summary=diff_summary or _derive_change_pattern(rule),
        user_intent=user_intent
        or f"根据{rule.contract_type}中{rule.review_module}条款的修改行为反推候选审核规则",
        risk_name=rule.risk_name[:100],
        check_point=rule.check_point,
        trigger_condition=rule.trigger_condition,
        default_risk_level=risk_level,
        suggestion_template=rule.suggestion_template,
        example_clause=rule.example_clause,
        tags=_derive_tags(rule, judge_tags),
    )


# ---------------------------------------------------------------------------
# 3. MiniMax Judge 批量审核
# ---------------------------------------------------------------------------

JUDGE_PROMPT = """你是合同审核规则知识库的质量审核员。

请逐条判断以下候选规则是否适合作为知识库案例入库。

入库标准：
1. 规则逻辑自洽：风险识别→检查点→触发条件→建议 形成闭环
2. 不与已有案例重复（已给出同模块相似案例供对比）
3. 具有复用价值：同类合同审核场景可重复使用
4. 表述专业清晰，不含模糊或矛盾的描述

已入库同模块案例（供查重参考）：
{cases_json}

候选规则列表：
{rules_json}

对每条候选规则，输出 JSON 数组：
[{{"case_id": "...", "approved": true/false, "reason": "判定理由",
   "tags": ["建议标签1", "建议标签2"],
   "risk_level_override": null}}]

risk_level_override 仅在认为原始风险等级不当时覆盖（"低"/"中"/"高"/null）。
只输出 JSON 数组，不要其他内容。"""


def _resolve_judge_config() -> dict[str, str]:
    """获取 Judge LLM 配置，复用 MiniMax 环境变量。"""
    return {
        "api_key": os.getenv("MINIMAX_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
        "base_url": (
            os.getenv("MINIMAX_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.minimax.io/v1"
        ),
        "model": os.getenv("LLM_MODEL_NAME", "MiniMax-M2.7"),
    }


def _slim_rule_for_judge(rule: CandidateRuleForDB) -> dict[str, Any]:
    """精简规则字段供 Judge 审核。"""
    return {
        "case_id": _generate_case_id(rule),
        "contract_type": rule.contract_type,
        "review_module": rule.review_module,
        "review_perspective": rule.review_perspective,
        "risk_name": rule.risk_name,
        "check_point": rule.check_point,
        "trigger_condition": rule.trigger_condition,
        "default_risk_level": rule.default_risk_level,
        "suggestion_template": rule.suggestion_template,
        "traces_count": len(rule.traces),
        "avg_confidence": round(_avg_trace_confidence(rule), 4),
    }


def _slim_case_for_judge(case: dict[str, Any]) -> dict[str, Any]:
    """精简已有案例字段供 Judge 参考。"""
    return {
        "case_id": case.get("case_id", ""),
        "review_module": case.get("review_module", ""),
        "risk_name": case.get("risk_name", ""),
        "check_point": case.get("check_point", ""),
        "trigger_condition": case.get("trigger_condition", ""),
        "change_pattern": case.get("change_pattern", ""),
    }


def _call_judge(prompt: str) -> list[dict[str, Any]] | None:
    """调用 MiniMax API 进行批量审核，返回判定结果列表。"""
    config = _resolve_judge_config()
    if not config["api_key"]:
        logger.warning("[Feedback Judge] No API key, rejecting all candidates")
        return None

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{config['base_url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 2048,
                },
            )
            if resp.status_code != 200:
                logger.warning(
                    "[Feedback Judge] API returned %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return None

            body = resp.json()
            content = body["choices"][0]["message"]["content"]

            # 剥离 <think>...</think> 推理块（MiniMax M3）
            cleaned = re.sub(
                r"<think>.*?</think>", "", content, flags=re.DOTALL
            ).strip()

            # 尝试1: 解析 JSON 数组
            start = cleaned.find("[")
            end = cleaned.rfind("]")
            if start >= 0 and end > start:
                try:
                    return json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError:
                    pass

            # 尝试2: 解析 JSON Lines（每行一个 JSON 对象）
            lines = cleaned.split("\n")
            objects = []
            for line in lines:
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        objects.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            if objects:
                return objects

            logger.warning(
                "[Feedback Judge] Could not parse JSON from: %s",
                cleaned[:300],
            )
            return None
    except Exception:
        logger.exception("[Feedback Judge] API call failed")
        return None


def _judge_rules(
    candidates: list[CandidateRuleForDB],
) -> tuple[list[dict[str, Any]], int]:
    """批量审核候选规则。

    Returns:
        (judge_results, judge_errors): 判定结果列表和调用失败计数
    """
    if not candidates:
        return [], 0

    # 按模块分组，每组先查同模块已有案例
    by_module: dict[str, list[CandidateRuleForDB]] = {}
    for rule in candidates:
        by_module.setdefault(rule.review_module, []).append(rule)

    all_results: list[dict[str, Any]] = []
    judge_errors = 0

    for module, module_candidates in by_module.items():
        # 查同模块已有案例（只取 5 条供参考）
        module_cases = _fetch_module_cases_for_judge(module, limit=5)
        logger.info(
            "[Feedback Judge] 模块「%s」: %d 条候选, %d 条已有案例供查重",
            module,
            len(module_candidates),
            len(module_cases),
        )

        # 构建 prompt
        rules_json = json.dumps(
            [_slim_rule_for_judge(r) for r in module_candidates],
            ensure_ascii=False,
            indent=2,
        )
        cases_json = json.dumps(
            [_slim_case_for_judge(c) for c in module_cases],
            ensure_ascii=False,
            indent=2,
        )

        prompt = JUDGE_PROMPT.format(cases_json=cases_json, rules_json=rules_json)
        results = _call_judge(prompt)

        if results is None:
            judge_errors += len(module_candidates)
            # 保守拒绝：每个候选都标记为 rejected
            for rule in module_candidates:
                all_results.append(
                    {
                        "case_id": _generate_case_id(rule),
                        "approved": False,
                        "reason": "Judge API 调用失败，保守拒绝",
                        "tags": None,
                        "risk_level_override": None,
                    }
                )
        else:
            all_results.extend(results)

    return all_results, judge_errors


def _fetch_module_cases_for_judge(
    review_module: str, limit: int = 5
) -> list[dict[str, Any]]:
    """获取指定模块的已有案例供 Judge 查重参考。"""
    try:
        return retrieve_reverse_rule_cases(
            query=review_module,
            review_module=review_module,
            k=limit,
        )
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 4. 知识库写入
# ---------------------------------------------------------------------------


def append_case_to_jsonl(
    case: ReverseRuleCase,
    jsonl_path: Path | None = None,
) -> None:
    """线程+进程安全追加一条案例到 JSONL 文件。

    线程安全: _jsonl_lock（进程内）
    进程安全: 锁文件重试机制（跨进程），超时 5 秒
    """
    import time as _time

    if jsonl_path is None:
        jsonl_path = DEFAULT_CASES_PATH
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    with _jsonl_lock:
        # 跨进程锁：通过排他创建锁文件实现
        lock_path = jsonl_path.with_suffix(jsonl_path.suffix + ".lock")
        deadline = _time.monotonic() + 5.0
        lock_fd = None

        while lock_fd is None:
            try:
                # 排他创建：已存在则抛异常
                lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if _time.monotonic() > deadline:
                    logger.warning("[Feedback] 获取 JSONL 锁超时，强制写入")
                    break
                _time.sleep(0.05)

        try:
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(case.model_dump_json(ensure_ascii=False) + "\n")
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
                try:
                    lock_path.unlink()
                except OSError:
                    pass

    logger.info("[Feedback] JSONL 追加: %s → %s", case.case_id, jsonl_path)


def rebuild_local_kb(
    jsonl_path: Path | None = None,
    persist_dir: str | None = None,
) -> None:
    """从 JSONL 重建本地检索索引。"""
    if jsonl_path is None:
        jsonl_path = DEFAULT_CASES_PATH
    if persist_dir is None:
        persist_dir = DEFAULT_PERSIST_DIR
    from app.kb.retriever import build_reverse_rule_kb

    cases = load_reverse_rule_cases(jsonl_path)
    build_reverse_rule_kb(cases, persist_dir=persist_dir)
    logger.info("[Feedback] Local KB rebuilt with %d cases", len(cases))


def push_case_to_rag_service(case: ReverseRuleCase) -> bool:
    """推送单条案例到 RAG 服务 /index 端点。"""
    rag_url = os.getenv("RAG_SERVICE_URL", "http://rag-service:8000")
    logger.info("[Feedback] RAG 推送: %s → %s/index", case.case_id, rag_url)
    try:
        import urllib.error
        import urllib.request

        payload = json.dumps({"case": case.model_dump()}, ensure_ascii=False).encode()
        req = urllib.request.Request(
            f"{rag_url}/index",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                logger.info("[Feedback] RAG 推送成功: %s", case.case_id)
                return True
            logger.warning(
                "[Feedback] RAG 推送失败 status=%d: %s",
                resp.status,
                resp.read().decode(errors="ignore")[:200],
            )
            return False
    except urllib.error.URLError:
        logger.warning("[Feedback] RAG 服务不可达: %s", rag_url)
        return False
    except Exception:
        logger.exception("[Feedback] RAG 推送异常: %s", case.case_id)
        return False


# ---------------------------------------------------------------------------
# 5. 编排器
# ---------------------------------------------------------------------------


def _load_existing_case_ids(jsonl_path: Path | None = None) -> set[str]:
    """从 JSONL 加载已有 case_id 集合（用于去重）。"""
    if jsonl_path is None:
        jsonl_path = DEFAULT_CASES_PATH
    if not jsonl_path.exists():
        return set()
    ids: set[str] = set()
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                ids.add(data.get("case_id", ""))
            except json.JSONDecodeError:
                continue
    return ids


def _empty_feedback_result() -> dict[str, Any]:
    """返回空的 feedback_result。"""
    return {
        "candidates": 0,
        "judge_approved": 0,
        "judge_rejected": 0,
        "judge_error": 0,
        "skipped_duplicates": 0,
        "added_to_kb": 0,
        "rag_success": 0,
        "rag_failed": 0,
        "case_ids": [],
        "judge_details": [],
    }


def feedback_rules_to_kb(
    rules: list[CandidateRuleForDB],
) -> dict[str, Any]:
    """编排器：筛选 → MiniMax 审核 → 转换 → 去重 → 写入。

    Returns:
        feedback_result 字典，包含各步骤统计。
    """
    logger.info("[Feedback] ========== 开始知识库回流 ==========")
    logger.info("[Feedback] 输入规则数: %d", len(rules))

    if not rules:
        logger.info("[Feedback] 输入为空，跳过")
        return _empty_feedback_result()

    # Step 1: 置信度筛选
    candidates = [r for r in rules if _avg_trace_confidence(r) > MIN_CONFIDENCE]
    logger.info(
        "[Feedback] Step1 置信度筛选: %d/%d 条通过 (阈值>%.2f)",
        len(candidates),
        len(rules),
        MIN_CONFIDENCE,
    )
    for r in rules:
        conf = _avg_trace_confidence(r)
        if conf <= MIN_CONFIDENCE:
            logger.info(
                "[Feedback]   跳过「%s」: 置信度 %.3f ≤ %.2f",
                r.risk_name,
                conf,
                MIN_CONFIDENCE,
            )

    if not candidates:
        logger.info("[Feedback] 无候选规则通过筛选，结束")
        return _empty_feedback_result()

    # Step 2-3: MiniMax 批量审核
    logger.info(
        "[Feedback] Step2 调用 MiniMax Judge 批量审核 %d 条候选规则", len(candidates)
    )
    judge_results, judge_errors = _judge_rules(candidates)
    logger.info(
        "[Feedback] Step2 Judge 完成: %d 条结果, %d 条调用失败",
        len(judge_results),
        judge_errors,
    )

    # 构建 case_id → judge_result 映射
    judge_map: dict[str, dict[str, Any]] = {}
    for jr in judge_results:
        cid = jr.get("case_id", "")
        if cid:
            judge_map[cid] = jr

    # 漏判检测：确保每个候选规则都有对应的 Judge 结果
    candidate_ids = {_generate_case_id(r) for r in candidates}
    judged_ids = set(judge_map.keys())
    missing = candidate_ids - judged_ids
    extra = judged_ids - candidate_ids
    if missing:
        logger.warning(
            "[Feedback Judge] 漏判 %d 条候选规则（将被保守拒绝）: %s",
            len(missing),
            ", ".join(sorted(missing)),
        )
    if extra:
        logger.warning(
            "[Feedback Judge] Judge 返回了 %d 条不存在候选的 case_id: %s",
            len(extra),
            ", ".join(sorted(extra)),
        )

    # Step 4-5: 转换 + 去重
    logger.info("[Feedback] Step3 转换+去重+写入")
    existing_ids = _load_existing_case_ids()
    logger.info("[Feedback] 已有案例数: %d", len(existing_ids))

    approved_count = 0
    rejected_count = 0
    skipped_duplicates = 0
    added_count = 0
    rag_success = 0
    rag_failed = 0
    added_case_ids: list[str] = []
    judge_details: list[dict[str, Any]] = []

    for rule in candidates:
        case_id = _generate_case_id(rule)
        jr = judge_map.get(case_id, {})

        if not jr:
            # Judge 未返回此 case_id 的结果（不应发生）
            judge_details.append(
                {"case_id": case_id, "approved": False, "reason": "Judge 未返回结果"}
            )
            rejected_count += 1
            continue

        is_approved = jr.get("approved", False)

        if not is_approved:
            logger.info(
                "[Feedback]   Judge拒绝「%s」: %s",
                rule.risk_name,
                jr.get("reason", "")[:80],
            )
            judge_details.append(
                {
                    "case_id": case_id,
                    "approved": False,
                    "reason": jr.get("reason", ""),
                }
            )
            rejected_count += 1
            continue

        approved_count += 1
        logger.info("[Feedback]   Judge通过「%s」→ case_id=%s", rule.risk_name, case_id)

        # 去重检查
        if case_id in existing_ids:
            skipped_duplicates += 1
            judge_details.append(
                {
                    "case_id": case_id,
                    "approved": True,
                    "reason": "已存在相同案例，跳过",
                }
            )
            continue

        # 转换
        try:
            case = candidate_rule_to_reverse_rule_case(rule, jr)
        except Exception:
            logger.exception("[Feedback] Failed to convert rule to case")
            judge_details.append(
                {
                    "case_id": case_id,
                    "approved": False,
                    "reason": "转换 ReverseRuleCase 失败",
                }
            )
            rejected_count += 1
            continue

        # Step 6: 写入 JSONL
        try:
            append_case_to_jsonl(case)
            existing_ids.add(case_id)
            added_count += 1
            added_case_ids.append(case_id)
        except Exception:
            logger.exception("[Feedback] Failed to append case to JSONL")
            judge_details.append(
                {
                    "case_id": case_id,
                    "approved": False,
                    "reason": "JSONL 写入失败",
                }
            )
            rejected_count += 1
            continue

        # 推送 RAG 服务
        if push_case_to_rag_service(case):
            rag_success += 1
        else:
            rag_failed += 1

        judge_details.append(
            {
                "case_id": case_id,
                "approved": True,
                "reason": jr.get("reason", ""),
            }
        )

    # 重建本地索引
    if added_count > 0:
        logger.info("[Feedback] Step4 重建本地索引 (%d 条新案例)", added_count)
        try:
            rebuild_local_kb()
            logger.info("[Feedback] 本地索引重建完成")
        except Exception:
            logger.exception("[Feedback] Failed to rebuild local KB")

    logger.info(
        "[Feedback] ========== 回流完成: 候选%d 通过%d 拒绝%d 入库%d RAG成功%d/失败%d ==========",
        len(candidates),
        approved_count,
        rejected_count + judge_errors,
        added_count,
        rag_success,
        rag_failed,
    )
    return {
        "candidates": len(candidates),
        "judge_approved": approved_count,
        "judge_rejected": rejected_count,
        "judge_error": judge_errors,
        "skipped_duplicates": skipped_duplicates,
        "added_to_kb": added_count,
        "rag_success": rag_success,
        "rag_failed": rag_failed,
        "case_ids": added_case_ids,
        "judge_details": judge_details,
    }
