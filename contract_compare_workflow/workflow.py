"""Standalone contract comparison workflow implementation."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from .llm_client import LLMClientError, chat_completion
from .prompts import (
    build_analyze_diff_risks_prompt,
    build_classify_contract_type_prompt,
    build_identify_differences_prompt,
)
from .rules_client import fetch_audit_rules


CONTRACT_TYPES = {"采购合同", "服务合同", "合作协议", "其他"}
CHANGE_TYPES = {"added", "deleted", "modified", "moved"}
RISK_LEVELS = {"high", "medium", "low"}

ERR_RULES_REQUEST_FAILED = "规则接口请求失败"
ERR_RULES_BODY_INVALID = "规则接口返回 body 不是合法 JSON"
ERR_DIFF_PARSE_FAILED = "差异识别结果解析失败"
ERR_RISK_PARSE_FAILED = "风险审查结果解析失败"

FINAL_FIELDS = ("success", "enhanced", "total_risks", "message")
ENHANCED_FIELDS = (
    "original",
    "change_type",
    "old_quote",
    "new_quote",
    "category",
    "summary",
    "risk_level",
    "evidence",
    "impact",
    "suggestion",
)

DEFAULT_REVIEW_SUGGESTION = "建议人工复核该改动是否符合业务预期"
DEFAULT_FORMAT_SUGGESTION = "无需修改，建议人工确认"

SUBSTANTIVE_KEYWORDS = (
    "金额",
    "价",
    "费用",
    "付款",
    "支付",
    "发票",
    "税",
    "期限",
    "日期",
    "责任",
    "违约",
    "赔偿",
    "验收",
    "解除",
    "终止",
    "争议",
    "仲裁",
    "法院",
    "知识产权",
    "保密",
    "交付",
    "履约",
    "义务",
    "权利",
)
NON_SUBSTANTIVE_KEYWORDS = (
    "非实质性",
    "格式",
    "标点",
    "空格",
    "换行",
    "编号",
    "标题样式",
    "排版",
    "位置移动",
    "单纯位置",
    "移位",
)

_DEBUG_CONTEXT: dict[str, Any] = {}


class CompareWorkflowError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def reset_debug_context() -> None:
    _DEBUG_CONTEXT.clear()


def update_debug_context(**values: Any) -> None:
    for key, value in values.items():
        _DEBUG_CONTEXT[key] = value


def get_debug_context() -> dict[str, Any]:
    return dict(_DEBUG_CONTEXT)


async def compare_contracts(old_text: str, new_text: str, task_type: str = "compare") -> dict[str, Any]:
    """Contract comparison workflow entry point.

    task_type is fixed as compare. The current workflow does not branch on it.
    """

    _ = task_type or "compare"
    reset_debug_context()

    if not _string_value(old_text).strip() and not _string_value(new_text).strip():
        return _failure("old_text 和 new_text 不能为空")
    if not _string_value(old_text).strip():
        return _failure("old_text 不能为空")
    if not _string_value(new_text).strip():
        return _failure("new_text 不能为空")

    try:
        contract_type, diff_texts = await asyncio.gather(
            classify_compare_contract_type(old_text, new_text),
            identify_differences(old_text, new_text),
        )
    except CompareWorkflowError as exc:
        return _failure(exc.message)

    rules_response = await fetch_audit_rules(contract_type)
    parsed_rules = parse_compare_rule_response(
        rules_response.get("body"),
        int(rules_response.get("status_code") or 0),
        diff_texts,
    )

    if not parsed_rules["success"]:
        return _failure(parsed_rules["message"] or ERR_RULES_REQUEST_FAILED)

    parsed_diff_texts = parsed_rules["diff_texts"]
    if not parsed_diff_texts:
        return _success_empty()

    risk_result = await analyze_diff_risks_with_llm(
        old_text=old_text,
        new_text=new_text,
        diff_texts=parsed_diff_texts,
        common_rules=parsed_rules["common_rules"],
        specific_rules=parsed_rules["specific_rules"],
    )
    if not risk_result.get("success", False):
        return _failure(_string_value(risk_result.get("message")) or ERR_RISK_PARSE_FAILED)
    return normalize_compare_output(risk_result, parsed_diff_texts)


async def classify_compare_contract_type(old_text: str, new_text: str) -> str:
    """Classify the compared contract into one of the supported contract types."""

    prompt = build_classify_contract_type_prompt(old_text=old_text, new_text=new_text)
    try:
        raw_result = await chat_completion(prompt, json_mode=True)
    except Exception:
        return "其他"

    contract_type = _strip_markdown_code_block(raw_result).strip()
    return contract_type if contract_type in CONTRACT_TYPES else "其他"


async def identify_differences(old_text: str, new_text: str) -> list[dict[str, Any]]:
    """Identify substantive differences and return diff_texts."""

    update_debug_context(step="identify_differences")
    chunks = _build_identify_chunks(old_text, new_text)
    changed_chunks = [chunk for chunk in chunks if chunk["old_text"] != chunk["new_text"]]
    update_debug_context(
        identify_strategy="section_split",
        identify_chunk_count=len(chunks),
        identify_changed_chunk_count=len(changed_chunks),
        identify_request_mode="json_mode_only",
    )

    if not changed_chunks:
        node_output = {"diff_texts": []}
        update_debug_context(
            identify_node_output=node_output,
            identify_diff_count=0,
            identify_llm_latency_ms=0.0,
        )
        return []

    all_diff_texts: list[dict[str, Any]] = []
    total_llm_latency_ms = 0.0
    chunk_summaries: list[dict[str, Any]] = []

    for chunk in changed_chunks:
        try:
            chunk_diff_texts, chunk_debug = await _identify_differences_for_chunk(
                old_text=chunk["old_text"],
                new_text=chunk["new_text"],
                full_old_text=old_text,
                full_new_text=new_text,
            )
        except CompareWorkflowError as exc:
            update_debug_context(
                identify_exception_type="CompareWorkflowError",
                identify_exception_message=exc.message,
                identify_failed_chunk=chunk["section_key"],
            )
            raise

        total_llm_latency_ms += float(chunk_debug.get("latency_ms") or 0.0)
        all_diff_texts.extend(chunk_diff_texts)
        chunk_summaries.append(
            {
                "section_key": chunk["section_key"],
                "diff_count": len(chunk_diff_texts),
                "latency_ms": chunk_debug.get("latency_ms"),
            }
        )

        if "raw_output_preview" in chunk_debug and "identify_raw_output_preview" not in get_debug_context():
            update_debug_context(
                identify_raw_output_preview=chunk_debug["raw_output_preview"],
                identify_cleaned_output_preview=chunk_debug.get("cleaned_output_preview", ""),
            )

    normalized = _normalize_diff_texts(all_diff_texts, old_text=old_text, new_text=new_text, validate_quotes=True)
    node_output = {"diff_texts": normalized}
    update_debug_context(
        identify_llm_latency_ms=round(total_llm_latency_ms, 3),
        identify_chunk_summaries=chunk_summaries,
        identify_node_output=node_output,
        identify_diff_count=len(normalized),
    )
    return normalized


def parse_compare_rule_response(body: Any, status_code: int, diff_texts: Any) -> dict[str, Any]:
    """Parse rule API response, merge rules, and split common/specific rules."""

    try:
        parsed = _parse_rule_body(body)
    except ValueError:
        return {
            "success": False,
            "common_rules": [],
            "specific_rules": [],
            "diff_texts": [],
            "total_rules": 0,
            "message": ERR_RULES_BODY_INVALID,
        }

    payload = parsed.get("data") if isinstance(parsed, dict) and isinstance(parsed.get("data"), dict) else parsed
    if not isinstance(payload, dict):
        payload = {}

    parsed_diff_texts = _parse_diff_texts_value(diff_texts)

    finance_rules = payload.get("finance_rules") if isinstance(payload.get("finance_rules"), list) else []
    legal_rules = payload.get("legal_rules") if isinstance(payload.get("legal_rules"), list) else []
    performance_rules = payload.get("performance_rules") if isinstance(payload.get("performance_rules"), list) else []
    other_rules = payload.get("other_rules") if isinstance(payload.get("other_rules"), list) else []

    all_rules = [
        *finance_rules,
        *legal_rules,
        *performance_rules,
        *other_rules,
    ]
    common_rules = [rule for rule in all_rules if _rule_contract_type(rule) == "通用"]
    specific_rules = [rule for rule in all_rules if _rule_contract_type(rule) != "通用"]

    ok_by_status = 200 <= int(status_code or 0) < 300
    return {
        "success": ok_by_status,
        "common_rules": common_rules,
        "specific_rules": specific_rules,
        "diff_texts": parsed_diff_texts,
        "total_rules": len(all_rules),
        "message": "" if ok_by_status else ERR_RULES_REQUEST_FAILED,
    }


async def analyze_diff_risks_with_llm(
    old_text: str,
    new_text: str,
    diff_texts: list[dict[str, Any]],
    common_rules: list[dict[str, Any]],
    specific_rules: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze risks for identified differences with one unified LLM node."""

    if not diff_texts:
        return _success_empty()

    prompt = build_analyze_diff_risks_prompt(
        old_text=old_text,
        new_text=new_text,
        diff_texts=diff_texts,
        common_rules=common_rules,
        specific_rules=specific_rules,
    )

    try:
        update_debug_context(step="analyze_diff_risks")
        llm_started_at = asyncio.get_running_loop().time()
        raw_result = await chat_completion(prompt, json_mode=True)
        llm_latency_ms = round((asyncio.get_running_loop().time() - llm_started_at) * 1000.0, 3)
        update_debug_context(
            risk_llm_latency_ms=llm_latency_ms,
            risk_raw_output_preview=_preview_text(raw_result),
            risk_request_mode="json_mode_only",
        )
    except Exception as exc:
        llm_latency_ms = round((asyncio.get_running_loop().time() - llm_started_at) * 1000.0, 3)
        update_debug_context(
            risk_llm_latency_ms=llm_latency_ms,
            risk_exception_type=type(exc).__name__,
            risk_exception_message=str(exc),
            risk_request_mode="json_mode_only",
        )
        return _failure(ERR_RISK_PARSE_FAILED)

    cleaned_output = _strip_markdown_code_block(raw_result).strip()
    update_debug_context(risk_cleaned_output_preview=_preview_text(cleaned_output))

    try:
        parsed = _parse_json_like(raw_result)
    except Exception as exc:
        update_debug_context(
            risk_json_parse_error=f"{type(exc).__name__}: {exc}",
        )
        return _failure(ERR_RISK_PARSE_FAILED)

    if not isinstance(parsed, dict) or not isinstance(parsed.get("enhanced"), list):
        update_debug_context(
            risk_invalid_result_type=type(parsed).__name__,
        )
        return _failure(ERR_RISK_PARSE_FAILED)

    update_debug_context(
        risk_node_output={
            "success": bool(parsed.get("success", True)),
            "enhanced": parsed.get("enhanced", []),
            "message": _string_value(parsed.get("message")),
            "total_risks": parsed.get("total_risks"),
        },
        risk_enhanced_count=len(parsed.get("enhanced", [])) if isinstance(parsed.get("enhanced"), list) else 0,
    )

    return normalize_compare_output(parsed, diff_texts)


def normalize_compare_output(
    raw_result: Any,
    source_diff_texts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Normalize final output and keep only success/enhanced/total_risks/message."""

    if not isinstance(raw_result, dict):
        return _failure(ERR_RISK_PARSE_FAILED)

    success = bool(raw_result.get("success", True))
    message = raw_result.get("message", "")
    if not isinstance(message, str):
        message = str(message)

    if not success:
        return _failure(message)

    raw_enhanced = raw_result.get("enhanced", [])
    if not isinstance(raw_enhanced, list):
        raw_enhanced = []

    if source_diff_texts is not None:
        enhanced = _merge_enhanced_with_diff_texts(raw_enhanced, source_diff_texts)
    else:
        enhanced = [_normalize_enhanced_item(item) for item in raw_enhanced if isinstance(item, dict)]

    total_risks = _coerce_total_risks(raw_result.get("total_risks"))
    if total_risks is None:
        total_risks = _compute_total_risks(enhanced)

    result = {
        "success": success,
        "enhanced": enhanced,
        "total_risks": total_risks,
        "message": message,
    }
    return {key: result[key] for key in FINAL_FIELDS}


def _success_empty() -> dict[str, Any]:
    return {
        "success": True,
        "enhanced": [],
        "total_risks": 0,
        "message": "",
    }


def _failure(message: str) -> dict[str, Any]:
    return {
        "success": False,
        "enhanced": [],
        "total_risks": 0,
        "message": message,
    }


def _parse_rule_body(body: Any) -> dict[str, Any]:
    if isinstance(body, dict):
        parsed: Any = body
    elif isinstance(body, str):
        if body.strip() == "":
            parsed = {}
        else:
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                raise ValueError(ERR_RULES_BODY_INVALID) from exc
    elif body is None:
        parsed = {}
    else:
        parsed = {}

    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError as exc:
            raise ValueError(ERR_RULES_BODY_INVALID) from exc

    return parsed if isinstance(parsed, dict) else {}


def _parse_diff_texts_value(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str) and value.strip():
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = []

    if not isinstance(value, list):
        return []

    return _normalize_diff_texts(value, validate_quotes=False)


def _parse_json_like(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        raise ValueError("Expected JSON string or object")

    text = _strip_markdown_code_block(value).strip()
    candidates = [text]
    extracted = _extract_json_candidate(text)
    if extracted != text:
        candidates.append(extracted)

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            parsed: Any = json.loads(candidate)
            while isinstance(parsed, str):
                parsed = json.loads(parsed)
            return parsed
        except json.JSONDecodeError as exc:
            last_error = exc

    raise ValueError("Unable to parse JSON") from last_error


def _strip_markdown_code_block(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json|JSON)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped


def _extract_json_candidate(text: str) -> str:
    object_start = text.find("{")
    object_end = text.rfind("}")
    array_start = text.find("[")
    array_end = text.rfind("]")

    object_candidate = text[object_start : object_end + 1] if object_start != -1 and object_end > object_start else ""
    array_candidate = text[array_start : array_end + 1] if array_start != -1 and array_end > array_start else ""

    if object_candidate and array_candidate:
        return object_candidate if object_start < array_start else array_candidate
    return object_candidate or array_candidate or text


async def _identify_differences_for_chunk(
    *,
    old_text: str,
    new_text: str,
    full_old_text: str,
    full_new_text: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prompt = build_identify_differences_prompt(old_text=old_text, new_text=new_text)
    llm_started_at = asyncio.get_running_loop().time()

    try:
        raw_result = await chat_completion(prompt, json_mode=True)
        llm_latency_ms = round((asyncio.get_running_loop().time() - llm_started_at) * 1000.0, 3)
    except Exception as exc:
        llm_latency_ms = round((asyncio.get_running_loop().time() - llm_started_at) * 1000.0, 3)
        update_debug_context(
            identify_llm_latency_ms=llm_latency_ms,
            identify_exception_type=type(exc).__name__,
            identify_exception_message=str(exc),
        )
        raise CompareWorkflowError(ERR_DIFF_PARSE_FAILED) from exc

    cleaned_output = _strip_markdown_code_block(raw_result).strip()

    try:
        parsed = _parse_json_like(raw_result)
    except Exception as exc:
        update_debug_context(
            identify_json_parse_error=f"{type(exc).__name__}: {exc}",
        )
        raise CompareWorkflowError(ERR_DIFF_PARSE_FAILED) from exc

    if isinstance(parsed, dict):
        diff_texts = parsed.get("diff_texts")
    elif isinstance(parsed, list):
        diff_texts = parsed
    else:
        diff_texts = None

    if not isinstance(diff_texts, list):
        update_debug_context(
            identify_json_parse_error="Parsed output does not contain a list diff_texts",
            identify_parsed_type=type(parsed).__name__,
        )
        raise CompareWorkflowError(ERR_DIFF_PARSE_FAILED)

    try:
        normalized = _normalize_diff_texts(
            diff_texts,
            old_text=full_old_text,
            new_text=full_new_text,
            validate_quotes=True,
        )
    except ValueError as exc:
        update_debug_context(
            identify_quote_validation_error=str(exc),
        )
        raise CompareWorkflowError(ERR_DIFF_PARSE_FAILED) from exc

    return normalized, {
        "latency_ms": llm_latency_ms,
        "raw_output_preview": _preview_text(raw_result),
        "cleaned_output_preview": _preview_text(cleaned_output),
    }


def _build_identify_chunks(old_text: str, new_text: str) -> list[dict[str, str]]:
    old_sections = _split_contract_sections(old_text)
    new_sections = _split_contract_sections(new_text)

    if len(old_sections) <= 1 and len(new_sections) <= 1:
        return [{"section_key": "__full__", "old_text": old_text, "new_text": new_text}]

    old_map = {section["key"]: section["text"] for section in old_sections}
    new_map = {section["key"]: section["text"] for section in new_sections}
    ordered_keys: list[str] = []
    seen: set[str] = set()

    for section in old_sections + new_sections:
        key = section["key"]
        if key not in seen:
            ordered_keys.append(key)
            seen.add(key)

    chunks: list[dict[str, str]] = []
    for key in ordered_keys:
        chunks.append(
            {
                "section_key": key,
                "old_text": old_map.get(key, ""),
                "new_text": new_map.get(key, ""),
            }
        )
    return chunks


def _split_contract_sections(text: str) -> list[dict[str, str]]:
    if not text.strip():
        return [{"key": "__empty__", "text": text}]

    normalized_text = text.replace("\r\n", "\n")
    lines = normalized_text.split("\n")
    header_pattern = re.compile(r"^(第[一二三四五六七八九十百零\d]+条|[一二三四五六七八九十百零]+、)\s*(.+)$")

    sections: list[dict[str, str]] = []
    current_key = "__preamble__"
    current_lines: list[str] = []
    duplicate_counter: dict[str, int] = {}

    def flush() -> None:
        if current_lines:
            sections.append({"key": current_key, "text": "\n".join(current_lines).strip()})

    for line in lines:
        stripped = line.strip()
        match = header_pattern.match(stripped)
        if match:
            flush()
            title = _normalize_section_title(match.group(2))
            duplicate_counter[title] = duplicate_counter.get(title, 0) + 1
            suffix = f"#{duplicate_counter[title]}" if duplicate_counter[title] > 1 else ""
            current_key = f"{title}{suffix}" or "__section__"
            current_lines = [line]
        else:
            current_lines.append(line)

    flush()
    return sections or [{"key": "__full__", "text": normalized_text}]


def _normalize_section_title(title: str) -> str:
    normalized = re.sub(r"\s+", "", title)
    normalized = normalized.replace("：", "").replace(":", "")
    return normalized or "__section__"


def _extract_diff_texts_from_analysis_text(text: str) -> list[dict[str, Any]] | None:
    normalized_text = text.replace("\r\n", "\n")
    blocks = re.split(r"\n(?=\d+\.\s)", normalized_text)
    extracted: list[dict[str, Any]] = []

    for block in blocks:
        stripped = block.strip()
        if not re.match(r"^\d+\.\s", stripped):
            continue

        change_type_match = re.search(r"\b(added|deleted|modified|moved)\b", stripped, flags=re.IGNORECASE)
        old_match = re.search(
            r'(?:^|\n)\s*-\s*(?:Old|旧版?|旧合同)\s*:\s*"([^"]+)"',
            stripped,
            flags=re.IGNORECASE,
        )
        new_match = re.search(
            r'(?:^|\n)\s*-\s*(?:New|新版?|新合同)\s*:\s*"([^"]+)"',
            stripped,
            flags=re.IGNORECASE,
        )
        change_match = re.search(
            r'(?:^|\n)\s*-\s*(?:Change|Changes|变化|改动)\s*:\s*(.+)',
            stripped,
            flags=re.IGNORECASE,
        )

        if not change_type_match and not old_match and not new_match:
            continue

        change_type = _normalize_change_type(
            change_type_match.group(1).lower() if change_type_match else "modified"
        )
        old_quote = old_match.group(1).strip() if old_match else ""
        new_quote = new_match.group(1).strip() if new_match else ""
        original = change_match.group(1).strip() if change_match else ""

        if not original:
            title_line = stripped.splitlines()[0]
            original = re.sub(r"^\d+\.\s*", "", title_line).strip()

        extracted.append(
            {
                "change_type": change_type,
                "old_quote": old_quote,
                "new_quote": new_quote,
                "original": original,
            }
        )

    return extracted or None


def _extract_risk_result_from_analysis_text(
    text: str,
    diff_texts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    normalized_text = text.replace("\r\n", "\n").strip()
    blocks = re.split(r"\n(?=\d+\.\s)", normalized_text)
    extracted: list[dict[str, Any]] = []

    for index, diff_item in enumerate(diff_texts):
        block = ""
        if index < len(blocks) and re.match(r"^\d+\.\s", blocks[index].strip()):
            block = blocks[index].strip()
        elif index + 1 < len(blocks) and re.match(r"^\d+\.\s", blocks[index + 1].strip()):
            block = blocks[index + 1].strip()

        extracted_item = _extract_single_risk_item_from_block(block, diff_item) if block else None
        if extracted_item is None:
            extracted_item = _build_default_risk_item(diff_item)
        extracted.append(extracted_item)

    if not extracted:
        return None

    total_risks = _extract_total_risks_from_text(normalized_text)
    return {
        "success": True,
        "enhanced": extracted,
        "message": "",
        "total_risks": total_risks if total_risks is not None else _compute_total_risks(extracted),
    }


def _extract_single_risk_item_from_block(
    block: str,
    diff_item: dict[str, Any],
) -> dict[str, Any] | None:
    text = block.strip()
    if not text:
        return None

    category = _extract_labeled_value(text, "Category", "分类", "风险分类", "类别")
    summary = _extract_labeled_value(text, "Summary", "摘要", "总结")
    evidence = _extract_labeled_value(text, "Evidence", "证据", "依据", "分析依据")
    impact = _extract_labeled_value(text, "Impact", "影响", "可能影响")
    suggestion = _extract_labeled_value(text, "Suggestion", "建议", "处理建议")
    risk_level_raw = _extract_labeled_value(text, "Risk Level", "Risk", "风险等级", "风险级别")

    item = _build_default_risk_item(diff_item)

    if category:
        item["category"] = category
    if summary:
        item["summary"] = summary
    if evidence:
        item["evidence"] = evidence
    if impact:
        item["impact"] = impact
    if suggestion:
        item["suggestion"] = suggestion
    if risk_level_raw:
        item["risk_level"] = _normalize_risk_level(_normalize_risk_level_text(risk_level_raw))
    else:
        inferred_risk_level = _infer_risk_level_from_text(text)
        if inferred_risk_level:
            item["risk_level"] = inferred_risk_level

    return item


def _extract_labeled_value(text: str, *labels: str) -> str:
    for label in labels:
        pattern = rf"(?:^|\n)\s*(?:[-*]\s*)?{re.escape(label)}\s*[:：]\s*(.+)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            value = re.split(r"\n\s*(?:[-*]\s*)?(?:Category|Summary|Evidence|Impact|Suggestion|Risk Level|Risk|分类|风险分类|类别|摘要|总结|证据|依据|分析依据|影响|可能影响|建议|处理建议|风险等级|风险级别)\s*[:：]", value, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            if value:
                return value
    return ""


def _extract_total_risks_from_text(text: str) -> int | None:
    match = re.search(r"(?:total_risks|total risks|风险总数|重点风险数量)\s*[:：]\s*(\d+)", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _normalize_risk_level_text(value: str) -> str:
    lowered = value.strip().lower()
    if "high" in lowered or "高" in value:
        return "high"
    if "medium" in lowered or "中" in value:
        return "medium"
    if "low" in lowered or "低" in value:
        return "low"
    return value.strip()


def _infer_risk_level_from_text(text: str) -> str | None:
    lowered = text.lower()
    if "high" in lowered or "高风险" in text:
        return "high"
    if "medium" in lowered or "中风险" in text:
        return "medium"
    if "low" in lowered or "低风险" in text:
        return "low"
    return None


def _build_default_risk_result(diff_texts: list[dict[str, Any]]) -> dict[str, Any]:
    enhanced = [_build_default_risk_item(diff_item) for diff_item in diff_texts]
    return {
        "success": True,
        "enhanced": enhanced,
        "message": "",
        "total_risks": _compute_total_risks(enhanced),
    }


def _build_default_risk_item(diff_item: dict[str, Any]) -> dict[str, Any]:
    item = {
        "original": _string_value(diff_item.get("original")),
        "change_type": _normalize_change_type(diff_item.get("change_type")),
        "old_quote": _string_value(diff_item.get("old_quote")),
        "new_quote": _string_value(diff_item.get("new_quote")),
        "category": _infer_category_from_diff(diff_item),
        "summary": _string_value(diff_item.get("original")),
        "risk_level": _infer_risk_level_from_diff(diff_item),
        "evidence": _build_default_evidence(diff_item),
        "impact": "该改动可能影响合同履行或双方权利义务，建议结合业务背景复核。",
        "suggestion": _infer_default_suggestion(diff_item),
    }
    return {key: item[key] for key in ENHANCED_FIELDS}


def _infer_category_from_diff(diff_item: dict[str, Any]) -> str:
    text = "".join(_string_value(diff_item.get(key)) for key in ("original", "old_quote", "new_quote"))
    category_rules = (
        ("付款条款", ("付款", "支付")),
        ("合同金额", ("金额", "价款", "合同总价", "价格")),
        ("发票条款", ("发票",)),
        ("税费承担", ("税", "税费")),
        ("验收条款", ("验收",)),
        ("交付条款", ("交付", "交货")),
        ("违约责任", ("违约", "赔偿")),
        ("解除终止", ("解除", "终止")),
        ("保密义务", ("保密",)),
        ("知识产权归属", ("知识产权", "著作权", "专利", "成果归属")),
        ("争议解决", ("争议", "仲裁", "法院", "管辖")),
    )
    for category, keywords in category_rules:
        if any(keyword in text for keyword in keywords):
            return category
    if _normalize_change_type(diff_item.get("change_type")) == "moved":
        return "条款位置"
    return "其他"


def _infer_risk_level_from_diff(diff_item: dict[str, Any]) -> str:
    category = _infer_category_from_diff(diff_item)
    if category in {"合同金额", "付款条款", "违约责任", "验收条款", "争议解决", "知识产权归属"}:
        return "medium"
    if _normalize_change_type(diff_item.get("change_type")) == "moved":
        return "low"
    return "low"


def _infer_default_suggestion(diff_item: dict[str, Any]) -> str:
    if _is_non_substantive_change(_build_default_risk_item_minimal(diff_item)):
        return DEFAULT_FORMAT_SUGGESTION
    return DEFAULT_REVIEW_SUGGESTION


def _build_default_risk_item_minimal(diff_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": _infer_category_from_diff(diff_item),
        "summary": _string_value(diff_item.get("original")),
        "original": _string_value(diff_item.get("original")),
        "impact": "",
        "suggestion": DEFAULT_REVIEW_SUGGESTION,
        "change_type": _normalize_change_type(diff_item.get("change_type")),
    }


def _normalize_diff_texts(
    diff_texts: list[Any],
    old_text: str = "",
    new_text: str = "",
    validate_quotes: bool = False,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []

    for raw_item in diff_texts:
        if not isinstance(raw_item, dict):
            continue

        change_type = _normalize_change_type(raw_item.get("change_type"))
        old_quote = _string_value(raw_item.get("old_quote"))
        new_quote = _string_value(raw_item.get("new_quote"))

        if change_type == "added":
            old_quote = ""
        elif change_type == "deleted":
            new_quote = ""

        item = {
            "change_type": change_type,
            "old_quote": old_quote,
            "new_quote": new_quote,
            "original": _string_value(raw_item.get("original")),
        }

        if validate_quotes and not _diff_quotes_are_valid(item, old_text=old_text, new_text=new_text):
            raise ValueError("Diff quote cannot be located in source text")

        normalized.append(item)

    return normalized


def _diff_quotes_are_valid(item: dict[str, Any], old_text: str, new_text: str) -> bool:
    change_type = item["change_type"]
    old_quote = item["old_quote"]
    new_quote = item["new_quote"]

    if change_type == "added":
        return old_quote == "" and bool(new_quote) and new_quote in new_text
    if change_type == "deleted":
        return new_quote == "" and bool(old_quote) and old_quote in old_text
    return bool(old_quote) and old_quote in old_text and bool(new_quote) and new_quote in new_text


def _normalize_change_type(value: Any) -> str:
    return value if isinstance(value, str) and value in CHANGE_TYPES else "modified"


def _normalize_risk_level(value: Any) -> str:
    if isinstance(value, str):
        value = {"高": "high", "中": "medium", "低": "low"}.get(value, value)
    return value if isinstance(value, str) and value in RISK_LEVELS else "low"


def _normalize_enhanced_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "original": _string_value(item.get("original")),
        "change_type": _normalize_change_type(item.get("change_type")),
        "old_quote": _string_value(item.get("old_quote")),
        "new_quote": _string_value(item.get("new_quote")),
        "category": _string_value(item.get("category")) or "其他",
        "summary": _string_value(item.get("summary")),
        "risk_level": _normalize_risk_level(item.get("risk_level")),
        "evidence": _string_value(item.get("evidence")),
        "impact": _string_value(item.get("impact")),
        "suggestion": _string_value(item.get("suggestion")) or DEFAULT_REVIEW_SUGGESTION,
    }
    return {key: normalized[key] for key in ENHANCED_FIELDS}


def _merge_enhanced_with_diff_texts(
    raw_enhanced: list[Any],
    source_diff_texts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enhanced: list[dict[str, Any]] = []

    for index, diff_item in enumerate(source_diff_texts):
        raw_item = raw_enhanced[index] if index < len(raw_enhanced) and isinstance(raw_enhanced[index], dict) else {}
        normalized = _normalize_enhanced_item(raw_item)
        normalized["original"] = _string_value(diff_item.get("original"))
        normalized["change_type"] = _normalize_change_type(diff_item.get("change_type"))
        normalized["old_quote"] = _string_value(diff_item.get("old_quote"))
        normalized["new_quote"] = _string_value(diff_item.get("new_quote"))

        if not normalized["summary"]:
            normalized["summary"] = normalized["original"]
        if not normalized["evidence"]:
            normalized["evidence"] = _build_default_evidence(normalized)
        if not normalized["impact"]:
            normalized["impact"] = "该改动可能影响合同履行或双方权利义务，建议结合业务背景复核。"
        if not normalized["suggestion"]:
            normalized["suggestion"] = DEFAULT_REVIEW_SUGGESTION

        enhanced.append({key: normalized[key] for key in ENHANCED_FIELDS})

    return enhanced


def _build_default_evidence(item: dict[str, Any]) -> str:
    old_quote = item.get("old_quote", "")
    new_quote = item.get("new_quote", "")
    if old_quote and new_quote:
        return f"旧合同约定：{old_quote}；新合同约定：{new_quote}"
    if new_quote:
        return f"新合同新增：{new_quote}"
    if old_quote:
        return f"旧合同删除：{old_quote}"
    return ""


def _compute_total_risks(enhanced: list[dict[str, Any]]) -> int:
    total = 0
    for item in enhanced:
        risk_level = item.get("risk_level")
        if risk_level in {"high", "medium"}:
            total += 1
            continue
        if risk_level == "low" and not _is_non_substantive_change(item):
            total += 1
    return total


def _coerce_total_risks(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if value < 0:
            return None
        if value.is_integer():
            return int(value)
        return None
    return None


def _is_non_substantive_change(item: dict[str, Any]) -> bool:
    text = "".join(
        _string_value(item.get(field))
        for field in ("category", "summary", "original", "impact", "suggestion")
    )
    has_non_substantive = any(keyword in text for keyword in NON_SUBSTANTIVE_KEYWORDS)
    has_substantive = any(keyword in text for keyword in SUBSTANTIVE_KEYWORDS)

    if item.get("suggestion") == DEFAULT_FORMAT_SUGGESTION:
        return True
    if item.get("change_type") == "moved" and has_non_substantive and not has_substantive:
        return True
    return has_non_substantive and not has_substantive


def _rule_contract_type(rule: Any) -> str | None:
    return rule.get("contract_type") if isinstance(rule, dict) else None


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _preview_text(value: Any, limit: int = 1000) -> str:
    text = _string_value(value)
    if len(text) <= limit:
        return text
    return text[:limit]
