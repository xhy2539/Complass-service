import json
import re
import tempfile
from pathlib import Path
from typing import get_args

import pytest

from app.chains.reverse_rule_graph import _parse_rule_batch_from_text
from app.chains.reverse_rule_graph import run_reverse_rule_extraction
from app.models.reverse_rule import CandidateRuleForDB
from app.models.reverse_rule import ChangeType
from app.models.reverse_rule import ContractPair
from app.models.reverse_rule import DiffClause
from app.models.reverse_rule import DiffResult
from app.models.reverse_rule import RiskLevel
from app.services.reverse_rule_tools import validate_evidence


DEFAULT_RISK_LEVEL = get_args(RiskLevel)[1]
DEFAULT_CHANGE_TYPE = get_args(ChangeType)[3]


@pytest.fixture(autouse=True)
def isolate_llm_environment(monkeypatch, request):
    for key in (
        "DISABLE_REAL_LLM",
        "LLM_PROVIDER",
        "MINIMAX_API_KEY",
        "MINIMAX_MODEL_NAME",
        "MINIMAX_BASE_URL",
        "LLM_MODEL_NAME",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    safe_name = re.sub(r"[^a-zA-Z0-9_]+", "_", request.node.name)
    workdir = Path(tempfile.gettempdir()) / "reverse_rule_workflow_tests" / "trace_binding" / safe_name
    workdir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(workdir)


def _rule_payload(trace: dict) -> dict:
    return {
        "contract_type": "service",
        "review_perspective": "通用",
        "review_module": "Payment",
        "risk_name": "payment period",
        "check_point": "Check payment period.",
        "trigger_condition": "Trigger on payment period changes.",
        "default_risk_level": DEFAULT_RISK_LEVEL,
        "suggestion_template": "Use 30 days.",
        "example_clause": "Pay within 90 days.",
        "traces": [trace],
    }


def _diff(diff_id: str = "pair-1-diff-1") -> DiffClause:
    return DiffClause(
        diff_id=diff_id,
        review_module="Payment",
        change_type=DEFAULT_CHANGE_TYPE,
        before="Pay within 90 days.",
        after="Pay within 30 days.",
        diff_summary="Payment period changed.",
        is_substantive=True,
    )


def test_candidate_rule_trace_preserves_source_diff_id():
    rule = CandidateRuleForDB.model_validate(
        _rule_payload(
            {
                "pair_id": "pair-1",
                "source_diff_id": "pair-1-diff-1",
                "evidence_before": "Pay within 90 days.",
                "evidence_after": "Pay within 30 days.",
                "diff_summary": "Payment period changed.",
                "user_intent": "Shorten payment period.",
                "confidence": 0.8,
            }
        )
    )

    assert rule.traces[0].source_diff_id == "pair-1-diff-1"


def test_validate_evidence_rejects_wrong_source_diff_id():
    rule = CandidateRuleForDB.model_validate(
        _rule_payload(
            {
                "pair_id": "pair-1",
                "source_diff_id": "pair-1-diff-2",
                "evidence_before": "Pay within 90 days.",
                "evidence_after": "Pay within 30 days.",
                "diff_summary": "Payment period changed.",
                "user_intent": "Shorten payment period.",
                "confidence": 0.8,
            }
        )
    )

    assert validate_evidence(rule, _diff()) is False


def test_rule_with_unknown_source_diff_id_is_filtered():
    def bad_rule_generator(pair, diff_result, retrieved_cases, base_info=None):
        return [
            _rule_payload(
                {
                    "pair_id": pair.pair_id,
                    "source_diff_id": "missing-diff",
                    "evidence_before": diff_result.changed_clauses[0].before,
                    "evidence_after": diff_result.changed_clauses[0].after,
                    "diff_summary": diff_result.changed_clauses[0].diff_summary,
                    "user_intent": "Shorten payment period.",
                    "confidence": 0.8,
                }
            )
        ]

    result = run_reverse_rule_extraction(
        [
            {
                "pair_id": "pair-1",
                "before_text": "Pay within 90 days.",
                "after_text": "Pay within 30 days.",
                "contract_type": "service",
                "review_role": "通用",
            }
        ],
        rule_generator=bad_rule_generator,
    )

    assert result["rules"] == []


def test_missing_source_diff_id_is_not_guessed_when_multiple_diffs_match():
    text = json.dumps(
        {
            "rules": [
                _rule_payload(
                    {
                        "pair_id": "pair-1",
                        "evidence_before": "Pay within 90 days.",
                        "evidence_after": "Pay within 30 days.",
                        "diff_summary": "Payment period changed.",
                        "user_intent": "Shorten payment period.",
                        "confidence": 0.8,
                    }
                )
            ]
        },
        ensure_ascii=False,
    )
    pair = ContractPair(
        pair_id="pair-1",
        before_text="Pay within 90 days. Pay within 90 days.",
        after_text="Pay within 30 days. Pay within 30 days.",
        contract_type="service",
    )
    diff_result = DiffResult(
        pair_id="pair-1",
        changed_clauses=[_diff("pair-1-diff-1"), _diff("pair-1-diff-2")],
    )

    parsed = _parse_rule_batch_from_text(text, pair=pair, diff_result=diff_result)

    assert len(parsed.rules) == 1
    assert parsed.rules[0].traces[0].source_diff_id is None


def test_missing_source_diff_id_is_filled_for_unique_matching_diff():
    text = json.dumps(
        {
            "rules": [
                _rule_payload(
                    {
                        "pair_id": "pair-1",
                        "evidence_before": "Pay within 90 days.",
                        "evidence_after": "Pay within 30 days.",
                        "diff_summary": "Payment period changed.",
                        "user_intent": "Shorten payment period.",
                        "confidence": 0.8,
                    }
                )
            ]
        },
        ensure_ascii=False,
    )
    pair = ContractPair(
        pair_id="pair-1",
        before_text="Pay within 90 days.",
        after_text="Pay within 30 days.",
        contract_type="service",
    )
    diff_result = DiffResult(pair_id="pair-1", changed_clauses=[_diff("pair-1-diff-1")])

    parsed = _parse_rule_batch_from_text(text, pair=pair, diff_result=diff_result)

    assert parsed.rules[0].traces[0].source_diff_id == "pair-1-diff-1"
