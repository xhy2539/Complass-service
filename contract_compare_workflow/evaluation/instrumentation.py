"""Non-invasive instrumentation helpers for compare workflow evaluation."""

from __future__ import annotations

import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from contract_compare_workflow import workflow


@dataclass
class InvocationTrace:
    contract_type: str = ""
    diff_texts: list[dict[str, Any]] = field(default_factory=list)
    diff_node_output: dict[str, Any] = field(default_factory=dict)
    parsed_diff_texts: list[dict[str, Any]] = field(default_factory=list)
    common_rule_count: int = 0
    specific_rule_count: int = 0
    latency_ms: float = 0.0
    error: str = ""
    debug_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def run_compare_with_trace(
    *,
    old_text: str,
    new_text: str,
    task_type: str = "compare",
) -> tuple[dict[str, Any], InvocationTrace]:
    """Run compare_contracts while tracing internal observable data."""

    trace = InvocationTrace()

    original_classify = workflow.classify_compare_contract_type
    original_identify = workflow.identify_differences
    original_parse_rules = workflow.parse_compare_rule_response

    async def classify_wrapper(old_text: str, new_text: str) -> str:
        contract_type = await original_classify(old_text, new_text)
        trace.contract_type = contract_type
        return contract_type

    async def identify_wrapper(old_text: str, new_text: str) -> list[dict[str, Any]]:
        diff_texts = await original_identify(old_text, new_text)
        trace.diff_texts = [dict(item) for item in diff_texts]
        debug_context = workflow.get_debug_context()
        node_output = debug_context.get("identify_node_output")
        if isinstance(node_output, dict):
            trace.diff_node_output = dict(node_output)
        trace.debug_context = debug_context
        return diff_texts

    def parse_rules_wrapper(body: Any, status_code: int, diff_texts: Any) -> dict[str, Any]:
        parsed = original_parse_rules(body, status_code, diff_texts)
        trace.parsed_diff_texts = [dict(item) for item in parsed.get("diff_texts", [])]
        trace.common_rule_count = len(parsed.get("common_rules", []))
        trace.specific_rule_count = len(parsed.get("specific_rules", []))
        return parsed

    workflow.classify_compare_contract_type = classify_wrapper
    workflow.identify_differences = identify_wrapper
    workflow.parse_compare_rule_response = parse_rules_wrapper

    started_at = time.perf_counter()
    try:
        response = await workflow.compare_contracts(
            old_text=old_text,
            new_text=new_text,
            task_type=task_type,
        )
    except Exception as exc:
        trace.error = f"{type(exc).__name__}: {exc}"
        response = {
            "success": False,
            "enhanced": [],
            "total_risks": 0,
            "message": trace.error,
        }
    finally:
        trace.latency_ms = round((time.perf_counter() - started_at) * 1000.0, 3)
        if not trace.debug_context:
            trace.debug_context = workflow.get_debug_context()
            node_output = trace.debug_context.get("identify_node_output")
            if isinstance(node_output, dict):
                trace.diff_node_output = dict(node_output)
        workflow.classify_compare_contract_type = original_classify
        workflow.identify_differences = original_identify
        workflow.parse_compare_rule_response = original_parse_rules

    return response, trace
