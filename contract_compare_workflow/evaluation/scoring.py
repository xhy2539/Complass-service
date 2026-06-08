"""Scoring helpers for compare workflow evaluation."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any


TOP_LEVEL_FIELDS = ("success", "enhanced", "total_risks", "message")
ENHANCED_FIELDS = (
    "category",
    "change_type",
    "evidence",
    "impact",
    "new_quote",
    "old_quote",
    "original",
    "risk_level",
    "suggestion",
    "summary",
)
ALLOWED_CHANGE_TYPES = {"added", "deleted", "modified", "moved"}
ALLOWED_RISK_LEVELS = {"high", "medium", "low"}
INTERNAL_LEAK_FIELDS = {"diff_list", "stats", "addCount", "deleteCount", "modifyCount", "contract_type"}
DEFAULT_REVIEW_SUGGESTION = "建议人工复核该改动是否符合业务预期"
DEFAULT_FORMAT_SUGGESTION = "无需修改，建议人工确认"


def load_gold_cases(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("gold_cases.json 格式错误：cases 必须是数组")
    return cases


def build_stub_enhanced(case: dict[str, Any]) -> list[dict[str, Any]]:
    enhanced: list[dict[str, Any]] = []
    for diff in case.get("diff_items", []):
        stub_output = diff.get("stub_output", {})
        enhanced.append(
            {
                "category": _string(stub_output.get("category")),
                "change_type": _string(diff.get("change_type")),
                "evidence": _string(stub_output.get("evidence")),
                "impact": _string(stub_output.get("impact")),
                "new_quote": _string(diff.get("new_quote")),
                "old_quote": _string(diff.get("old_quote")),
                "original": _string(stub_output.get("original")) or _default_original(diff),
                "risk_level": _string(stub_output.get("risk_level")),
                "suggestion": _string(stub_output.get("suggestion")),
                "summary": _string(stub_output.get("summary")),
            }
        )
    return enhanced


def evaluate_case(
    *,
    case: dict[str, Any],
    response: dict[str, Any],
    trace: dict[str, Any],
) -> dict[str, Any]:
    predicted = response.get("enhanced", []) if isinstance(response.get("enhanced"), list) else []
    gold_diffs = case.get("diff_items", [])

    schema_ok, schema_errors = _check_schema(response)
    types_ok, type_errors = _check_types(response)
    enum_ok, enum_errors = _check_enums(predicted)
    leaks = [field for field in INTERNAL_LEAK_FIELDS if field in response]

    matches, unmatched_gold, unmatched_pred = _match_diffs(gold_diffs, predicted)

    old_hits, old_total = _quote_hits(predicted, case.get("old_text", ""), "old_quote")
    new_hits, new_total = _quote_hits(predicted, case.get("new_text", ""), "new_quote")

    change_type_correct = 0
    quote_preserved = 0
    original_fact_hits = 0
    category_hits = 0
    risk_level_hits = 0
    suggestion_hits = 0

    for gold_diff, predicted_item in matches:
        if predicted_item.get("change_type") == gold_diff.get("change_type"):
            change_type_correct += 1
        if (
            predicted_item.get("old_quote", "") == gold_diff.get("old_quote", "")
            and predicted_item.get("new_quote", "") == gold_diff.get("new_quote", "")
        ):
            quote_preserved += 1
        if _original_covers_facts(predicted_item.get("original", ""), gold_diff.get("original_required_facts", [])):
            original_fact_hits += 1
        if predicted_item.get("category") in gold_diff.get("acceptable_categories", []):
            category_hits += 1
        if predicted_item.get("risk_level") in gold_diff.get("acceptable_risk_levels", []):
            risk_level_hits += 1
        if _suggestion_matches(predicted_item.get("suggestion", ""), gold_diff):
            suggestion_hits += 1

    success = bool(response.get("success"))
    success_message_ok = (
        (success and response.get("message") == "")
        or ((not success) and isinstance(response.get("message"), str) and response.get("message", "").strip())
    )

    enhanced_coverage_expected = bool(trace.get("parsed_diff_texts"))
    enhanced_coverage_pass = _enhanced_covers_diff_texts(response, trace)

    non_substantive_expectation = case.get("non_substantive_expectation")
    non_substantive_pass = _score_non_substantive_case(
        expectation=non_substantive_expectation,
        case=case,
        response=response,
    )

    counts = {
        "gold_diff_total": len(gold_diffs),
        "pred_diff_total": len(predicted),
        "matched_diff_total": len(matches),
        "matched_change_type_correct": change_type_correct,
        "matched_quote_preserved": quote_preserved,
        "matched_original_fact_hits": original_fact_hits,
        "matched_category_hits": category_hits,
        "matched_risk_level_hits": risk_level_hits,
        "matched_suggestion_hits": suggestion_hits,
        "old_quote_hit_total": old_total,
        "old_quote_hits": old_hits,
        "new_quote_hit_total": new_total,
        "new_quote_hits": new_hits,
        "enhanced_coverage_total": 1 if enhanced_coverage_expected else 0,
        "enhanced_coverage_hits": 1 if enhanced_coverage_expected and enhanced_coverage_pass else 0,
        "non_substantive_total": 1 if non_substantive_expectation else 0,
        "non_substantive_hits": 1 if non_substantive_expectation and non_substantive_pass else 0,
        "success_case_total": 1 if success else 0,
        "total_risks_hits": 1 if success and response.get("total_risks") == case.get("expected_total_risks") else 0,
    }

    metrics = {
        "schema_pass": schema_ok,
        "field_type_pass": types_ok,
        "enum_pass": enum_ok,
        "success_message_consistency": bool(success_message_ok),
        "internal_field_leak": bool(leaks),
        "total_risks_pass": bool(counts["total_risks_hits"]),
        "enhanced_coverage_pass": enhanced_coverage_pass if enhanced_coverage_expected else None,
        "non_substantive_pass": non_substantive_pass,
        "latency_ms": trace.get("latency_ms", 0.0),
    }

    return {
        "case_id": case.get("case_id"),
        "run_metrics": metrics,
        "counts": counts,
        "schema_errors": schema_errors,
        "type_errors": type_errors,
        "enum_errors": enum_errors,
        "leaked_fields": leaks,
        "unmatched_gold_diff_ids": [diff.get("diff_id") for diff in unmatched_gold],
        "unmatched_pred_indexes": unmatched_pred,
        "trace": trace,
        "needs_manual_review": bool(unmatched_gold or unmatched_pred),
    }


def aggregate_results(run_entries: list[dict[str, Any]], repeat: int) -> dict[str, Any]:
    if not run_entries:
        return {}

    total_runs = len(run_entries)
    schema_pass = sum(1 for entry in run_entries if entry["evaluation"]["run_metrics"]["schema_pass"])
    field_type_pass = sum(1 for entry in run_entries if entry["evaluation"]["run_metrics"]["field_type_pass"])
    enum_pass = sum(1 for entry in run_entries if entry["evaluation"]["run_metrics"]["enum_pass"])
    success_message_pass = sum(
        1 for entry in run_entries if entry["evaluation"]["run_metrics"]["success_message_consistency"]
    )
    leak_count = sum(1 for entry in run_entries if entry["evaluation"]["run_metrics"]["internal_field_leak"])

    totals = Counter()
    for entry in run_entries:
        totals.update(entry["evaluation"]["counts"])

    latency_by_bucket: dict[str, list[float]] = defaultdict(list)
    for entry in run_entries:
        latency_by_bucket[entry["case"]["length_bucket"]].append(float(entry["trace"].get("latency_ms", 0.0)))

    stability = _aggregate_stability(run_entries, repeat)

    summary = {
        "case_count": len({entry["case"]["case_id"] for entry in run_entries}),
        "run_count": total_runs,
        "schema_pass_rate": _ratio(schema_pass, total_runs),
        "field_type_pass_rate": _ratio(field_type_pass, total_runs),
        "enum_pass_rate": _ratio(enum_pass, total_runs),
        "success_message_consistency": _ratio(success_message_pass, total_runs),
        "internal_field_leak_rate": _ratio(leak_count, total_runs),
        "diff_recall": _ratio(totals["matched_diff_total"], totals["gold_diff_total"]),
        "diff_precision": _ratio(totals["matched_diff_total"], totals["pred_diff_total"]),
        "change_type_accuracy": _ratio(totals["matched_change_type_correct"], totals["matched_diff_total"]),
        "old_quote_hit_rate": _ratio(totals["old_quote_hits"], totals["old_quote_hit_total"]),
        "new_quote_hit_rate": _ratio(totals["new_quote_hits"], totals["new_quote_hit_total"]),
        "quote_preservation_rate": _ratio(totals["matched_quote_preserved"], totals["matched_diff_total"]),
        "original_fact_coverage": _ratio(totals["matched_original_fact_hits"], totals["matched_diff_total"]),
        "category_accuracy": _ratio(totals["matched_category_hits"], totals["matched_diff_total"]),
        "risk_level_accuracy": _ratio(totals["matched_risk_level_hits"], totals["matched_diff_total"]),
        "suggestion_template_hit_rate": _ratio(totals["matched_suggestion_hits"], totals["matched_diff_total"]),
        "total_risks_accuracy": _ratio(totals["total_risks_hits"], totals["success_case_total"]),
        "non_substantive_filter_accuracy": _ratio(totals["non_substantive_hits"], totals["non_substantive_total"]),
        "enhanced_coverage_rate": _ratio(totals["enhanced_coverage_hits"], totals["enhanced_coverage_total"]),
        "latency": {
            bucket: {
                "avg_ms": round(sum(values) / len(values), 3),
                "p95_ms": round(_percentile(values, 95), 3),
                "max_ms": round(max(values), 3),
            }
            for bucket, values in latency_by_bucket.items()
            if values
        },
        "stability": stability,
    }
    return summary


def print_console_summary(summary: dict[str, Any], output_path: str) -> None:
    print("")
    print("=== Compare Workflow Evaluation Summary ===")
    print(f"Cases: {summary.get('case_count', 0)}")
    print(f"Runs: {summary.get('run_count', 0)}")
    print(f"schema_pass_rate: {summary.get('schema_pass_rate', 0):.3f}")
    print(f"field_type_pass_rate: {summary.get('field_type_pass_rate', 0):.3f}")
    print(f"enum_pass_rate: {summary.get('enum_pass_rate', 0):.3f}")
    print(f"diff_recall: {summary.get('diff_recall', 0):.3f}")
    print(f"diff_precision: {summary.get('diff_precision', 0):.3f}")
    print(f"change_type_accuracy: {summary.get('change_type_accuracy', 0):.3f}")
    print(f"old_quote_hit_rate: {summary.get('old_quote_hit_rate', 0):.3f}")
    print(f"new_quote_hit_rate: {summary.get('new_quote_hit_rate', 0):.3f}")
    print(f"original_fact_coverage: {summary.get('original_fact_coverage', 0):.3f}")
    print(f"suggestion_template_hit_rate: {summary.get('suggestion_template_hit_rate', 0):.3f}")
    print(f"total_risks_accuracy: {summary.get('total_risks_accuracy', 0):.3f}")
    print(f"non_substantive_filter_accuracy: {summary.get('non_substantive_filter_accuracy', 0):.3f}")
    print(f"enhanced_coverage_rate: {summary.get('enhanced_coverage_rate', 0):.3f}")
    print("latency_by_length:")
    for bucket, bucket_stats in summary.get("latency", {}).items():
        print(
            f"  - {bucket}: avg={bucket_stats['avg_ms']:.3f}ms "
            f"p95={bucket_stats['p95_ms']:.3f}ms max={bucket_stats['max_ms']:.3f}ms"
        )
    if summary.get("stability"):
        print("stability:")
        print(
            "  - exact_match_rate(avg): "
            f"{summary['stability'].get('exact_match_rate_avg', 0):.3f}"
        )
        print(
            "  - structure_rate(avg): "
            f"{summary['stability'].get('structure_rate_avg', 0):.3f}"
        )
        print(
            "  - quote_rate(avg): "
            f"{summary['stability'].get('quote_rate_avg', 0):.3f}"
        )
    print(f"results_json: {output_path}")


def _check_schema(response: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if tuple(response.keys()) != TOP_LEVEL_FIELDS:
        if set(response.keys()) != set(TOP_LEVEL_FIELDS):
            errors.append("top_level_fields")
    enhanced = response.get("enhanced")
    if isinstance(enhanced, list):
        for index, item in enumerate(enhanced):
            if not isinstance(item, dict):
                errors.append(f"enhanced[{index}]_not_object")
                continue
            if set(item.keys()) != set(ENHANCED_FIELDS):
                errors.append(f"enhanced[{index}]_fields")
    else:
        errors.append("enhanced_not_list")
    return not errors, errors


def _check_types(response: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(response.get("success"), bool):
        errors.append("success")
    if not isinstance(response.get("enhanced"), list):
        errors.append("enhanced")
    if not isinstance(response.get("total_risks"), int):
        errors.append("total_risks")
    if not isinstance(response.get("message"), str):
        errors.append("message")
    if isinstance(response.get("enhanced"), list):
        for index, item in enumerate(response["enhanced"]):
            if not isinstance(item, dict):
                continue
            for field_name in ENHANCED_FIELDS:
                if field_name in item and not isinstance(item[field_name], str):
                    errors.append(f"enhanced[{index}].{field_name}")
    return not errors, errors


def _check_enums(predicted: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for index, item in enumerate(predicted):
        if item.get("change_type") not in ALLOWED_CHANGE_TYPES:
            errors.append(f"enhanced[{index}].change_type")
        if item.get("risk_level") not in ALLOWED_RISK_LEVELS:
            errors.append(f"enhanced[{index}].risk_level")
    return not errors, errors


def _match_diffs(
    gold_diffs: list[dict[str, Any]],
    predicted: list[dict[str, Any]],
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], list[dict[str, Any]], list[int]]:
    used_indexes: set[int] = set()
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    unmatched_gold: list[dict[str, Any]] = []

    for gold_diff in gold_diffs:
        matched_index = _find_match_index(gold_diff, predicted, used_indexes)
        if matched_index is None:
            unmatched_gold.append(gold_diff)
            continue
        used_indexes.add(matched_index)
        matches.append((gold_diff, predicted[matched_index]))

    unmatched_pred = [index for index in range(len(predicted)) if index not in used_indexes]
    return matches, unmatched_gold, unmatched_pred


def _find_match_index(
    gold_diff: dict[str, Any],
    predicted: list[dict[str, Any]],
    used_indexes: set[int],
) -> int | None:
    gold_change = gold_diff.get("change_type")
    gold_old = gold_diff.get("old_quote", "")
    gold_new = gold_diff.get("new_quote", "")

    for index, item in enumerate(predicted):
        if index in used_indexes:
            continue
        if item.get("change_type") != gold_change:
            continue
        if gold_change == "added":
            if item.get("old_quote", "") == "" and item.get("new_quote", "") == gold_new:
                return index
        elif gold_change == "deleted":
            if item.get("new_quote", "") == "" and item.get("old_quote", "") == gold_old:
                return index
        else:
            if item.get("old_quote", "") == gold_old and item.get("new_quote", "") == gold_new:
                return index
    return None


def _quote_hits(items: list[dict[str, Any]], source_text: str, field_name: str) -> tuple[int, int]:
    hits = 0
    total = 0
    for item in items:
        quote = item.get(field_name, "")
        if not isinstance(quote, str) or not quote:
            continue
        total += 1
        if quote in source_text:
            hits += 1
    return hits, total


def _original_covers_facts(original: str, required_facts: list[Any]) -> bool:
    if not required_facts:
        return True
    for fact in required_facts:
        if isinstance(fact, str):
            if fact not in original:
                return False
            continue
        if isinstance(fact, list):
            options = [item for item in fact if isinstance(item, str) and item]
            if not options or not any(option in original for option in options):
                return False
            continue
        return False
    return True


def _suggestion_matches(suggestion: str, gold_diff: dict[str, Any]) -> bool:
    mode = gold_diff.get("suggestion_mode")
    if mode == "rule_template":
        template = _string(gold_diff.get("expected_suggestion_template"))
        return bool(template) and template in suggestion
    if mode == "default_review":
        return suggestion == DEFAULT_REVIEW_SUGGESTION
    if mode == "default_format":
        return suggestion == DEFAULT_FORMAT_SUGGESTION
    return True


def _enhanced_covers_diff_texts(response: dict[str, Any], trace: dict[str, Any]) -> bool:
    diff_texts = trace.get("parsed_diff_texts") or []
    enhanced = response.get("enhanced") if isinstance(response.get("enhanced"), list) else []
    if not diff_texts:
        return False
    if len(diff_texts) != len(enhanced):
        return False
    for diff_item, enhanced_item in zip(diff_texts, enhanced):
        if enhanced_item.get("change_type") != diff_item.get("change_type"):
            return False
        if enhanced_item.get("old_quote") != diff_item.get("old_quote"):
            return False
        if enhanced_item.get("new_quote") != diff_item.get("new_quote"):
            return False
    return True


def _score_non_substantive_case(
    *,
    expectation: str | None,
    case: dict[str, Any],
    response: dict[str, Any],
) -> bool | None:
    if not expectation:
        return None
    if expectation == "filtered":
        return bool(response.get("success")) and response.get("total_risks") == 0 and response.get("enhanced") == []
    if expectation == "low_retained":
        enhanced = response.get("enhanced") if isinstance(response.get("enhanced"), list) else []
        return (
            bool(response.get("success"))
            and response.get("total_risks") == case.get("expected_total_risks")
            and all(item.get("risk_level") == "low" for item in enhanced)
        )
    return False


def _aggregate_stability(run_entries: list[dict[str, Any]], repeat: int) -> dict[str, Any]:
    if repeat <= 1:
        return {}

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in run_entries:
        grouped[entry["case"]["case_id"]].append(entry)

    exact_rates: list[float] = []
    structure_rates: list[float] = []
    quote_rates: list[float] = []

    per_case: dict[str, Any] = {}

    for case_id, entries in grouped.items():
        response_counter = Counter(_canonical_json(entry["response"]) for entry in entries)
        structure_counter = Counter(_structure_signature(entry["response"]) for entry in entries)
        quote_counter = Counter(_quote_signature(entry["response"]) for entry in entries)

        exact_rate = _ratio(max(response_counter.values()), len(entries))
        structure_rate = _ratio(max(structure_counter.values()), len(entries))
        quote_rate = _ratio(max(quote_counter.values()), len(entries))

        exact_rates.append(exact_rate)
        structure_rates.append(structure_rate)
        quote_rates.append(quote_rate)

        per_case[case_id] = {
            "repeat_count": len(entries),
            "exact_match_rate": exact_rate,
            "structure_rate": structure_rate,
            "quote_rate": quote_rate,
        }

    return {
        "repeat": repeat,
        "exact_match_rate_avg": _ratio(sum(exact_rates), len(exact_rates)),
        "structure_rate_avg": _ratio(sum(structure_rates), len(structure_rates)),
        "quote_rate_avg": _ratio(sum(quote_rates), len(quote_rates)),
        "per_case": per_case,
    }


def _structure_signature(response: dict[str, Any]) -> str:
    enhanced = response.get("enhanced") if isinstance(response.get("enhanced"), list) else []
    signature = {
        "top_keys": list(response.keys()),
        "success": response.get("success"),
        "enhanced_len": len(enhanced),
        "item_keys": [sorted(item.keys()) if isinstance(item, dict) else [] for item in enhanced],
        "change_types": [item.get("change_type") for item in enhanced if isinstance(item, dict)],
        "risk_levels": [item.get("risk_level") for item in enhanced if isinstance(item, dict)],
    }
    return _canonical_json(signature)


def _quote_signature(response: dict[str, Any]) -> str:
    enhanced = response.get("enhanced") if isinstance(response.get("enhanced"), list) else []
    signature = sorted(
        (
            item.get("change_type", ""),
            item.get("old_quote", ""),
            item.get("new_quote", ""),
        )
        for item in enhanced
        if isinstance(item, dict)
    )
    return _canonical_json(signature)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _percentile(values: list[float], percent: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (percent / 100) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _ratio(numerator: float, denominator: int) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 6)


def _default_original(diff: dict[str, Any]) -> str:
    required_facts = diff.get("original_required_facts") or []
    if required_facts:
        flattened: list[str] = []
        for item in required_facts:
            if isinstance(item, str) and item:
                flattened.append(item)
            elif isinstance(item, list):
                options = [_string(option) for option in item if _string(option)]
                if options:
                    flattened.append(options[0])
        return "；".join(flattened)
    return ""


def _string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)
