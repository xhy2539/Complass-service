import json
from collections import Counter
from pathlib import Path

import pytest

from scripts import evaluate_reverse_rule_extraction as evaluator


def matching_sample() -> dict:
    return {
        "name": "short payment benchmark",
        "length_category": "short",
        "contract_type": "service",
        "review_role": "vendor",
        "before_text": "Party A shall pay service fees within 90 days after acceptance.",
        "after_text": "Party A shall pay service fees within 30 days after acceptance and valid invoice receipt.",
        "expected_review_modules": ["Payment"],
        "expected_risk_keywords": ["payment"],
        "expected_trigger_keywords": ["30 days", "invoice"],
        "expected_suggestion_keywords": ["30 days", "invoice"],
        "expected_trace_keywords": ["90 days", "30 days"],
        "should_generate_rule": True,
        "min_confidence": 0.7,
    }


def generated_rule() -> dict:
    return {
        "contract_type": "service",
        "review_perspective": "通用",
        "review_module": "Payment",
        "risk_name": "payment period too long",
        "check_point": "Check whether payment period and invoice condition are clear.",
        "trigger_condition": "Trigger when payment exceeds 30 days or lacks valid invoice condition.",
        "default_risk_level": "中",
        "suggestion_template": "Agree payment within 30 days after valid invoice receipt.",
        "example_clause": "Party A shall pay service fees within 90 days after acceptance.",
        "traces": [
            {
                "pair_id": "pair-1",
                "source_diff_id": "pair-1-diff-1",
                "evidence_before": "Party A shall pay service fees within 90 days after acceptance.",
                "evidence_after": "Party A shall pay service fees within 30 days after acceptance and valid invoice receipt.",
                "diff_summary": "Payment period changed from 90 days to 30 days with invoice condition.",
                "user_intent": "Improve collection certainty.",
                "confidence": 0.82,
            }
        ],
    }


def expected_rule(
    rule_id: str,
    module: str,
    risk: str,
    trigger: str,
    suggestion: str,
    evidence: str,
) -> dict:
    return {
        "rule_id": rule_id,
        "review_module": module,
        "risk_keywords": [risk],
        "trigger_keywords": [trigger],
        "suggestion_keywords": [suggestion],
        "evidence_keywords": [evidence],
    }


def payment_rule() -> dict:
    rule = generated_rule()
    rule["review_module"] = "Payment"
    rule["risk_name"] = "payment period too long"
    rule["trigger_condition"] = "Trigger when payment exceeds 30 days."
    rule["suggestion_template"] = "Agree payment within 30 days."
    return rule


def liability_rule() -> dict:
    rule = generated_rule()
    rule["review_module"] = "Liability"
    rule["risk_name"] = "liability cap missing"
    rule["trigger_condition"] = "Trigger when liability has no cap."
    rule["suggestion_template"] = "Agree a liability cap."
    rule["traces"][0]["evidence_before"] = "Supplier bears all liability."
    rule["traces"][0]["evidence_after"] = "Liability is capped at paid fees."
    return rule


def unrelated_rule() -> dict:
    rule = generated_rule()
    rule["review_module"] = "Confidentiality"
    rule["risk_name"] = "confidentiality term"
    rule["trigger_condition"] = "Trigger when confidentiality term is missing."
    rule["suggestion_template"] = "Add confidentiality term."
    return rule


def test_expected_rules_are_matched_one_to_one_for_precision_and_coverage():
    expected_rules = [
        expected_rule("payment", "Payment", "payment", "30 days", "30 days", "90 days"),
        expected_rule("liability", "Liability", "liability", "cap", "cap", "paid fees"),
    ]

    result = evaluator.evaluate_rule_matches(
        [payment_rule(), liability_rule(), unrelated_rule()],
        expected_rules,
    )

    assert result["expected_rule_count"] == 2
    assert result["generated_rule_count"] == 3
    assert result["matched_expected_rule_count"] == 2
    assert result["usable_generated_rule_count"] == 2
    assert result["expected_rule_coverage"] == pytest.approx(1.0)
    assert result["usable_rule_precision"] == pytest.approx(2 / 3)
    assert result["split_accuracy"] == pytest.approx(1.0)
    assert result["duplicate_or_overmerge_rate"] == pytest.approx(0.0)


def test_expected_rules_penalize_overmerged_outputs():
    expected_rules = [
        expected_rule("payment", "Payment", "payment", "30 days", "30 days", "90 days"),
        expected_rule("liability", "Liability", "liability", "cap", "cap", "paid fees"),
    ]

    result = evaluator.evaluate_rule_matches([payment_rule()], expected_rules)

    assert result["expected_rule_coverage"] == pytest.approx(0.5)
    assert result["usable_rule_precision"] == pytest.approx(1.0)
    assert result["split_accuracy"] == pytest.approx(0.5)
    assert result["duplicate_or_overmerge_rate"] == pytest.approx(0.5)


def test_expected_rules_match_module_aliases_and_keyword_ratios():
    rule = generated_rule()
    rule["review_module"] = "Dispute Resolution"
    rule["risk_name"] = "jurisdiction venue is unclear"
    rule["trigger_condition"] = "Trigger when the contract lacks a court venue."
    rule["suggestion_template"] = "Add a clear court venue."
    rule["traces"][0]["evidence_before"] = "Any competent court may hear the dispute."
    rule["traces"][0]["evidence_after"] = "The court at Party A location may hear the dispute."
    expected_rules = [
        {
            "rule_id": "jurisdiction",
            "review_module": "Jurisdiction",
            "allowed_review_modules": ["Jurisdiction", "Dispute Resolution"],
            "risk_keywords": ["jurisdiction", "venue", "forum"],
            "trigger_keywords": ["court", "venue"],
            "suggestion_keywords": ["court", "venue"],
            "evidence_keywords": ["court", "Party A location"],
        }
    ]

    result = evaluator.evaluate_rule_matches([rule], expected_rules)

    assert result["expected_rule_coverage"] == pytest.approx(1.0)
    assert result["usable_rule_precision"] == pytest.approx(1.0)
    assert result["matched_rule_ids"] == ["jurisdiction"]


def test_workflow_diagnostics_count_diffs_and_validate_trace_evidence(monkeypatch):
    sample = {
        "name": "single contract diagnostic",
        "length_category": "short",
        "contract_type": "service",
        "review_role": "vendor",
        "before_text": "1. Party A pays in 90 days.\n2. Clause numbering only.",
        "after_text": "1. Party A pays in 30 days after invoice.\n2. Clause numbering only.",
        "expected_rules": [
            {
                "rule_id": "payment",
                "review_module": "Payment",
                "allowed_review_modules": ["Payment"],
                "risk_keywords": ["payment"],
                "trigger_keywords": ["30 days"],
                "suggestion_keywords": ["30 days"],
                "evidence_keywords": ["90 days", "30 days"],
                "expected_diff_keywords": ["90 days", "30 days"],
                "expected_change_type": "修改",
            }
        ],
    }
    valid_rule = payment_rule()
    valid_rule["traces"][0]["evidence_before"] = "Party A pays in 90 days."
    valid_rule["traces"][0]["evidence_after"] = "Party A pays in 30 days after invoice."
    forged_rule = payment_rule()
    valid_rule["traces"][0]["source_diff_id"] = "pair-1-expected-1"
    forged_rule["traces"][0]["source_diff_id"] = "pair-1-expected-1"
    forged_rule["traces"][0]["evidence_before"] = "This evidence is not in the contract."

    diagnostics = evaluator.evaluate_workflow_diagnostics(sample, [valid_rule, forged_rule])

    assert diagnostics["candidate_diff_count"] >= 1
    assert diagnostics["substantive_diff_count"] >= 1
    assert diagnostics["expected_diff_coverage"] == pytest.approx(1.0)
    assert diagnostics["diff_to_rule_conversion_rate"] == pytest.approx(2.0)
    assert diagnostics["rules_per_substantive_diff"] == pytest.approx(2.0)
    assert diagnostics["trace_validated_by_workflow_rate"] == pytest.approx(0.5)
    assert diagnostics["trace_diff_id_present_rate"] == pytest.approx(1.0)


def test_evaluate_sample_records_latency_and_split_metrics(monkeypatch):
    sample = matching_sample()
    monkeypatch.setattr(evaluator, "run_reverse_rule_extraction", lambda pairs: {"summary": "ok", "rules": [generated_rule()]})
    ticks = iter([10.0, 10.25])
    monkeypatch.setattr(evaluator.time, "perf_counter", lambda: next(ticks))

    row = evaluator.evaluate_sample(sample, run_index=2)

    assert row["name"] == sample["name"]
    assert row["run_index"] == 2
    assert row["length_category"] == "short"
    assert row["latency_ms"] == 250
    assert row["rule_count"] == 1
    assert row["generation_ok"] is True
    assert row["review_module_hit"] is True
    assert row["risk_hit"] is True
    assert row["trigger_hit"] is True
    assert row["suggestion_hit"] is True
    assert row["trace_evidence_accuracy"] is True
    assert row["schema_ok"] is True
    assert row["backend_fields_clean"] is True
    assert row["strict_passed"] is True
    assert row["weighted_score"] == pytest.approx(1.0)


def test_build_report_summarizes_overall_and_by_length():
    rows = [
        {
            "name": "short-pass",
            "length_category": "short",
            "expected_generated": True,
            "generated": True,
            "generation_ok": True,
            "review_module_hit": True,
            "risk_hit": True,
            "trigger_hit": True,
            "suggestion_hit": True,
            "trace_evidence_accuracy": True,
            "schema_ok": True,
            "backend_fields_clean": True,
            "duplicate_merge_accuracy": True,
            "strict_passed": True,
            "weighted_score": 1.0,
            "latency_ms": 100,
            "rule_count": 1,
            "parse_failure": False,
            "empty_result": False,
            "over_generated": False,
            "under_generated": False,
            "confidence_aligned": True,
            "notes": [],
        },
        {
            "name": "long-fail",
            "length_category": "long",
            "expected_generated": True,
            "generated": False,
            "generation_ok": False,
            "review_module_hit": False,
            "risk_hit": False,
            "trigger_hit": False,
            "suggestion_hit": False,
            "trace_evidence_accuracy": False,
            "schema_ok": True,
            "backend_fields_clean": True,
            "duplicate_merge_accuracy": True,
            "strict_passed": False,
            "weighted_score": 0.2,
            "latency_ms": 400,
            "rule_count": 0,
            "parse_failure": False,
            "empty_result": True,
            "over_generated": False,
            "under_generated": True,
            "confidence_aligned": False,
            "notes": ["generation_ok"],
        },
    ]

    report = evaluator.build_report(rows, fixture_path="fixture.json", runs=1, use_real_llm=True)

    assert report["summary"]["sample_count"] == 2
    assert report["summary"]["strict_pass_rate"] == pytest.approx(0.5)
    assert report["summary"]["weighted_score"] == pytest.approx(0.6)
    assert report["summary"]["latency_ms"]["avg"] == 250
    assert report["summary"]["under_generation_rate"] == pytest.approx(0.5)
    assert report["by_length"]["short"]["strict_pass_rate"] == pytest.approx(1.0)
    assert report["by_length"]["long"]["latency_ms"]["max"] == 400


def test_failure_rates_are_zero_when_denominator_is_empty():
    rows = [
        {
            "name": "expected-positive",
            "length_category": "long",
            "expected_generated": True,
            "generated": True,
            "generation_ok": True,
            "review_module_hit": True,
            "risk_hit": True,
            "trigger_hit": True,
            "suggestion_hit": True,
            "trace_evidence_accuracy": True,
            "schema_ok": True,
            "backend_fields_clean": True,
            "duplicate_merge_accuracy": True,
            "strict_passed": True,
            "weighted_score": 1.0,
            "latency_ms": 100,
            "rule_count": 1,
            "parse_failure": False,
            "empty_result": False,
            "over_generated": False,
            "under_generated": False,
            "confidence_aligned": True,
            "notes": [],
        }
    ]

    report = evaluator.build_report(rows, fixture_path="fixture.json", runs=1, use_real_llm=True)

    assert report["summary"]["over_generation_rate"] == 0


def test_write_report_writes_json_payload(tmp_path):
    output = tmp_path / "report.json"
    payload = {"summary": {"sample_count": 1}, "rows": [{"name": "sample"}]}

    evaluator.write_report(payload, output)

    assert json.loads(output.read_text(encoding="utf-8")) == payload


def test_merge_reports_combines_rows_and_rebuilds_summary(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    output = tmp_path / "merged.json"
    first.write_text(
        json.dumps(
            {
                "metadata": {"fixture_path": "fixture.json", "runs": 1, "use_real_llm": True},
                "rows": [
                    {
                        "name": "a",
                        "length_category": "short",
                        "expected_generated": True,
                        "generated": True,
                        "generation_ok": True,
                        "review_module_hit": True,
                        "risk_hit": True,
                        "trigger_hit": True,
                        "suggestion_hit": True,
                        "trace_evidence_accuracy": True,
                        "schema_ok": True,
                        "backend_fields_clean": True,
                        "duplicate_merge_accuracy": True,
                        "strict_passed": True,
                        "weighted_score": 1.0,
                        "latency_ms": 100,
                        "rule_count": 5,
                        "parse_failure": False,
                        "empty_result": False,
                        "over_generated": False,
                        "under_generated": False,
                        "confidence_aligned": True,
                        "notes": [],
                        "expected_rule_count": 5,
                        "generated_rule_count": 5,
                        "matched_expected_rule_count": 5,
                        "usable_generated_rule_count": 5,
                        "expected_rule_coverage": 1.0,
                        "usable_rule_precision": 1.0,
                        "split_accuracy": 1.0,
                        "duplicate_or_overmerge_rate": 0.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    second.write_text(json.dumps({"metadata": {}, "rows": []}), encoding="utf-8")

    report = evaluator.merge_reports([first, second], output_path=output)

    assert report["metadata"]["merged_report_count"] == 2
    assert report["summary"]["sample_count"] == 1
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["sample_count"] == 1


def test_main_returns_success_when_report_is_generated_even_with_metric_failures(monkeypatch, tmp_path):
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps([matching_sample()]), encoding="utf-8")
    output = tmp_path / "report.json"
    monkeypatch.setattr(evaluator, "run_reverse_rule_extraction", lambda pairs: {"summary": "none", "rules": []})
    monkeypatch.setattr(
        evaluator.sys,
        "argv",
        [
            "evaluate_reverse_rule_extraction.py",
            "--fixture",
            str(fixture),
            "--output",
            str(output),
        ],
    )

    assert evaluator.main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["strict_pass_rate"] == 0


def test_main_filters_samples_by_length_category(monkeypatch, tmp_path):
    fixture = tmp_path / "fixture.json"
    short_sample = {**matching_sample(), "name": "short sample", "length_category": "short"}
    long_sample = {**matching_sample(), "name": "long sample", "length_category": "long"}
    fixture.write_text(json.dumps([short_sample, long_sample]), encoding="utf-8")
    output = tmp_path / "report.json"
    seen: list[str] = []

    def fake_run(pairs):
        seen.append(pairs[0]["before_text"])
        return {"summary": "ok", "rules": [generated_rule()]}

    monkeypatch.setattr(evaluator, "run_reverse_rule_extraction", fake_run)
    monkeypatch.setattr(
        evaluator.sys,
        "argv",
        [
            "evaluate_reverse_rule_extraction.py",
            "--fixture",
            str(fixture),
            "--length",
            "long",
            "--output",
            str(output),
        ],
    )

    assert evaluator.main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["metadata"]["length_filter"] == "long"
    assert [row["name"] for row in report["rows"]] == ["long sample"]
    assert len(seen) == 1


def test_main_filters_samples_by_name(monkeypatch, tmp_path):
    fixture = tmp_path / "fixture.json"
    first_sample = {**matching_sample(), "name": "first sample"}
    second_sample = {**matching_sample(), "name": "second sample"}
    fixture.write_text(json.dumps([first_sample, second_sample]), encoding="utf-8")
    output = tmp_path / "report.json"
    monkeypatch.setattr(evaluator, "run_reverse_rule_extraction", lambda pairs: {"summary": "ok", "rules": [generated_rule()]})
    monkeypatch.setattr(
        evaluator.sys,
        "argv",
        [
            "evaluate_reverse_rule_extraction.py",
            "--fixture",
            str(fixture),
            "--name",
            "second sample",
            "--output",
            str(output),
        ],
    )

    assert evaluator.main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["metadata"]["name_filter"] == "second sample"
    assert [row["name"] for row in report["rows"]] == ["second sample"]


def test_load_env_file_sets_missing_keys_without_overwriting(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "MINIMAX_API_KEY=file-key",
                "LLM_MODEL_NAME=file-model",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MINIMAX_API_KEY", "existing-key")
    monkeypatch.delenv("LLM_MODEL_NAME", raising=False)

    evaluator._load_env_file(env_file)

    assert evaluator.os.getenv("MINIMAX_API_KEY") == "existing-key"
    assert evaluator.os.getenv("LLM_MODEL_NAME") == "file-model"


def test_expand_text_supports_repeatable_parts():
    sample = {
        "before_text": {
            "parts": ["header"],
            "repeat": ["boilerplate"],
            "repeat_count": 3,
            "suffix": ["target"],
        }
    }

    assert evaluator._expand_text(sample, "before_text") == "header\nboilerplate\nboilerplate\nboilerplate\ntarget"


def test_pairs_from_sample_defaults_to_single_contract_even_with_pair_delimiter():
    sample = {
        "name": "single contract with delimiter text",
        "contract_type": "service",
        "review_role": "vendor",
        "before_text": "before clause one\n---PAIR---\nbefore clause two",
        "after_text": "after clause one\n---PAIR---\nafter clause two",
    }

    pairs = evaluator._pairs_from_sample(sample)

    assert pairs == [
        {
            "pair_id": "pair-1",
            "before_text": sample["before_text"],
            "after_text": sample["after_text"],
            "contract_type": "service",
            "review_role": "vendor",
        }
    ]


def test_pairs_from_sample_splits_only_when_fixture_mode_is_multi_pair():
    sample = {
        "name": "explicit multi pair sample",
        "fixture_mode": "multi_pair",
        "contract_type": "service",
        "review_role": "vendor",
        "before_text": "before clause one\n---PAIR---\nbefore clause two",
        "after_text": "after clause one\n---PAIR---\nafter clause two",
    }

    pairs = evaluator._pairs_from_sample(sample)

    assert [pair["pair_id"] for pair in pairs] == ["pair-1", "pair-2"]
    assert [pair["before_text"] for pair in pairs] == ["before clause one", "before clause two"]
    assert [pair["after_text"] for pair in pairs] == ["after clause one", "after clause two"]


def test_pairs_from_sample_rejects_mismatched_explicit_multi_pair_parts():
    sample = {
        "name": "broken multi pair sample",
        "fixture_mode": "multi_pair",
        "contract_type": "service",
        "review_role": "vendor",
        "before_text": "before clause one\n---PAIR---\nbefore clause two",
        "after_text": "after only one",
    }

    with pytest.raises(ValueError, match="multi_pair"):
        evaluator._pairs_from_sample(sample)


def test_benchmark_fixture_has_expected_size_and_length_buckets():
    fixture_path = Path(__file__).parent / "fixtures" / "reverse_rule_eval_benchmark.json"
    samples = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert len(samples) == 13
    assert Counter(sample["length_category"] for sample in samples) == {
        "short": 6,
        "medium": 4,
        "long": 3,
    }
    assert any("---PAIR---" in sample["before_text"] for sample in samples)
    assert any("---PAIR---" not in sample["before_text"] for sample in samples)
    for sample in samples:
        if sample["length_category"] == "short":
            assert len(sample.get("expected_rules", [])) >= 5
        elif sample["length_category"] == "medium":
            assert len(sample.get("expected_rules", [])) >= 8
        elif sample["length_category"] == "long":
            assert len(sample.get("expected_rules", [])) >= 10
        for expected_rule in sample["expected_rules"]:
            assert expected_rule["rule_id"]
            assert expected_rule["review_module"]
            assert expected_rule["risk_keywords"]
            assert expected_rule["trigger_keywords"]
            assert expected_rule["suggestion_keywords"]
            assert expected_rule["evidence_keywords"]
        before_len = len(evaluator._expand_text(sample, "before_text"))
        after_len = len(evaluator._expand_text(sample, "after_text"))
        if sample["length_category"] == "short":
            assert 500 <= before_len <= 1500
            assert 500 <= after_len <= 1500
        elif sample["length_category"] == "medium":
            assert 3000 <= before_len <= 6000
            assert 3000 <= after_len <= 6000
        elif sample["length_category"] == "long":
            assert 10000 <= before_len <= 20000
            assert 10000 <= after_len <= 20000
    assert sum(len(sample["expected_rules"]) for sample in samples) >= 92
