"""Main orchestration for the standalone contract audit workflow."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from contextvars import ContextVar
from typing import Any

from .audit_prompts import build_finance_review_prompt
from .audit_prompts import build_legal_review_prompt
from .audit_prompts import build_performance_review_prompt
from .contract_type_classifier import classify_contract_type
from .llm_client import NODE_REQUEST_WINDOW_SECONDS
from .llm_client import get_llm_client
from .rule_adapter import adapt_rules
from .rule_adapter import flatten_rules
from .rule_adapter import split_common_specific_rules
from .rules_client import fetch_audit_rules
from .schemas import LLMOutputError
from .schemas import LLMRequestError
from .schemas import count_final_items
from .schemas import count_intermediate_items
from .schemas import empty_final_result
from .schemas import empty_review_result
from .schemas import ensure_str
from .schemas import normalize_final_risk
from .schemas import normalize_intermediate_risk
from .schemas import normalize_review_result
from .schemas import parse_json_like
from .schemas import preview_text
from .schemas import strip_markdown_code_fence

logger = logging.getLogger(__name__)
REVIEW_JSON_ONLY_WINDOW_SECONDS = NODE_REQUEST_WINDOW_SECONDS
_CURRENT_REVIEW_RULE_GROUP: ContextVar[str] = ContextVar(
    "contract_audit_review_rule_group",
    default="unknown",
)


async def audit_contract(input: str) -> dict:
    content = input
    clean_contract_text = input
    if not isinstance(content, str):
        raise TypeError("audit_contract input must be a string.")
    if not content.strip():
        return empty_final_result()

    contract_type = await classify_contract_type(content)
    rule_response = await fetch_audit_rules(contract_type)
    adapted_rules = adapt_rules(rule_response)

    fin_common_rules, fin_spec_rules = split_common_specific_rules(
        adapted_rules["finance_rules"]
    )
    lgl_common_rules, lgl_spec_rules = split_common_specific_rules(
        adapted_rules["legal_rules"]
    )
    perf_common_rules, perf_spec_rules = split_common_specific_rules(
        adapted_rules["performance_rules"]
    )

    (
        fin_common_result,
        fin_spec_result,
        lgl_common_result,
        lgl_spec_result,
        perf_common_result,
        perf_spec_result,
    ) = await asyncio.gather(
        _run_review_task("财务", "通用", fin_common_rules, clean_contract_text),
        _run_review_task("财务", "专项", fin_spec_rules, clean_contract_text),
        _run_review_task("法务", "通用", lgl_common_rules, clean_contract_text),
        _run_review_task("法务", "专项", lgl_spec_rules, clean_contract_text),
        _run_review_task("履约", "通用", perf_common_rules, clean_contract_text),
        _run_review_task("履约", "专项", perf_spec_rules, clean_contract_text),
    )

    finance_review_result = merge_review_results(
        fin_common_result,
        fin_spec_result,
    )
    legal_review_result = merge_review_results(
        lgl_common_result,
        lgl_spec_result,
    )
    performance_review_result = merge_review_results(
        perf_common_result,
        perf_spec_result,
    )
    total_result = merge_review_results(
        finance_review_result,
        legal_review_result,
        performance_review_result,
    )

    return normalize_final_output(total_result, flatten_rules(adapted_rules))


async def review_rules_with_llm(
    module: str,
    rules: list[dict],
    clean_contract_text: str,
) -> dict:
    rule_group = _CURRENT_REVIEW_RULE_GROUP.get()
    if not rules:
        return empty_review_result()

    started_at = time.perf_counter()
    prompt = _build_review_prompt(module, rules, clean_contract_text)
    last_request_error: LLMRequestError | None = None
    last_output_error: LLMOutputError | None = None
    last_raw_output = ""
    attempt = 0

    while True:
        elapsed_seconds = time.perf_counter() - started_at
        remaining_seconds = REVIEW_JSON_ONLY_WINDOW_SECONDS - elapsed_seconds
        if remaining_seconds <= 0:
            break

        attempt += 1
        try:
            raw_output = await get_llm_client().complete(
                prompt,
                step=f"review_rules_with_llm:{module}:{rule_group}",
                max_window_seconds=remaining_seconds,
            )
            last_raw_output = raw_output
        except LLMRequestError as exc:
            last_request_error = exc
            logger.warning(
                "Review request attempt failed before JSON-only window exhausted [module=%s rule_group=%s rule_count=%s attempt=%s remaining_seconds=%.2f]: %s",
                module,
                rule_group,
                len(rules),
                attempt,
                max(REVIEW_JSON_ONLY_WINDOW_SECONDS - (time.perf_counter() - started_at), 0.0),
                exc,
            )
            continue

        try:
            return _normalize_review_output_with_context(
                module=module,
                rule_group=rule_group,
                rules=rules,
                raw_output=raw_output,
                started_at=started_at,
            )
        except LLMOutputError as exc:
            last_output_error = exc
            logger.warning(
                "Review output invalid before JSON-only window exhausted [module=%s rule_group=%s rule_count=%s attempt=%s remaining_seconds=%.2f]: %s",
                module,
                rule_group,
                len(rules),
                attempt,
                max(REVIEW_JSON_ONLY_WINDOW_SECONDS - (time.perf_counter() - started_at), 0.0),
                exc,
            )
            continue

    if last_output_error is not None and last_raw_output:
        logger.warning(
            "Review output invalid after JSON-only window exhausted, using heuristic extraction [module=%s rule_group=%s rule_count=%s]: %s",
            module,
            rule_group,
            len(rules),
            last_output_error,
        )
        return _extract_review_result_from_analysis_text(
            module=module,
            rule_group=rule_group,
            rules=rules,
            raw_output=last_raw_output,
            started_at=started_at,
        )

    error = last_request_error or LLMRequestError(
        f"Review request failed to produce valid JSON within {REVIEW_JSON_ONLY_WINDOW_SECONDS} seconds."
    )
    logger.error(
        "Review request failed after JSON-only window exhausted, using fallback result [module=%s rule_group=%s rule_count=%s]: %s",
        module,
        rule_group,
        len(rules),
        error,
    )
    return _build_request_failure_review_result(
        module=module,
        rule_group=rule_group,
        rules=rules,
        error=error,
        started_at=started_at,
    )


def merge_review_results(*results: dict) -> dict:
    output: list[dict[str, str]] = []

    for result in results:
        normalized = normalize_review_result(result)
        for item in normalized["output"]:
            output.append(item)

    merged = {"output": output}
    merged.update(count_intermediate_items(output))
    return merged


def normalize_final_output(raw_result: dict, all_rules: list[dict]) -> dict:
    normalized = normalize_review_result(raw_result)
    final_output: list[dict[str, str]] = []

    for item in normalized["output"]:
        final_risk, risk_label = normalize_final_risk(item.get("risk"))
        key = ensure_str(item.get("key"))
        tip = ensure_str(item.get("tip"), "无")
        content = ensure_str(item.get("content"), "无")
        advice = ensure_str(item.get("advice"), "无")
        replace_text = ensure_str(item.get("replace_text"), "无")
        final_item = {
            "rule_code": _resolve_rule_code(item, all_rules),
            "risk": final_risk,
            "risk_label": risk_label,
            "action_type": _determine_action_type(
                risk=final_risk,
                key=key,
                content=content,
                replace_text=replace_text,
            ),
            "key": key,
            "tip": tip,
            "content": content,
            "advice": advice,
            "replace_text": replace_text,
        }
        final_output.append(final_item)

    final_result = {
        "agreeCount": "0",
        "highlevelriskCount": "0",
        "mediumlevelriskCount": "0",
        "lowlevelriskCount": "0",
        "output": final_output,
    }
    final_result.update(count_final_items(final_output))
    return final_result


def _build_review_prompt(
    module: str,
    rules: list[dict],
    clean_contract_text: str,
) -> str:
    if module == "财务":
        return build_finance_review_prompt(rules, clean_contract_text)
    if module == "法务":
        return build_legal_review_prompt(rules, clean_contract_text)
    if module == "履约":
        return build_performance_review_prompt(rules, clean_contract_text)
    raise ValueError(f"Unsupported review module: {module}")


async def _run_review_task(
    module: str,
    rule_group: str,
    rules: list[dict],
    clean_contract_text: str,
) -> dict:
    token = _CURRENT_REVIEW_RULE_GROUP.set(rule_group)
    try:
        return await review_rules_with_llm(module, rules, clean_contract_text)
    finally:
        _CURRENT_REVIEW_RULE_GROUP.reset(token)


def _normalize_review_output_with_context(
    module: str,
    rule_group: str,
    rules: list[dict],
    raw_output: str,
    started_at: float,
) -> dict:
    cleaned_output = strip_markdown_code_fence(str(raw_output))
    try:
        parsed_output = parse_json_like(raw_output)
    except LLMOutputError as exc:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        message = (
            "Review output JSON parse failed "
            f"[module={module} rule_group={rule_group} rule_count={len(rules)} "
            f"elapsed_ms={elapsed_ms} parse_error={type(exc).__name__}: {exc}] "
            f"raw_output_preview={preview_text(raw_output)!r} "
            f"cleaned_output_preview={preview_text(cleaned_output)!r}"
        )
        raise LLMOutputError(message) from exc

    result = normalize_review_result(parsed_output, expected_rules=rules)
    if len(result["output"]) != len(rules):
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        raise LLMOutputError(
            "Review output count mismatch "
            f"[module={module} rule_group={rule_group} rule_count={len(rules)} "
            f"actual_output_count={len(result['output'])} elapsed_ms={elapsed_ms}] "
            f"raw_output_preview={preview_text(raw_output)!r} "
            f"cleaned_output_preview={preview_text(cleaned_output)!r}"
        )
    return result


def _extract_review_result_from_analysis_text(
    module: str,
    rule_group: str,
    rules: list[dict],
    raw_output: str,
    started_at: float,
) -> dict:
    text = str(raw_output or "")
    items = []
    for index, rule in enumerate(rules):
        section = _locate_rule_section(text, rules, index)
        items.append(_build_item_from_analysis_section(rule, section))

    result = {"output": items}
    result.update(count_intermediate_items(items))
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    logger.warning(
        "Review output extracted heuristically [module=%s rule_group=%s rule_count=%s elapsed_ms=%s]",
        module,
        rule_group,
        len(rules),
        elapsed_ms,
    )
    return result


def _build_request_failure_review_result(
    module: str,
    rule_group: str,
    rules: list[dict],
    error: Exception,
    started_at: float,
) -> dict:
    items = []
    reason = preview_text(str(error), 200)
    for rule in rules:
        default_risk = _default_rule_risk(rule)
        items.append(
            {
                "risk": default_risk,
                "key": ensure_str(rule.get("risk_name")) or ensure_str(rule.get("check_point")),
                "tip": f"审查节点调用失败，需人工复核：{reason}",
                "content": "无" if default_risk == "通过" else "未发现明确原文，但相关内容缺失",
                "advice": ensure_str(rule.get("suggestion_template"), "建议人工复核相关条款。"),
                "replace_text": "无",
            }
        )
    result = {"output": items}
    result.update(count_intermediate_items(items))
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    logger.warning(
        "Review request fallback generated [module=%s rule_group=%s rule_count=%s elapsed_ms=%s]",
        module,
        rule_group,
        len(rules),
        elapsed_ms,
    )
    return result


def _locate_rule_section(text: str, rules: list[dict], index: int) -> str:
    rule = rules[index]
    code = ensure_str(rule.get("rule_code")) or ensure_str(rule.get("rule_id"))
    risk_name = ensure_str(rule.get("risk_name"))
    start = -1
    if code:
        start = text.find(code)
    if start == -1 and risk_name:
        start = text.find(risk_name)
    if start == -1:
        return ""

    end = len(text)
    for later_rule in rules[index + 1 :]:
        later_code = ensure_str(later_rule.get("rule_code")) or ensure_str(later_rule.get("rule_id"))
        later_risk_name = ensure_str(later_rule.get("risk_name"))
        later_positions = [
            pos
            for pos in (
                text.find(later_code, start + 1) if later_code else -1,
                text.find(later_risk_name, start + 1) if later_risk_name else -1,
            )
            if pos != -1
        ]
        if later_positions:
            end = min(later_positions)
            break
    return text[start:end]


def _build_item_from_analysis_section(rule: dict[str, Any], section: str) -> dict[str, str]:
    key = ensure_str(rule.get("risk_name")) or ensure_str(rule.get("check_point"))
    risk = _infer_risk_from_section(section, rule)
    if risk == "通过":
        return {
            "risk": "通过",
            "key": key,
            "tip": "无",
            "content": "无",
            "advice": "无",
            "replace_text": "无",
        }

    content = _infer_content_from_section(section)
    tip = _infer_tip_from_section(section) or f"{key}存在风险，建议人工复核。"
    advice = ensure_str(rule.get("suggestion_template"), f"建议补充并明确{key}相关条款。")
    return {
        "risk": risk,
        "key": key,
        "tip": tip,
        "content": content,
        "advice": advice,
        "replace_text": "无",
    }


def _infer_risk_from_section(section: str, rule: dict[str, Any]) -> str:
    text = ensure_str(section)
    lower_text = text.lower()
    if any(token in text for token in ("高风险", "风险等级：高", "风险: 高", "Risk: 高")):
        return "高风险"
    if any(token in text for token in ("中风险", "风险等级：中", "风险: 中", "Risk: 中")):
        return "中风险"
    if any(token in text for token in ("低风险", "风险等级：低", "风险: 低", "Risk: 低")):
        return "低风险"
    if any(token in text for token in ("通过", "无风险")) or any(
        token in lower_text for token in ("this passes", "pass.", " pass", "no risk")
    ):
        return "通过"
    if any(
        token in lower_text
        for token in (
            "this is a risk",
            "is a risk",
            "risk: yes",
            "trigger",
            "doesn't mention",
            "does not mention",
            "doesn't specify",
            "not specify",
            "vague",
        )
    ) or any(token in text for token in ("存在风险", "构成风险", "未约定", "不明确", "缺失", "另行协商")):
        return _default_rule_risk(rule)
    return "通过"


def _default_rule_risk(rule: dict[str, Any]) -> str:
    default_level = ensure_str(rule.get("default_risk_level"), "中")
    return normalize_intermediate_risk(default_level)


def _infer_content_from_section(section: str) -> str:
    text = ensure_str(section)
    if not text:
        return "未发现明确原文，但相关内容缺失"
    if "未发现明确原文，但相关内容缺失" in text:
        return "未发现明确原文，但相关内容缺失"
    if any(
        token in text.lower()
        for token in ("doesn't mention", "does not mention", "not specify", "missing")
    ) or any(token in text for token in ("未约定", "未明确", "缺失", "另行协商")):
        return "未发现明确原文，但相关内容缺失"

    quoted_matches = re.findall(r"[“\"]([^\"”\n]{4,200})[”\"]", text)
    for match in quoted_matches:
        candidate = ensure_str(match)
        if candidate:
            return candidate
    return "未发现明确原文，但相关内容缺失"


def _infer_tip_from_section(section: str) -> str:
    text = ensure_str(section)
    if not text:
        return ""
    lines = [line.strip(" -*\t") for line in text.splitlines()]
    for line in lines:
        if not line:
            continue
        lower_line = line.lower()
        if any(
            prefix in lower_line
            for prefix in (
                "rule ",
                "check point",
                "trigger",
                "default risk",
                "contract content",
            )
        ):
            continue
        if any(
            token in lower_line
            for token in (
                "doesn't",
                "does not",
                "not specify",
                "vague",
                "unclear",
                "missing",
                "risk",
            )
        ) or any(token in line for token in ("未约定", "不明确", "缺失", "另行协商", "风险")):
            return preview_text(line, 120)
    return preview_text(lines[1] if len(lines) > 1 else lines[0], 120) if lines else ""


def _resolve_rule_code(item: dict[str, Any], all_rules: list[dict]) -> str:
    direct_code = ensure_str(item.get("rule_code")) or ensure_str(item.get("rule_id"))
    if direct_code:
        return direct_code

    key = ensure_str(item.get("key"))
    if not key:
        return ""
    for rule in all_rules:
        if ensure_str(rule.get("risk_name")) == key:
            return ensure_str(rule.get("rule_code")) or ensure_str(rule.get("rule_id"))
    return ""


def _determine_action_type(
    risk: str,
    key: str,
    content: str,
    replace_text: str,
) -> str:
    normalized_key = ensure_str(key)
    normalized_content = ensure_str(content)
    normalized_replace_text = ensure_str(replace_text)

    if risk == "pass":
        return "manual"
    if not normalized_replace_text or normalized_replace_text == "无":
        return "manual"
    if (
        not normalized_content
        or normalized_content == "无"
        or "未发现明确原文" in normalized_content
        or "相关内容缺失" in normalized_content
    ):
        return "append"
    if any(token in normalized_key for token in ("缺失", "不明确", "不清晰", "不具体", "不足")):
        return "insert"
    if normalized_content and normalized_content != "无" and normalized_replace_text != "无":
        return "replace"
    return "manual"
