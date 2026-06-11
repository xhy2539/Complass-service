"""Run evaluation suites for the contract comparison workflow."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from contract_compare_workflow import workflow
from contract_compare_workflow.evaluation.instrumentation import run_compare_with_trace
from contract_compare_workflow.evaluation.scoring import aggregate_results
from contract_compare_workflow.evaluation.scoring import build_stub_enhanced
from contract_compare_workflow.evaluation.scoring import evaluate_case
from contract_compare_workflow.evaluation.scoring import load_gold_cases
from contract_compare_workflow.evaluation.scoring import print_console_summary

RESULTS_DIR = Path(__file__).resolve().parent / "results"
GOLD_CASES_PATH = Path(__file__).resolve().parent / "gold_cases.json"

EMPTY_RULES_BODY = {
    "data": {
        "finance_rules": [],
        "legal_rules": [],
        "performance_rules": [],
        "other_rules": [],
    }
}


class StubbedCompareCase(AbstractContextManager["StubbedCompareCase"]):
    """Monkeypatch compare workflow internals for deterministic evaluation."""

    def __init__(self, case: dict[str, Any]) -> None:
        self.case = case
        self.originals: dict[str, Any] = {}

    def __enter__(self) -> "StubbedCompareCase":
        self.originals = {
            "classify_compare_contract_type": workflow.classify_compare_contract_type,
            "identify_differences": workflow.identify_differences,
            "fetch_audit_rules": workflow.fetch_audit_rules,
            "analyze_diff_risks_with_llm": workflow.analyze_diff_risks_with_llm,
        }

        async def classify_compare_contract_type(old_text: str, new_text: str) -> str:
            _ = old_text, new_text
            return self.case["contract_type"]

        async def identify_differences(old_text: str, new_text: str) -> list[dict[str, Any]]:
            _ = old_text, new_text
            return [
                {
                    "change_type": diff["change_type"],
                    "old_quote": diff["old_quote"],
                    "new_quote": diff["new_quote"],
                    "original": _stub_original(diff),
                }
                for diff in self.case.get("diff_items", [])
            ]

        async def fetch_audit_rules(contract_type: str) -> dict[str, Any]:
            _ = contract_type
            return {
                "status_code": 200,
                "body": json.dumps(EMPTY_RULES_BODY, ensure_ascii=False),
            }

        async def analyze_diff_risks_with_llm(
            old_text: str,
            new_text: str,
            diff_texts: list[dict[str, Any]],
            common_rules: list[dict[str, Any]],
            specific_rules: list[dict[str, Any]],
        ) -> dict[str, Any]:
            _ = old_text, new_text, diff_texts, common_rules, specific_rules
            return {
                "success": True,
                "enhanced": build_stub_enhanced(self.case),
                "total_risks": self.case.get("expected_total_risks", 0),
                "message": "",
            }

        workflow.classify_compare_contract_type = classify_compare_contract_type
        workflow.identify_differences = identify_differences
        workflow.fetch_audit_rules = fetch_audit_rules
        workflow.analyze_diff_risks_with_llm = analyze_diff_risks_with_llm
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        for name, value in self.originals.items():
            setattr(workflow, name, value)
        return None


async def _run_case(case: dict[str, Any], mode: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if mode == "stub":
        with StubbedCompareCase(case):
            response, trace = await run_compare_with_trace(
                old_text=case["old_text"],
                new_text=case["new_text"],
                task_type=case.get("task_type", "compare"),
            )
        return response, trace.to_dict()

    response, trace = await run_compare_with_trace(
        old_text=case["old_text"],
        new_text=case["new_text"],
        task_type=case.get("task_type", "compare"),
    )
    return response, trace.to_dict()


def _filter_cases(cases: list[dict[str, Any]], case_filter: str | None) -> list[dict[str, Any]]:
    if not case_filter:
        return cases
    wanted = {item.strip() for item in case_filter.split(",") if item.strip()}
    filtered = [case for case in cases if case.get("case_id") in wanted]
    missing = wanted - {case.get("case_id") for case in filtered}
    if missing:
        raise SystemExit(f"未找到 case_id: {', '.join(sorted(missing))}")
    return filtered


def _build_output_path(mode: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return RESULTS_DIR / f"compare_evaluation_{mode}_{timestamp}.json"


def _stub_original(diff: dict[str, Any]) -> str:
    stub_output = diff.get("stub_output", {})
    original = stub_output.get("original")
    if isinstance(original, str) and original:
        return original
    required_facts = diff.get("original_required_facts", [])
    flattened: list[str] = []
    for item in required_facts:
        if isinstance(item, str) and item:
            flattened.append(item)
        elif isinstance(item, list):
            options = [option for option in item if isinstance(option, str) and option]
            if options:
                flattened.append(options[0])
    return "；".join(flattened)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate contract_compare_workflow")
    parser.add_argument("--mode", choices=("stub", "live"), default="stub")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--case-id", dest="case_id", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    if args.repeat <= 0:
        raise SystemExit("--repeat 必须大于 0")

    cases = load_gold_cases(str(GOLD_CASES_PATH))
    selected_cases = _filter_cases(cases, args.case_id)

    run_entries: list[dict[str, Any]] = []
    for case in selected_cases:
        for run_index in range(args.repeat):
            response, trace = await _run_case(case, args.mode)
            evaluation = evaluate_case(case=case, response=response, trace=trace)
            run_entries.append(
                {
                    "case": {
                        "case_id": case["case_id"],
                        "suite": case["suite"],
                        "contract_type": case["contract_type"],
                        "length_bucket": case["length_bucket"],
                        "scenario_tags": case.get("scenario_tags", []),
                        "expected_success": case["expected_success"],
                        "expected_total_risks": case["expected_total_risks"],
                    },
                    "run_index": run_index + 1,
                    "response": response,
                    "trace": trace,
                    "evaluation": evaluation,
                }
            )

    summary = aggregate_results(run_entries, args.repeat)
    payload = {
        "mode": args.mode,
        "repeat": args.repeat,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "gold_cases_path": str(GOLD_CASES_PATH),
        "summary": summary,
        "runs": run_entries,
    }

    output_path = Path(args.output) if args.output else _build_output_path(args.mode)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print_console_summary(summary, str(output_path))


if __name__ == "__main__":
    asyncio.run(main())
