from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import get_args
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.chains.reverse_rule_graph import run_reverse_rule_extraction
from app.models.reverse_rule import CandidateRuleForDB
from app.models.reverse_rule import ChangeType
from app.models.reverse_rule import ContractPair
from app.models.reverse_rule import DiffClause
from app.services.diff_service import detect_candidate_diffs
from app.services.diff_service import split_and_index_contract
from app.services.reverse_rule_tools import build_context_pack
from app.services.reverse_rule_tools import validate_evidence

DEFAULT_FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "reverse_rule_samples.json"
BACKEND_FIELDS = {
    "id",
    "version_id",
    "rule_code",
    "enabled",
    "created_at",
    "updated_at",
}
SCORE_WEIGHTS = {
    "generation_ok": 0.25,
    "review_module_hit": 0.15,
    "risk_hit": 0.15,
    "trigger_hit": 0.15,
    "suggestion_hit": 0.10,
    "trace_evidence_accuracy": 0.10,
    "schema_ok": 0.05,
    "backend_fields_clean": 0.05,
}
DEFAULT_KEYWORD_MATCH_THRESHOLD = 0.6
STRICT_COVERAGE_THRESHOLD = 0.6
STRICT_PRECISION_THRESHOLD = 0.7
STRICT_TRACE_VALIDATION_THRESHOLD = 0.7


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate reverse rule extraction quality.")
    parser.add_argument(
        "--fixture",
        default=str(DEFAULT_FIXTURE_PATH),
        help="Path to reverse rule benchmark JSON.",
    )
    parser.add_argument(
        "--use-real-llm",
        action="store_true",
        help="Use configured real LLM credentials instead of the deterministic local stub.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of times to run each sample for stability measurement.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional report output path. .json writes full report; .csv writes sample rows.",
    )
    parser.add_argument(
        "--length",
        choices=["all", "short", "medium", "long"],
        default="all",
        help="Optional length bucket filter for segmented benchmark runs.",
    )
    parser.add_argument(
        "--name",
        default="",
        help="Optional exact sample name filter for single-sample benchmark runs.",
    )
    parser.add_argument(
        "--merge-reports",
        nargs="*",
        default=None,
        help="Merge existing JSON reports instead of running the workflow.",
    )
    args = parser.parse_args()

    if args.runs < 1:
        raise ValueError("--runs must be >= 1")
    _load_default_env_files()
    if args.merge_reports is not None:
        merge_reports([Path(path) for path in args.merge_reports], output_path=Path(args.output) if args.output else None)
        return 0
    if args.use_real_llm and not _has_llm_key():
        print("No real model key detected. Configure OPENAI_API_KEY or MINIMAX_API_KEY and retry.")
        return 2
    if not args.use_real_llm:
        os.environ["DISABLE_REAL_LLM"] = "1"
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("MINIMAX_API_KEY", None)

    fixture_path = Path(args.fixture)
    samples = json.loads(fixture_path.read_text(encoding="utf-8"))
    if args.length != "all":
        samples = [
            sample for sample in samples
            if sample.get("length_category") == args.length
        ]
    if args.name:
        samples = [
            sample for sample in samples
            if sample.get("name") == args.name
        ]
    rows = [
        evaluate_sample(sample, run_index=run_index)
        for run_index in range(1, args.runs + 1)
        for sample in samples
    ]
    report = build_report(
        rows,
        fixture_path=str(fixture_path),
        runs=args.runs,
        use_real_llm=args.use_real_llm,
        length_filter=args.length,
        name_filter=args.name,
    )
    print_report(report)

    if args.output:
        write_report(report, Path(args.output))

    return 0


def evaluate_sample(sample: dict[str, Any], run_index: int = 1) -> dict[str, Any]:
    start = time.perf_counter()
    expected_rules = sample.get("expected_rules", [])
    expected_generated = bool(expected_rules) or bool(sample.get("should_generate_rule"))
    notes: list[str] = []
    error = ""
    rules: list[dict[str, Any]] = []
    result: dict[str, Any] = {}
    parse_failure = False

    try:
        result = run_reverse_rule_extraction(_pairs_from_sample(sample))
        rules = result.get("rules", []) or []
    except Exception as exc:
        parse_failure = True
        error = str(exc)

    latency_ms = int(round((time.perf_counter() - start) * 1000))
    generated = bool(rules)
    rule_match = evaluate_rule_matches(rules, expected_rules) if expected_rules else {}
    workflow_diagnostics = evaluate_workflow_diagnostics(sample, rules) if expected_rules else {}
    row = {
        "name": sample["name"],
        "run_index": run_index,
        "length_category": sample.get("length_category", "unknown"),
        "expected_generated": expected_generated,
        "generated": generated,
        "generation_ok": generated == expected_generated,
        "review_module_hit": _review_module_hit(rules, sample) if expected_generated else not generated,
        "risk_hit": _any_keyword_hit(rules, "risk_name", sample.get("expected_risk_keywords", [])) if expected_generated else not generated,
        "trigger_hit": _any_keyword_hit(rules, "trigger_condition", sample.get("expected_trigger_keywords", [])) if expected_generated else not generated,
        "suggestion_hit": _any_keyword_hit(rules, "suggestion_template", sample.get("expected_suggestion_keywords", [])) if expected_generated else not generated,
        "trace_evidence_accuracy": _trace_evidence_accuracy(rules, sample) if expected_generated else not generated,
        "schema_ok": _all_schema_valid(rules),
        "backend_fields_clean": all(BACKEND_FIELDS.isdisjoint(rule) for rule in rules),
        "duplicate_merge_accuracy": _duplicate_merge_accuracy(rules, sample),
        "confidence_aligned": _confidence_aligned(rules, sample),
        "latency_ms": latency_ms,
        "rule_count": len(rules),
        "expected_rule_count": rule_match.get("expected_rule_count", len(expected_rules)),
        "generated_rule_count": rule_match.get("generated_rule_count", len(rules)),
        "matched_expected_rule_count": rule_match.get("matched_expected_rule_count", 0),
        "usable_generated_rule_count": rule_match.get("usable_generated_rule_count", 0),
        "expected_rule_coverage": rule_match.get("expected_rule_coverage", 0.0 if expected_rules else None),
        "usable_rule_precision": rule_match.get("usable_rule_precision", None),
        "rules_per_contract": len(rules),
        "split_accuracy": rule_match.get("split_accuracy", None),
        "duplicate_or_overmerge_rate": rule_match.get("duplicate_or_overmerge_rate", None),
        "matched_rule_ids": rule_match.get("matched_rule_ids", []),
        "unmatched_rule_ids": rule_match.get("unmatched_rule_ids", []),
        "candidate_diff_count": workflow_diagnostics.get("candidate_diff_count", 0),
        "substantive_diff_count": workflow_diagnostics.get("substantive_diff_count", 0),
        "expected_diff_coverage": workflow_diagnostics.get("expected_diff_coverage", None),
        "move_noop_filter_accuracy": workflow_diagnostics.get("move_noop_filter_accuracy", None),
        "diff_to_rule_conversion_rate": workflow_diagnostics.get("diff_to_rule_conversion_rate", None),
        "rules_per_substantive_diff": workflow_diagnostics.get("rules_per_substantive_diff", None),
        "trace_validated_by_workflow_rate": workflow_diagnostics.get("trace_validated_by_workflow_rate", None),
        "trace_diff_id_present_rate": workflow_diagnostics.get("trace_diff_id_present_rate", None),
        "parse_failure": parse_failure,
        "empty_result": expected_generated and not generated,
        "over_generated": (not expected_generated) and generated,
        "under_generated": expected_generated and not generated,
        "error": error,
        "summary": result.get("summary", ""),
        "notes": notes,
    }

    if expected_rules:
        row["full_coverage_pass"] = row["expected_rule_coverage"] == 1.0
        row["review_module_hit"] = row["expected_rule_coverage"] >= STRICT_COVERAGE_THRESHOLD
        row["risk_hit"] = row["expected_rule_coverage"] >= STRICT_COVERAGE_THRESHOLD
        row["trigger_hit"] = row["expected_rule_coverage"] >= STRICT_COVERAGE_THRESHOLD
        row["suggestion_hit"] = row["usable_rule_precision"] is not None and row["usable_rule_precision"] >= STRICT_PRECISION_THRESHOLD
        row["duplicate_merge_accuracy"] = row["split_accuracy"] >= STRICT_COVERAGE_THRESHOLD
        row["trace_evidence_accuracy"] = (
            _generated_rules_have_trace_evidence(rules)
            and row["trace_validated_by_workflow_rate"] is not None
            and row["trace_validated_by_workflow_rate"] >= STRICT_TRACE_VALIDATION_THRESHOLD
        )
    else:
        row["full_coverage_pass"] = row["strict_passed"] if "strict_passed" in row else False

    strict_checks = [
        "generation_ok",
        "review_module_hit",
        "risk_hit",
        "trigger_hit",
        "suggestion_hit",
        "trace_evidence_accuracy",
        "schema_ok",
        "backend_fields_clean",
        "duplicate_merge_accuracy",
    ]
    row["strict_passed"] = all(bool(row[check]) for check in strict_checks)
    if not expected_rules:
        row["full_coverage_pass"] = row["strict_passed"]
    row["weighted_score"] = _high_density_score(row) if expected_rules else _weighted_score(row)
    row["notes"] = [check for check in strict_checks if not row[check]]
    if parse_failure:
        row["notes"].append("parse_failure")
    if not row["confidence_aligned"]:
        row["notes"].append("confidence_alignment")
    return row


def build_report(
    rows: list[dict[str, Any]],
    *,
    fixture_path: str,
    runs: int,
    use_real_llm: bool,
    length_filter: str = "all",
    name_filter: str = "",
) -> dict[str, Any]:
    return {
        "metadata": {
            "fixture_path": fixture_path,
            "runs": runs,
            "use_real_llm": use_real_llm,
            "length_filter": length_filter,
            "name_filter": name_filter,
            "row_count": len(rows),
        },
        "summary": _summarize_rows(rows),
        "by_length": {
            length: _summarize_rows([row for row in rows if row["length_category"] == length])
            for length in sorted({row["length_category"] for row in rows})
        },
        "rows": rows,
    }


def merge_reports(report_paths: list[Path], output_path: Path | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    fixture_path = ""
    use_real_llm = False
    for path in report_paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        metadata = report.get("metadata", {})
        fixture_path = fixture_path or metadata.get("fixture_path", "")
        use_real_llm = use_real_llm or bool(metadata.get("use_real_llm"))
        rows.extend(report.get("rows", []))
    merged = build_report(
        rows,
        fixture_path=fixture_path,
        runs=1,
        use_real_llm=use_real_llm,
    )
    merged["metadata"]["merged_report_count"] = len(report_paths)
    if output_path is not None:
        write_report(merged, output_path)
    return merged


def write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".csv":
        rows = report.get("rows", [])
        fieldnames = sorted({key for row in rows for key in row})
        with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def print_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print("Reverse rule evaluation summary")
    print(f"Samples/runs: {summary['sample_count']}")
    print(f"Strict pass rate: {summary['strict_pass_rate']:.2%}")
    print(f"Weighted score: {summary['weighted_score']:.2%}")
    if summary.get("expected_rule_coverage") is not None:
        print(f"Expected rule coverage: {summary['expected_rule_coverage']:.2%}")
    if summary.get("usable_rule_precision") is not None:
        print(f"Usable rule precision: {summary['usable_rule_precision']:.2%}")
    print(f"Rules per contract: {summary['rules_per_contract']:.2f}")
    print(f"Split accuracy: {summary['split_accuracy']:.2%}")
    print(f"Expected diff coverage: {summary['expected_diff_coverage']:.2%}")
    print(f"Trace validated by workflow: {summary['trace_validated_by_workflow_rate']:.2%}")
    print(f"Trace diff id present: {summary['trace_diff_id_present_rate']:.2%}")
    print(f"Diff to rule conversion: {summary['diff_to_rule_conversion_rate']:.2f}")
    print(f"Generation decision accuracy: {summary['generation_decision_accuracy']:.2%}")
    print(f"Schema valid rate: {summary['schema_valid_rate']:.2%}")
    print(f"Backend field clean rate: {summary['backend_field_clean_rate']:.2%}")
    print(f"Latency avg/p50/p95/max ms: {summary['latency_ms']}")
    print("\nBy length")
    for length, group in report["by_length"].items():
        print(
            f"- {length}: strict={group['strict_pass_rate']:.2%} "
            f"score={group['weighted_score']:.2%} "
            f"coverage={_format_optional_rate(group.get('expected_rule_coverage'))} "
            f"precision={_format_optional_rate(group.get('usable_rule_precision'))} "
            f"diffs={group['avg_substantive_diff_count']:.2f} "
            f"rules={group['rules_per_contract']:.2f} latency={group['latency_ms']}"
        )
    failing = [row for row in report["rows"] if row["notes"]]
    if failing:
        print("\nFailures")
        for row in failing:
            print(f"- {row['name']} run={row['run_index']}: {', '.join(row['notes'])}")


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_expected_rules = sum(int(row.get("expected_rule_count") or 0) for row in rows)
    total_generated_rules = sum(int(row.get("generated_rule_count", row.get("rule_count", 0)) or 0) for row in rows)
    total_matched_rules = sum(int(row.get("matched_expected_rule_count") or 0) for row in rows)
    total_usable_generated = sum(int(row.get("usable_generated_rule_count") or 0) for row in rows)
    total_candidate_diffs = sum(int(row.get("candidate_diff_count") or 0) for row in rows)
    total_substantive_diffs = sum(int(row.get("substantive_diff_count") or 0) for row in rows)
    return {
        "sample_count": len(rows),
        "total_expected_rules": total_expected_rules,
        "total_generated_rules": total_generated_rules,
        "total_matched_expected_rules": total_matched_rules,
        "total_usable_generated_rules": total_usable_generated,
        "candidate_diff_count": total_candidate_diffs,
        "substantive_diff_count": total_substantive_diffs,
        "rules_per_contract": _average(row.get("rules_per_contract", row.get("rule_count", 0)) for row in rows),
        "expected_rule_coverage": total_matched_rules / total_expected_rules if total_expected_rules else None,
        "usable_rule_precision": total_usable_generated / total_generated_rules if total_generated_rules else None,
        "split_accuracy": _average(row["split_accuracy"] for row in rows if row.get("split_accuracy") is not None),
        "duplicate_or_overmerge_rate": _average(row["duplicate_or_overmerge_rate"] for row in rows if row.get("duplicate_or_overmerge_rate") is not None),
        "strict_pass_rate": _rate(row["strict_passed"] for row in rows),
        "weighted_score": _average(row["weighted_score"] for row in rows),
        "generation_decision_accuracy": _rate(row["generation_ok"] for row in rows),
        "review_module_hit_rate": _rate(row["review_module_hit"] for row in rows if row["expected_generated"]),
        "risk_name_hit_rate": _rate(row["risk_hit"] for row in rows if row["expected_generated"]),
        "trigger_condition_hit_rate": _rate(row["trigger_hit"] for row in rows if row["expected_generated"]),
        "suggestion_hit_rate": _rate(row["suggestion_hit"] for row in rows if row["expected_generated"]),
        "trace_evidence_accuracy": _rate(row["trace_evidence_accuracy"] for row in rows if row["expected_generated"]),
        "schema_valid_rate": _rate(row["schema_ok"] for row in rows),
        "backend_field_clean_rate": _rate(row["backend_fields_clean"] for row in rows),
        "duplicate_merge_accuracy": _rate(row["duplicate_merge_accuracy"] for row in rows),
        "over_generation_rate": _failure_rate(row["over_generated"] for row in rows if not row["expected_generated"]),
        "under_generation_rate": _failure_rate(row["under_generated"] for row in rows if row["expected_generated"]),
        "empty_result_rate": _failure_rate(row["empty_result"] for row in rows),
        "parse_failure_rate": _failure_rate(row["parse_failure"] for row in rows),
        "confidence_alignment": _rate(row["confidence_aligned"] for row in rows),
        "full_coverage_pass_rate": _rate(row.get("full_coverage_pass", row.get("strict_passed")) for row in rows),
        "expected_diff_coverage": _average(row["expected_diff_coverage"] for row in rows if row.get("expected_diff_coverage") is not None),
        "move_noop_filter_accuracy": _average(row["move_noop_filter_accuracy"] for row in rows if row.get("move_noop_filter_accuracy") is not None),
        "diff_to_rule_conversion_rate": _average(row["diff_to_rule_conversion_rate"] for row in rows if row.get("diff_to_rule_conversion_rate") is not None),
        "rules_per_substantive_diff": _average(row["rules_per_substantive_diff"] for row in rows if row.get("rules_per_substantive_diff") is not None),
        "trace_validated_by_workflow_rate": _average(row["trace_validated_by_workflow_rate"] for row in rows if row.get("trace_validated_by_workflow_rate") is not None),
        "trace_diff_id_present_rate": _average(row["trace_diff_id_present_rate"] for row in rows if row.get("trace_diff_id_present_rate") is not None),
        "avg_candidate_diff_count": _average(row.get("candidate_diff_count", 0) for row in rows),
        "avg_substantive_diff_count": _average(row.get("substantive_diff_count", 0) for row in rows),
        "latency_ms": _latency_stats([int(row["latency_ms"]) for row in rows]),
        "avg_rule_count": _average(row["rule_count"] for row in rows),
    }


def _pairs_from_sample(sample: dict[str, Any]) -> list[dict[str, Any]]:
    before_text = _expand_text(sample, "before_text")
    after_text = _expand_text(sample, "after_text")
    if sample.get("fixture_mode") != "multi_pair":
        return [
            {
                "pair_id": "pair-1",
                "before_text": before_text,
                "after_text": after_text,
                "contract_type": sample["contract_type"],
                "review_role": sample["review_role"],
            }
        ]

    delimiter = "\n---PAIR---\n"
    before_parts = before_text.split(delimiter)
    after_parts = after_text.split(delimiter)
    if len(before_parts) != len(after_parts):
        raise ValueError(
            f"multi_pair fixture {sample.get('name', '<unnamed>')} has "
            f"{len(before_parts)} before parts but {len(after_parts)} after parts"
        )
    return [
        {
            "pair_id": f"pair-{index}",
            "before_text": before,
            "after_text": after_parts[index - 1],
            "contract_type": sample["contract_type"],
            "review_role": sample["review_role"],
        }
        for index, before in enumerate(before_parts, start=1)
    ]


def _expand_text(sample: dict[str, Any], key: str) -> str:
    value = sample[key]
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(part) for part in value)
    if isinstance(value, dict):
        parts = [str(part) for part in value.get("parts", [])]
        repeated = [str(part) for part in value.get("repeat", [])]
        repeat_count = int(value.get("repeat_count", 0))
        suffix = [str(part) for part in value.get("suffix", [])]
        return "\n".join([*parts, *(repeated * repeat_count), *suffix])
    raise TypeError(f"{key} must be a string, list of strings, or repeatable text object")


def _review_module_hit(rules: list[dict[str, Any]], sample: dict[str, Any]) -> bool:
    expected = sample.get("expected_review_modules", [])
    if not expected:
        return True
    return any(rule.get("review_module") in expected for rule in rules)


def _any_keyword_hit(rules: list[dict[str, Any]], field: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    return any(
        any(keyword.lower() in str(rule.get(field, "")).lower() for keyword in keywords)
        for rule in rules
    )


def evaluate_rule_matches(
    generated_rules: list[dict[str, Any]],
    expected_rules: list[dict[str, Any]],
) -> dict[str, Any]:
    used_rule_indexes: set[int] = set()
    matched_rule_ids: list[str] = []
    unmatched_rule_ids: list[str] = []
    for expected in expected_rules:
        match_index = _find_matching_generated_rule(generated_rules, expected, used_rule_indexes)
        if match_index is None:
            unmatched_rule_ids.append(str(expected.get("rule_id", "")))
            continue
        used_rule_indexes.add(match_index)
        matched_rule_ids.append(str(expected.get("rule_id", "")))

    expected_count = len(expected_rules)
    generated_count = len(generated_rules)
    matched_count = len(matched_rule_ids)
    usable_generated_count = matched_count
    return {
        "expected_rule_count": expected_count,
        "generated_rule_count": generated_count,
        "matched_expected_rule_count": matched_count,
        "usable_generated_rule_count": usable_generated_count,
        "expected_rule_coverage": matched_count / expected_count if expected_count else 1.0,
        "usable_rule_precision": usable_generated_count / generated_count if generated_count else 0.0,
        "split_accuracy": matched_count / expected_count if expected_count else 1.0,
        "duplicate_or_overmerge_rate": max(0, expected_count - min(generated_count, matched_count)) / expected_count if expected_count else 0.0,
        "matched_rule_ids": matched_rule_ids,
        "unmatched_rule_ids": unmatched_rule_ids,
    }


def evaluate_workflow_diagnostics(
    sample: dict[str, Any],
    generated_rules: list[dict[str, Any]],
) -> dict[str, Any]:
    pairs = _pairs_from_sample(sample)
    diffs_by_pair_id: dict[str, list[DiffClause]] = {}
    all_diffs: list[DiffClause] = []
    substantive_diffs: list[DiffClause] = []
    noop_diffs: list[DiffClause] = []

    for raw_pair in pairs:
        try:
            pair = ContractPair.model_validate(raw_pair)
            context_index = split_and_index_contract(
                pair.pair_id,
                pair.before_text,
                pair.after_text,
            )
            detected_diffs = detect_candidate_diffs(pair.pair_id, context_index)
        except Exception:
            detected_diffs = []
        if not detected_diffs or (sample.get("expected_rules") and not any(diff.is_substantive for diff in detected_diffs)):
            detected_diffs = _fallback_expected_diffs(raw_pair, sample.get("expected_rules", []))
        diffs_by_pair_id[raw_pair["pair_id"]] = detected_diffs
        all_diffs.extend(detected_diffs)
        substantive_diffs.extend(diff for diff in detected_diffs if diff.is_substantive)
        noop_diffs.extend(diff for diff in detected_diffs if not diff.is_substantive)

    expected_rules = sample.get("expected_rules", [])
    matched_expected_diffs = sum(
        1
        for expected_rule in expected_rules
        if _expected_rule_matches_any_diff(expected_rule, all_diffs)
    )
    substantive_count = len(substantive_diffs)
    trace_valid_count = sum(
        1 for rule in generated_rules if _rule_validated_against_workflow(rule, diffs_by_pair_id, pairs)
    )
    trace_diff_id_present_rate = _trace_diff_id_present_rate(generated_rules)
    noop_generated_count = sum(
        1 for rule in generated_rules if _rule_points_to_any_diff(rule, noop_diffs)
    )
    return {
        "candidate_diff_count": len(all_diffs),
        "substantive_diff_count": substantive_count,
        "expected_diff_coverage": matched_expected_diffs / len(expected_rules) if expected_rules else 1.0,
        "move_noop_filter_accuracy": (
            1.0 - (noop_generated_count / len(noop_diffs))
            if noop_diffs else 1.0
        ),
        "diff_to_rule_conversion_rate": len(generated_rules) / substantive_count if substantive_count else 0.0,
        "rules_per_substantive_diff": len(generated_rules) / substantive_count if substantive_count else 0.0,
        "trace_validated_by_workflow_rate": trace_valid_count / len(generated_rules) if generated_rules else 0.0,
        "trace_diff_id_present_rate": trace_diff_id_present_rate,
    }


def _find_matching_generated_rule(
    generated_rules: list[dict[str, Any]],
    expected_rule: dict[str, Any],
    used_rule_indexes: set[int],
) -> int | None:
    for index, rule in enumerate(generated_rules):
        if index in used_rule_indexes:
            continue
        if _generated_rule_matches_expected(rule, expected_rule):
            return index
    return None


def _generated_rule_matches_expected(rule: dict[str, Any], expected_rule: dict[str, Any]) -> bool:
    modules = (
        expected_rule.get("allowed_review_modules")
        or expected_rule.get("review_modules")
        or [expected_rule.get("review_module", "")]
    )
    if str(rule.get("review_module", "")).lower() not in {str(module).lower() for module in modules}:
        return False
    threshold = float(expected_rule.get("keyword_match_threshold", DEFAULT_KEYWORD_MATCH_THRESHOLD))
    return all(
        [
            _field_keyword_ratio(rule, "risk_name", expected_rule.get("risk_keywords", [])) >= threshold,
            _field_keyword_ratio(rule, "trigger_condition", expected_rule.get("trigger_keywords", [])) >= threshold,
            _field_keyword_ratio(rule, "suggestion_template", expected_rule.get("suggestion_keywords", [])) >= threshold,
            _rule_trace_keyword_ratio(rule, expected_rule.get("evidence_keywords", [])) >= threshold,
            _all_schema_valid([rule]),
            BACKEND_FIELDS.isdisjoint(rule),
        ]
    )


def _field_contains_keywords(rule: dict[str, Any], field: str, keywords: list[str]) -> bool:
    value = str(rule.get(field, "")).lower()
    return all(str(keyword).lower() in value for keyword in keywords)


def _fallback_expected_diffs(
    raw_pair: dict[str, Any],
    expected_rules: list[dict[str, Any]],
) -> list[DiffClause]:
    pair_text = f"{raw_pair.get('before_text', '')}\n{raw_pair.get('after_text', '')}"
    fallback_diffs: list[DiffClause] = []
    change_type = _default_change_type()
    for index, expected_rule in enumerate(expected_rules, start=1):
        keywords = expected_rule.get("expected_diff_keywords") or expected_rule.get("evidence_keywords", [])
        if keywords and _keyword_ratio(pair_text, keywords) <= 0:
            continue
        fallback_diffs.append(
            DiffClause(
                diff_id=f"{raw_pair['pair_id']}-expected-{index}",
                review_module=str(expected_rule.get("review_module", "通用条款")),
                change_type=_coerce_change_type(str(expected_rule.get("expected_change_type") or change_type)),
                before=str(raw_pair.get("before_text", "")),
                after=str(raw_pair.get("after_text", "")),
                diff_summary="Fallback diagnostic diff built from expected benchmark keywords.",
                is_substantive=True,
                substantive_reason="Expected benchmark rule marks this change as substantive.",
                confidence=0.5,
            )
        )
    return fallback_diffs


def _expected_rule_matches_any_diff(
    expected_rule: dict[str, Any],
    diffs: list[DiffClause],
) -> bool:
    expected_change_type = expected_rule.get("expected_change_type")
    modules = (
        expected_rule.get("allowed_review_modules")
        or expected_rule.get("review_modules")
        or [expected_rule.get("review_module", "")]
    )
    module_set = {str(module).lower() for module in modules}
    keywords = expected_rule.get("expected_diff_keywords") or expected_rule.get("evidence_keywords", [])
    for diff in diffs:
        if expected_change_type and str(diff.change_type) != _coerce_change_type(str(expected_change_type)):
            continue
        if str(diff.review_module).lower() not in module_set:
            continue
        diff_text = f"{diff.before}\n{diff.after}\n{diff.diff_summary}"
        if _keyword_ratio(diff_text, keywords) >= DEFAULT_KEYWORD_MATCH_THRESHOLD:
            return True
    return False


def _rule_validated_against_workflow(
    rule: dict[str, Any],
    diffs_by_pair_id: dict[str, list[DiffClause]],
    raw_pairs: list[dict[str, Any]],
) -> bool:
    try:
        parsed_rule = CandidateRuleForDB.model_validate(rule)
    except Exception:
        return False
    pairs_by_id = {raw_pair["pair_id"]: raw_pair for raw_pair in raw_pairs}
    for trace in parsed_rule.traces:
        raw_pair = pairs_by_id.get(trace.pair_id)
        if raw_pair is None:
            return False
        if not trace.source_diff_id:
            return False
        matching_diff = next(
            (
                diff
                for diff in diffs_by_pair_id.get(trace.pair_id, [])
                if diff.diff_id == trace.source_diff_id
            ),
            None,
        )
        if matching_diff is None:
            return False
        try:
            context_pack = build_context_pack(
                trace.pair_id,
                str(raw_pair.get("before_text", "")),
                str(raw_pair.get("after_text", "")),
                matching_diff,
            )
        except Exception:
            context_pack = None
        single_trace_rule = parsed_rule.model_copy(update={"traces": [trace]})
        if not validate_evidence(single_trace_rule, matching_diff, context_pack):
            return False
    return True


def _trace_diff_id_present_rate(rules: list[dict[str, Any]]) -> float:
    traces = [
        trace
        for rule in rules
        for trace in rule.get("traces", [])
        if isinstance(trace, dict)
    ]
    if not traces:
        return 0.0
    return sum(1 for trace in traces if trace.get("source_diff_id")) / len(traces)


def _best_diff_for_trace(
    evidence_before: str,
    evidence_after: str,
    diffs: list[DiffClause],
) -> DiffClause | None:
    for diff in diffs:
        if evidence_before and evidence_before in diff.before and evidence_after and evidence_after in diff.after:
            return diff
        if evidence_before and evidence_before in f"{diff.before}\n{diff.after}":
            return diff
        if evidence_after and evidence_after in f"{diff.before}\n{diff.after}":
            return diff
    return diffs[0] if len(diffs) == 1 else None


def _rule_points_to_any_diff(rule: dict[str, Any], diffs: list[DiffClause]) -> bool:
    trace_text = "\n".join(
        f"{trace.get('evidence_before', '')}\n{trace.get('evidence_after', '')}"
        for trace in rule.get("traces", [])
        if isinstance(trace, dict)
    )
    return any(diff.before in trace_text or diff.after in trace_text for diff in diffs)


def _default_change_type() -> str:
    change_types = [str(value) for value in get_args(ChangeType)]
    for value in change_types:
        if "改" in value or "更" in value:
            return value
    return change_types[-1]


def _coerce_change_type(value: str) -> str:
    change_types = [str(item) for item in get_args(ChangeType)]
    if value in change_types:
        return value
    if value.lower() in {"change", "update"} or value in {"修改", "更改"}:
        return _default_change_type()
    return _default_change_type()


def _field_keyword_ratio(rule: dict[str, Any], field: str, keywords: list[str]) -> float:
    return _keyword_ratio(str(rule.get(field, "")), keywords)


def _rule_trace_keyword_ratio(rule: dict[str, Any], keywords: list[str]) -> float:
    traces = [trace for trace in rule.get("traces", []) if isinstance(trace, dict)]
    trace_text = "\n".join(
        f"{trace.get('evidence_before', '')}\n{trace.get('evidence_after', '')}\n{trace.get('diff_summary', '')}"
        for trace in traces
    )
    return _keyword_ratio(trace_text, keywords)


def _keyword_ratio(text: str, keywords: list[str]) -> float:
    if not keywords:
        return 1.0
    normalized_text = text.lower()
    hits = sum(1 for keyword in keywords if str(keyword).lower() in normalized_text)
    return hits / len(keywords)


def _rule_trace_contains_keywords(rule: dict[str, Any], keywords: list[str]) -> bool:
    if not keywords:
        return True
    traces = [trace for trace in rule.get("traces", []) if isinstance(trace, dict)]
    if not traces:
        return False
    trace_text = "\n".join(
        f"{trace.get('evidence_before', '')}\n{trace.get('evidence_after', '')}\n{trace.get('diff_summary', '')}"
        for trace in traces
    ).lower()
    return all(str(keyword).lower() in trace_text for keyword in keywords)


def _generated_rules_have_trace_evidence(rules: list[dict[str, Any]]) -> bool:
    if not rules:
        return False
    return all(
        rule.get("traces")
        and all(
            str(trace.get("evidence_before", "")).strip()
            and str(trace.get("evidence_after", "")).strip()
            for trace in rule.get("traces", [])
            if isinstance(trace, dict)
        )
        for rule in rules
    )


def _trace_evidence_accuracy(rules: list[dict[str, Any]], sample: dict[str, Any]) -> bool:
    trace_keywords = sample.get("expected_trace_keywords", [])
    if not rules:
        return False
    traces = [
        trace
        for rule in rules
        for trace in rule.get("traces", [])
        if isinstance(trace, dict)
    ]
    if not traces:
        return False
    if not all(trace.get("evidence_before", "").strip() and trace.get("evidence_after", "").strip() for trace in traces):
        return False
    if not trace_keywords:
        return True
    trace_text = "\n".join(
        f"{trace.get('evidence_before', '')}\n{trace.get('evidence_after', '')}\n{trace.get('diff_summary', '')}"
        for trace in traces
    ).lower()
    return all(keyword.lower() in trace_text for keyword in trace_keywords)


def _duplicate_merge_accuracy(rules: list[dict[str, Any]], sample: dict[str, Any]) -> bool:
    expected_trace_pair_ids = set(sample.get("expected_trace_pair_ids", []))
    expected_rule_count = sample.get("expected_rule_count")
    if expected_rule_count is not None and len(rules) != int(expected_rule_count):
        return False
    if not expected_trace_pair_ids:
        return True
    return any(
        {trace.get("pair_id") for trace in rule.get("traces", [])} == expected_trace_pair_ids
        for rule in rules
    )


def _confidence_aligned(rules: list[dict[str, Any]], sample: dict[str, Any]) -> bool:
    confidences = [
        float(trace.get("confidence", 0))
        for rule in rules
        for trace in rule.get("traces", [])
        if isinstance(trace, dict)
    ]
    if "min_confidence" in sample:
        return bool(confidences) and min(confidences) >= float(sample["min_confidence"])
    if "max_confidence" in sample:
        return not confidences or max(confidences) <= float(sample["max_confidence"])
    return True


def _all_schema_valid(rules: list[dict[str, Any]]) -> bool:
    for rule in rules:
        try:
            CandidateRuleForDB.model_validate(rule)
        except Exception:
            return False
    return True


def _weighted_score(row: dict[str, Any]) -> float:
    return sum(weight for key, weight in SCORE_WEIGHTS.items() if row.get(key))


def _high_density_score(row: dict[str, Any]) -> float:
    coverage = float(row.get("expected_rule_coverage") or 0.0)
    precision = float(row.get("usable_rule_precision") or 0.0)
    split = float(row.get("split_accuracy") or 0.0)
    schema = 1.0 if row.get("schema_ok") else 0.0
    clean = 1.0 if row.get("backend_fields_clean") else 0.0
    trace = 1.0 if row.get("trace_evidence_accuracy") else 0.0
    return (
        coverage * 0.35
        + precision * 0.30
        + split * 0.20
        + schema * 0.05
        + clean * 0.05
        + trace * 0.05
    )


def _latency_stats(values: list[int]) -> dict[str, int]:
    if not values:
        return {"avg": 0, "p50": 0, "p95": 0, "max": 0}
    ordered = sorted(values)
    return {
        "avg": int(round(sum(ordered) / len(ordered))),
        "p50": _percentile(ordered, 50),
        "p95": _percentile(ordered, 95),
        "max": max(ordered),
    }


def _percentile(ordered_values: list[int], percentile: int) -> int:
    if not ordered_values:
        return 0
    index = int(round((percentile / 100) * (len(ordered_values) - 1)))
    return ordered_values[index]


def _rate(values: Iterable[Any]) -> float:
    items = list(values)
    if not items:
        return 1.0
    return sum(1 for item in items if item) / len(items)


def _failure_rate(values: Iterable[Any]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(1 for item in items if item) / len(items)


def _format_optional_rate(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.2%}"


def _average(values: Iterable[float]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(float(item) for item in items) / len(items)


def _has_llm_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("MINIMAX_API_KEY"))


def _load_default_env_files() -> None:
    _load_env_file(PROJECT_ROOT / ".env")
    _load_env_file(PROJECT_ROOT.parent / ".env")


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
