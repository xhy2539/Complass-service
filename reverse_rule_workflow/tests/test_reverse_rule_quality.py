import json
from pathlib import Path
import tempfile

from app.chains.reverse_rule_graph import run_reverse_rule_extraction
from app.kb import retriever
from app.kb.loader import load_reverse_rule_cases
from app.models.reverse_rule import CandidateRuleForDB
from app.services.diff_service import diff_contract_pair
from app.services.query_builder import build_retrieval_queries
from app.services.rule_code import to_rule_record


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "reverse_rule_samples.json"
BACKEND_FIELDS = {
    "id",
    "version_id",
    "rule_code",
    "enabled",
    "created_at",
    "updated_at",
}


def load_samples() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def pair_from_sample(sample: dict, pair_id: str = "pair-1") -> dict:
    return {
        "pair_id": pair_id,
        "before_text": sample["before_text"],
        "after_text": sample["after_text"],
        "contract_type": sample["contract_type"],
        "review_role": sample["review_role"],
    }


def sample_by_name(name_prefix: str) -> dict:
    for sample in load_samples():
        if sample["name"].startswith(name_prefix):
            return sample
    raise AssertionError(f"sample not found: {name_prefix}")


def assert_rule_matches_sample(rule: dict, sample: dict) -> None:
    assert rule["review_module"] in sample["expected_review_modules"]
    assert any(keyword in rule["risk_name"] for keyword in sample["expected_risk_keywords"])
    assert any(keyword in rule["trigger_condition"] for keyword in sample["expected_trigger_keywords"])
    assert any(keyword in rule["suggestion_template"] for keyword in sample["expected_suggestion_keywords"])


def test_quality_fixture_has_required_sample_shape():
    samples = load_samples()

    assert len(samples) >= 8
    for sample in samples:
        for field in [
            "name",
            "contract_type",
            "review_role",
            "before_text",
            "after_text",
            "expected_review_modules",
            "expected_risk_keywords",
            "expected_trigger_keywords",
            "expected_suggestion_keywords",
            "should_generate_rule",
        ]:
            assert field in sample
        if sample["should_generate_rule"]:
            assert sample["min_confidence"] >= 0.5
        else:
            assert sample["max_confidence"] < 0.5


def test_payment_clause_generates_payment_term_rule():
    sample = sample_by_name("付款期限")
    result = run_reverse_rule_extraction([pair_from_sample(sample)])

    assert len(result["rules"]) == 1
    assert_rule_matches_sample(result["rules"][0], sample)


def test_liability_change_generates_liability_cap_rule():
    sample = sample_by_name("违约责任")
    result = run_reverse_rule_extraction([pair_from_sample(sample)])

    assert len(result["rules"]) == 1
    assert_rule_matches_sample(result["rules"][0], sample)


def test_termination_clause_generates_notice_period_rule():
    sample = sample_by_name("解除条款")
    result = run_reverse_rule_extraction([pair_from_sample(sample)])

    assert len(result["rules"]) == 1
    assert_rule_matches_sample(result["rules"][0], sample)


def test_plain_polish_generates_no_rule_or_low_confidence_trace():
    sample = sample_by_name("普通润色")
    result = run_reverse_rule_extraction([pair_from_sample(sample)])

    if not result["rules"]:
        return
    confidences = [
        trace["confidence"]
        for rule in result["rules"]
        for trace in rule["traces"]
    ]
    assert confidences
    assert max(confidences) <= sample["max_confidence"]


def test_similar_rules_merge_traces_from_multiple_pairs():
    sample = sample_by_name("多组合同重复规则")
    before_a, before_b = sample["before_text"].split("\n---PAIR---\n")
    after_a, after_b = sample["after_text"].split("\n---PAIR---\n")
    pairs = [
        {
            "pair_id": "pair-a",
            "before_text": before_a,
            "after_text": after_a,
            "contract_type": sample["contract_type"],
            "review_role": sample["review_role"],
        },
        {
            "pair_id": "pair-b",
            "before_text": before_b,
            "after_text": after_b,
            "contract_type": sample["contract_type"],
            "review_role": sample["review_role"],
        },
    ]

    result = run_reverse_rule_extraction(pairs)

    assert len(result["rules"]) == 1
    assert {trace["pair_id"] for trace in result["rules"][0]["traces"]} == {"pair-a", "pair-b"}


def test_all_generated_rules_have_example_clause_and_traces():
    samples = [sample for sample in load_samples() if sample["should_generate_rule"] and not sample["name"].startswith("多组")]
    results = [
        run_reverse_rule_extraction([pair_from_sample(sample, f"pair-{index}")])
        for index, sample in enumerate(samples, start=1)
    ]

    rules = [rule for result in results for rule in result["rules"]]
    assert rules
    for rule in rules:
        assert rule["example_clause"].strip()
        assert rule["traces"]


def test_all_traces_have_before_and_after_evidence():
    sample = sample_by_name("付款期限")
    result = run_reverse_rule_extraction([pair_from_sample(sample)])

    for rule in result["rules"]:
        for trace in rule["traces"]:
            assert trace["evidence_before"].strip()
            assert trace["evidence_after"].strip()


def test_all_rules_match_candidate_schema():
    sample = sample_by_name("保密期限")
    result = run_reverse_rule_extraction([pair_from_sample(sample)])

    assert result["rules"]
    for rule in result["rules"]:
        CandidateRuleForDB.model_validate(rule)


def test_kb_retrieval_is_relevant_to_diff_not_random(monkeypatch):
    persist_dir = Path(tempfile.gettempdir()) / "reverse_rule_workflow_tests" / "test_reverse_rule_kb_quality"
    retriever.build_reverse_rule_kb(load_reverse_rule_cases(), persist_dir)
    monkeypatch.setattr(retriever, "DEFAULT_PERSIST_DIR", str(persist_dir))

    payment_results = retriever.retrieve_reverse_rule_cases(
        "付款条款 服务合同 乙方 90日改30日 合法有效发票",
        review_module="付款条款",
        k=3,
    )
    polish_results = retriever.retrieve_reverse_rule_cases(
        "通用条款 服务合同 乙方 仅措辞润色 未发生实质权利义务变化",
        review_module="通用条款",
        k=3,
    )

    assert payment_results
    assert payment_results[0]["review_module"] == "付款条款"
    assert polish_results == []


def test_to_rule_record_generates_backend_fields():
    sample = sample_by_name("付款期限")
    result = run_reverse_rule_extraction([pair_from_sample(sample)])
    candidate = CandidateRuleForDB.model_validate(result["rules"][0])

    record = to_rule_record(candidate)

    assert record.id
    assert record.version_id
    assert record.rule_code
    assert record.enabled is True
    assert record.created_at
    assert record.updated_at


def test_llm_candidate_output_does_not_include_backend_fields():
    sample = sample_by_name("付款期限")
    result = run_reverse_rule_extraction([pair_from_sample(sample)])

    for rule in result["rules"]:
        assert BACKEND_FIELDS.isdisjoint(rule)


def test_diff_ignores_numbering_punctuation_format_only_change():
    pair = {
        "pair_id": "pair-format",
        "before_text": "1、甲方应按约定支付服务费。",
        "after_text": "（一）甲方应当按照约定支付服务费用。",
        "contract_type": "服务合同",
        "review_role": "乙方",
    }

    from app.models.reverse_rule import ContractPair

    diff = diff_contract_pair(ContractPair.model_validate(pair))

    assert all(not clause.is_substantive for clause in diff.changed_clauses)


def test_diff_uses_change_type_changed_for_substantive_text_change():
    from app.models.reverse_rule import ContractPair

    pair = ContractPair.model_validate(
        {
            "pair_id": "pair-change-type",
            "before_text": "甲方应在验收后90日内支付服务费。",
            "after_text": "甲方应在验收并收到合法有效发票后30日内支付服务费。",
            "contract_type": "服务合同",
            "review_role": "乙方",
        }
    )

    diff = diff_contract_pair(pair)

    assert diff.changed_clauses
    assert diff.changed_clauses[0].change_type == "更改"


def test_diff_detects_moved_clause_without_generating_substantive_change():
    from app.models.reverse_rule import ContractPair

    pair = ContractPair.model_validate(
        {
            "pair_id": "pair-move",
            "before_text": "\n".join(
                [
                    "1. 甲方应在验收后30日内支付服务费。",
                    "2. 乙方应在服务期内及时响应故障。",
                ]
            ),
            "after_text": "\n".join(
                [
                    "1. 乙方应在服务期内及时响应故障。",
                    "2. 甲方应在验收后30日内支付服务费。",
                ]
            ),
            "contract_type": "服务合同",
            "review_role": "乙方",
        }
    )

    diff = diff_contract_pair(pair)

    assert {clause.change_type for clause in diff.changed_clauses} == {"移位"}
    assert all(not clause.is_substantive for clause in diff.changed_clauses)


def test_long_contract_ip_and_sla_changes_split_into_separate_diffs():
    from app.models.reverse_rule import ContractPair

    repeated = "\n".join(
        [
            "项目实施期间，乙方应提交周报、会议纪要、需求确认单、测试记录和上线方案。甲方应配合提供业务资料、测试账号和验收反馈。"
            for _ in range(35)
        ]
    )
    before_text = "\n".join(
        [
            "甲方委托乙方建设业务中台系统，项目包括需求调研、原型设计、系统开发、联调测试、上线支持和运维交接。",
            repeated,
            "乙方完成开发成果后交付甲方使用，合同未明确源代码和技术文档的权利归属。系统上线后乙方应尽快处理故障，未约定响应时间和未达标扣款机制。",
        ]
    )
    after_text = "\n".join(
        [
            "甲方委托乙方建设业务中台系统，项目包括需求调研、原型设计、系统开发、联调测试、上线支持和运维交接。",
            repeated,
            "乙方为甲方定制开发形成的源代码、数据库设计文档、接口文档和交付成果的知识产权归甲方所有。系统上线后一级故障30分钟内响应、4小时内恢复，连续未达标的甲方可扣减当月服务费10%。",
        ]
    )
    pair = ContractPair.model_validate(
        {
            "pair_id": "pair-long-ip-sla",
            "before_text": before_text,
            "after_text": after_text,
            "contract_type": "软件开发服务合同",
            "review_role": "甲方",
        }
    )

    diff = diff_contract_pair(pair)
    modules = {clause.review_module for clause in diff.changed_clauses if clause.is_substantive}

    assert "知识产权" in modules
    assert "服务水平" in modules
    assert len([clause for clause in diff.changed_clauses if clause.is_substantive]) >= 2


def test_query_contains_module_direction_contract_type_and_role_without_full_text():
    sample = sample_by_name("付款期限")
    from app.models.reverse_rule import ContractPair

    pair = ContractPair.model_validate(pair_from_sample(sample))
    diff = diff_contract_pair(pair)
    queries = build_retrieval_queries(diff, pair.contract_type, pair.review_role)

    assert len(queries) == 1
    query = queries[0]
    assert "付款条款" in query
    assert "90日改30日" in query
    assert "服务合同" in query
    assert "乙方" in query
    assert sample["before_text"] not in query
    assert sample["after_text"] not in query
