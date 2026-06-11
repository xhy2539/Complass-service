import re
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from app.chains.reverse_rule_graph import _has_llm_credentials
from app.chains.reverse_rule_graph import _identify_base_info_node
from app.chains.reverse_rule_graph import _parse_rule_batch_from_text
from app.chains.reverse_rule_graph import _resolve_chat_model_config
from app.chains.reverse_rule_graph import build_reverse_rule_graph
from app.chains.reverse_rule_graph import run_reverse_rule_extraction
from app.models.reverse_rule import CandidateRuleForDB
from app.models.reverse_rule import ContractPair
from app.services.base_info import identify_base_info_for_pair
from app.services.rule_code import to_rule_record


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
    monkeypatch.chdir(_test_workdir(request.node.name))


def _test_workdir(name: str) -> Path:
    safe_name = re.sub(r"[^a-zA-Z0-9_]+", "_", name)
    path = Path(tempfile.gettempdir()) / "reverse_rule_workflow_tests" / "graph_env" / safe_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def payment_pair(pair_id: str = "pair-1") -> dict:
    return {
        "pair_id": pair_id,
        "before_text": "甲方应在验收后90日内向乙方支付服务费。",
        "after_text": "甲方应在验收并收到合法有效发票后30日内向乙方支付服务费。",
        "contract_type": "服务合同",
        "review_role": "乙方",
    }


def liability_pair(pair_id: str = "pair-2") -> dict:
    return {
        "pair_id": pair_id,
        "before_text": "任何一方违约时，应赔偿对方直接损失。",
        "after_text": "任何一方违约时，应赔偿对方全部损失，并承担律师费。",
        "contract_type": "服务合同",
        "review_role": "甲方",
    }


def test_single_contract_pair_generates_candidate_rule():
    result = run_reverse_rule_extraction([payment_pair()])

    assert result["summary"]
    assert len(result["rules"]) == 1
    rule = result["rules"][0]
    assert rule["contract_type"] == "服务合同"
    assert rule["review_module"] == "付款条款"
    assert rule["risk_name"]
    assert rule["check_point"]
    assert rule["trigger_condition"]
    assert rule["default_risk_level"] in {"低", "中", "高"}
    assert rule["suggestion_template"]
    assert rule["example_clause"]
    assert rule["traces"][0]["pair_id"] == "pair-1"
    assert 0 <= rule["traces"][0]["confidence"] <= 1


def test_two_contract_pairs_generate_and_merge_rules():
    result = run_reverse_rule_extraction([payment_pair("pair-a"), liability_pair("pair-b")])

    assert len(result["rules"]) == 2
    trace_pair_ids = {
        trace["pair_id"]
        for rule in result["rules"]
        for trace in rule["traces"]
    }
    assert trace_pair_ids == {"pair-a", "pair-b"}


def test_empty_input_raises_error():
    with pytest.raises(ValueError, match="1-5"):
        run_reverse_rule_extraction([])


def test_more_than_five_pairs_raises_error():
    with pytest.raises(ValueError, match="1-5"):
        run_reverse_rule_extraction([payment_pair(str(index)) for index in range(6)])


def test_plain_wording_polish_does_not_generate_high_confidence_rule():
    result = run_reverse_rule_extraction(
        [
            {
                "before_text": "甲方应按约定支付服务费。",
                "after_text": "甲方应当按照约定支付服务费用。",
                "contract_type": "服务合同",
                "review_role": "乙方",
            }
        ]
    )

    assert result["rules"] == []
    assert "未生成" in result["summary"]


def test_rule_output_matches_candidate_schema():
    result = run_reverse_rule_extraction([payment_pair()])

    parsed = CandidateRuleForDB.model_validate(result["rules"][0])
    assert parsed.risk_name == result["rules"][0]["risk_name"]


def test_kb_fallback_runs_without_external_module(monkeypatch):
    import app.kb.retriever as retriever

    def broken_retriever(*args, **kwargs):
        raise RuntimeError("external kb unavailable")

    monkeypatch.setattr(retriever, "retrieve_reverse_rule_cases", broken_retriever)

    result = run_reverse_rule_extraction([payment_pair()])

    assert len(result["rules"]) == 1
    assert result["rules"][0]["traces"][0]["pair_id"] == "pair-1"


def test_base_info_identifier_infers_purchase_installation_context(monkeypatch):
    monkeypatch.setenv("DISABLE_REAL_LLM", "1")
    pair = ContractPair(
        pair_id="pair-base-info",
        before_text=(
            "智能设备采购及安装调试合同\n"
            "甲方拟采购智能巡检设备，乙方负责设备供应、安装调试和验收支持。"
        ),
        after_text=(
            "智能设备采购及安装调试合同\n"
            "甲方拟采购智能巡检设备，乙方负责设备供应、安装调试和验收支持。"
        ),
    )

    base_info = identify_base_info_for_pair(pair)

    assert base_info.contract_type == "采购合同"
    assert base_info.review_role == "乙方"
    assert base_info.contract_subject == "智能设备采购及安装调试"
    assert base_info.party_a_identity == "采购方"
    assert base_info.party_b_identity == "供应及安装调试方"
    assert 0 <= base_info.confidence <= 1


def test_explicit_generic_metadata_skips_base_info_identification(monkeypatch):
    import app.chains.reverse_rule_graph as graph

    calls: list[str] = []

    def fail_if_called(pair: ContractPair):
        calls.append(pair.pair_id)
        raise AssertionError("base info identification should not run")

    monkeypatch.setattr(graph, "identify_base_info_for_pair", fail_if_called)
    pair = ContractPair(
        pair_id="pair-explicit-generic",
        before_text="甲方应在验收后90日内向乙方付款。",
        after_text="甲方应在验收并收到发票后30日内向乙方付款。",
        contract_type="通用",
        review_role="通用",
    )

    result = _identify_base_info_node({"pairs": [pair]})

    assert calls == []
    assert result["base_infos"][0].contract_type == "通用"
    assert result["base_infos"][0].review_role == "通用"


def test_missing_metadata_still_uses_base_info_identification(monkeypatch):
    import app.chains.reverse_rule_graph as graph

    calls: list[str] = []

    def identify(pair: ContractPair):
        calls.append(pair.pair_id)
        return graph.ContractBaseInfo(
            pair_id=pair.pair_id,
            contract_type="采购合同",
            review_role="乙方",
            contract_subject="设备采购",
            party_a_identity="采购方",
            party_b_identity="供应方",
            confidence=0.8,
        )

    monkeypatch.setattr(graph, "identify_base_info_for_pair", identify)
    pair = ContractPair(
        pair_id="pair-auto",
        before_text="甲方采购设备。",
        after_text="甲方采购设备并要求乙方安装调试。",
    )

    result = _identify_base_info_node({"pairs": [pair]})

    assert calls == ["pair-auto"]
    assert result["base_infos"][0].contract_type == "采购合同"
    assert result["base_infos"][0].review_role == "乙方"


def test_graph_contains_parallel_base_info_and_diff_nodes():
    graph = build_reverse_rule_graph().get_graph()

    assert "identify_base_info" in graph.nodes
    assert "diff_pairs" in graph.nodes
    assert "process_all_pairs" in graph.nodes
    assert any(edge.source == "validate_input" and edge.target == "identify_base_info" for edge in graph.edges)
    # validate_input → diff_pairs removed after graph restructure (diff_pairs now parallel via base_info)
    assert any(edge.source == "identify_base_info" and edge.target == "process_all_pairs" for edge in graph.edges)
    assert any(edge.source == "diff_pairs" and edge.target == "process_all_pairs" for edge in graph.edges)


def test_inferred_base_info_is_used_for_retrieval_filters_and_rules(monkeypatch):
    import app.kb.retriever as retriever

    captured_calls: list[dict] = []

    def fake_retrieve_reverse_rule_cases(*args, **kwargs):
        captured_calls.append(kwargs)
        return [
            {
                "case_id": "payment_001",
                "contract_type": ["采购合同"],
                "review_role": ["乙方"],
                "review_module": "付款条款",
                "change_pattern": "付款期限由90日缩短为30日",
                "before_example": "甲方应在验收后90日内付款。",
                "after_example": "甲方应在验收后30日内付款。",
                "diff_summary": "缩短付款期限。",
                "user_intent": "控制回款周期。",
                "risk_name": "付款期限过长",
                "check_point": "检查付款期限是否过长。",
                "trigger_condition": "付款期限超过30日时触发。",
                "default_risk_level": "中",
                "suggestion_template": "建议约定30日内付款。",
                "example_clause": "甲方应在验收后90日内付款。",
            }
        ]

    monkeypatch.setattr(retriever, "retrieve_reverse_rule_cases", fake_retrieve_reverse_rule_cases)
    result = run_reverse_rule_extraction(
        [
            {
                "pair_id": "pair-inferred",
                "before_text": (
                    "智能设备采购及安装调试合同\n"
                    "甲方采购智能设备，乙方负责供应、安装调试。甲方应在验收后90日内付款。"
                ),
                "after_text": (
                    "智能设备采购及安装调试合同\n"
                    "甲方采购智能设备，乙方负责供应、安装调试。甲方应在验收后30日内付款。"
                ),
            }
        ]
    )

    assert captured_calls
    assert captured_calls[0]["contract_type"] == "采购合同"
    assert captured_calls[0]["review_role"] == "乙方"
    assert result["rules"][0]["contract_type"] == "采购合同"
    assert "base_infos" not in result


def test_input_metadata_takes_precedence_over_identified_base_info(monkeypatch):
    import app.kb.retriever as retriever

    captured_calls: list[dict] = []

    def fake_retrieve_reverse_rule_cases(*args, **kwargs):
        captured_calls.append(kwargs)
        return [
            {
                "case_id": "payment_001",
                "contract_type": ["服务合同"],
                "review_role": ["甲方"],
                "review_module": "付款条款",
                "change_pattern": "付款期限由90日缩短为30日",
                "risk_name": "付款期限过长",
                "check_point": "检查付款期限是否过长。",
                "trigger_condition": "付款期限超过30日时触发。",
                "default_risk_level": "中",
                "suggestion_template": "建议约定30日内付款。",
                "example_clause": "甲方应在验收后90日内付款。",
            }
        ]

    monkeypatch.setattr(retriever, "retrieve_reverse_rule_cases", fake_retrieve_reverse_rule_cases)
    result = run_reverse_rule_extraction(
        [
            {
                "pair_id": "pair-input-first",
                "before_text": (
                    "智能设备采购及安装调试合同\n"
                    "甲方采购智能设备，乙方负责供应、安装调试。甲方应在验收后90日内付款。"
                ),
                "after_text": (
                    "智能设备采购及安装调试合同\n"
                    "甲方采购智能设备，乙方负责供应、安装调试。甲方应在验收后30日内付款。"
                ),
                "contract_type": "服务合同",
                "review_role": "甲方",
            }
        ]
    )

    assert captured_calls
    assert captured_calls[0]["contract_type"] == "服务合同"
    assert captured_calls[0]["review_role"] == "甲方"
    assert result["rules"][0]["contract_type"] == "服务合同"


def test_to_rule_record_generates_backend_fields():
    result = run_reverse_rule_extraction([payment_pair()])
    candidate = CandidateRuleForDB.model_validate(result["rules"][0])

    record = to_rule_record(candidate)

    assert record.id
    assert record.version_id
    assert record.rule_code.startswith("RULE-")
    assert record.enabled is True
    assert isinstance(record.created_at, datetime)
    assert isinstance(record.updated_at, datetime)
    assert record.contract_type == candidate.contract_type


def test_minimax_model_config_uses_openai_compatible_endpoint(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
    monkeypatch.setenv("LLM_MODEL_NAME", "MiniMax-M2.7")
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)

    config = _resolve_chat_model_config()

    assert _has_llm_credentials() is True
    assert config["api_key"] == "test-minimax-key"
    assert config["model"] == "MiniMax-M2.7"
    assert config["base_url"] == "https://api.minimax.io/v1"


def test_loads_minimax_config_from_dotenv(monkeypatch):
    dotenv = Path.cwd() / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=minimax",
                "MINIMAX_API_KEY=test-dotenv-key",
                "LLM_MODEL_NAME=MiniMax-M2.7",
                "MINIMAX_BASE_URL=https://api.minimax.io/v1",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL_NAME", raising=False)
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)

    config = _resolve_chat_model_config()

    assert _has_llm_credentials() is True
    assert config["api_key"] == "test-dotenv-key"
    assert config["model"] == "MiniMax-M2.7"


def test_parses_minimax_thinking_markdown_json_response():
    text = """
<think>先分析一下用户需求。</think>

```json
{"rules": []}
```
"""

    parsed = _parse_rule_batch_from_text(text)

    assert parsed.rules == []


def test_parses_minimax_array_response_and_adds_trace():
    text = """
[
  {
    "rule_name": "付款期限过长",
    "contract_type": ["服务合同"],
    "review_module": "付款条款",
    "check_point": "检查付款期限是否过长。",
    "trigger_condition": "付款期限超过30日时触发。",
    "default_risk_level": "中",
    "suggestion_template": "建议缩短付款期限。",
    "example_clause": "甲方应在验收后90日内付款。"
  }
]
"""
    from app.models.reverse_rule import ContractPair
    from app.services.diff_service import diff_contract_pair

    pair = ContractPair(
        pair_id="pair-1",
        before_text="甲方应在验收后90日内付款。",
        after_text="甲方应在验收后30日内付款。",
        contract_type="服务合同",
    )

    parsed = _parse_rule_batch_from_text(text, pair=pair, diff_result=diff_contract_pair(pair))

    assert len(parsed.rules) == 1
    assert parsed.rules[0].risk_name == "付款期限过长"
    assert parsed.rules[0].contract_type == "服务合同"
    assert parsed.rules[0].traces[0].pair_id == "pair-1"
def test_substantive_diff_generates_low_confidence_rule_without_retrieved_cases(monkeypatch):
    import app.chains.reverse_rule_graph as graph

    monkeypatch.setattr(graph, "retrieve_cases_for_diff", lambda *args, **kwargs: [])

    result = run_reverse_rule_extraction(
        [
            {
                "pair_id": "pair-no-case",
                "before_text": "乙方应在合同签署后向甲方提交项目计划。",
                "after_text": "乙方应在合同签署后5日内向甲方提交项目计划，逾期应每日按合同总价1%承担违约金。",
                "contract_type": "服务合同",
                "review_role": "通用",
            }
        ]
    )

    assert len(result["rules"]) == 1
    rule = result["rules"][0]
    assert rule["review_perspective"] == "通用"
    assert rule["traces"][0]["pair_id"] == "pair-no-case"
    assert rule["traces"][0]["confidence"] < 0.6
    assert "无高匹配知识库案例" in rule["traces"][0]["user_intent"]
def test_parses_llm_granular_review_perspective_as_rule_library_perspective():
    text = """
{
  "rules": [
    {
      "risk_name": "管辖法院不利",
      "contract_type": "采购合同",
      "review_perspective": "起诉方",
      "review_module": "管辖法院",
      "check_point": "检查管辖法院是否便利。",
      "trigger_condition": "约定由对方所在地法院管辖时触发。",
      "default_risk_level": "中",
      "suggestion_template": "建议约定审核方所在地法院管辖。",
      "example_clause": "由乙方所在地人民法院管辖。",
      "traces": [
        {
          "pair_id": "pair-1",
          "evidence_before": "提交上海仲裁委员会仲裁。",
          "evidence_after": "由乙方所在地人民法院管辖。",
          "diff_summary": "争议解决路径发生变化。",
          "user_intent": "提高维权便利性。",
          "confidence": 0.72
        }
      ]
    }
  ]
}
"""

    parsed = _parse_rule_batch_from_text(text)

    assert len(parsed.rules) == 1
    assert parsed.rules[0].review_perspective == "甲方"
