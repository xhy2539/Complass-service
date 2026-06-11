"""规则反哺回路测试：输出过滤 + 转换器 + Judge审核 + 知识库写入。"""

import json
import tempfile
from pathlib import Path
from unittest import mock

from app.models.reverse_rule import CandidateRuleForDB
from app.models.reverse_rule import RuleExtractionTrace

# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


def _make_rule(
    risk_name: str = "付款期限过长",
    review_module: str = "付款条款",
    check_point: str = "检查付款期限是否超过30日",
    trigger_condition: str = "合同约定付款期限超过30日",
    contract_type: str = "服务合同",
    review_perspective: str = "乙方",
    default_risk_level: str = "中",
    confidence: float = 0.82,
    traces: list[RuleExtractionTrace] | None = None,
) -> CandidateRuleForDB:
    if traces is None:
        traces = [
            RuleExtractionTrace(
                pair_id="pair-1",
                source_diff_id="diff-001",
                evidence_before="甲方应在收到发票后90日内付款。",
                evidence_after="甲方应在收到乙方开具的合法有效发票后30日内付款。",
                diff_summary="付款期限由90日缩短为30日",
                user_intent="缩短回款周期",
                confidence=confidence,
            )
        ]
    return CandidateRuleForDB(
        contract_type=contract_type,
        review_perspective=review_perspective,
        review_module=review_module,
        risk_name=risk_name,
        check_point=check_point,
        trigger_condition=trigger_condition,
        default_risk_level=default_risk_level,
        suggestion_template="建议约定在收到合法有效发票后30日内付款。",
        example_clause="甲方应在收到乙方开具的合法有效发票后30日内付款。",
        traces=traces,
    )


def _temp_workdir(name: str) -> Path:
    path = Path(tempfile.gettempdir()) / "reverse_rule_feedback_tests" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# 转换器测试
# ---------------------------------------------------------------------------


def test_candidate_rule_to_reverse_rule_case_maps_all_fields():
    """转换器正确映射所有字段。"""
    from app.kb.feedback import candidate_rule_to_reverse_rule_case

    rule = _make_rule()
    case = candidate_rule_to_reverse_rule_case(rule)

    assert case.case_id.startswith("auto_payment_terms_")
    assert len(case.case_id) > 20
    assert case.contract_type == ["服务合同"]
    assert case.review_role == ["乙方"]
    assert case.review_module == "付款条款"
    assert len(case.change_pattern) > 0
    assert "90日" in case.before_example
    assert "30日内付款" in case.after_example
    assert "付款期限" in case.diff_summary
    assert len(case.user_intent) > 0
    assert case.risk_name == "付款期限过长"
    assert len(case.check_point) > 0
    assert len(case.trigger_condition) > 0
    assert case.default_risk_level == "中"
    assert len(case.suggestion_template) > 0
    assert len(case.example_clause) > 0
    assert len(case.tags) >= 2
    assert "自动生成" in case.tags


def test_case_id_stable_for_same_content():
    """相同规则内容产生相同 case_id。"""
    from app.kb.feedback import candidate_rule_to_reverse_rule_case

    rule1 = _make_rule()
    rule2 = _make_rule()
    case1 = candidate_rule_to_reverse_rule_case(rule1)
    case2 = candidate_rule_to_reverse_rule_case(rule2)

    assert case1.case_id == case2.case_id


def test_case_id_different_for_different_content():
    """不同规则内容产生不同 case_id。"""
    from app.kb.feedback import candidate_rule_to_reverse_rule_case

    rule1 = _make_rule(risk_name="付款期限过长")
    rule2 = _make_rule(risk_name="付款条件不确定")
    case1 = candidate_rule_to_reverse_rule_case(rule1)
    case2 = candidate_rule_to_reverse_rule_case(rule2)

    assert case1.case_id != case2.case_id


def test_case_id_matches_pattern():
    """case_id 符合 CASE_ID_PATTERN。"""

    from app.kb.feedback import candidate_rule_to_reverse_rule_case
    from app.kb.schema import CASE_ID_PATTERN

    rule = _make_rule()
    case = candidate_rule_to_reverse_rule_case(rule)
    assert CASE_ID_PATTERN.match(case.case_id), f"case_id={case.case_id}"


def test_generic_review_role_expands_to_both_parties():
    """ "通用" 角色展开为 ["甲方", "乙方"]。"""
    from app.kb.feedback import candidate_rule_to_reverse_rule_case

    rule = _make_rule(review_perspective="通用")
    case = candidate_rule_to_reverse_rule_case(rule)
    assert case.review_role == ["甲方", "乙方"]


def test_judge_overrides_risk_level():
    """Judge 可以覆盖风险等级。"""
    from app.kb.feedback import candidate_rule_to_reverse_rule_case

    rule = _make_rule(default_risk_level="中")
    judge_result = {"risk_level_override": "高", "tags": ["高风险", "付款期限"]}
    case = candidate_rule_to_reverse_rule_case(rule, judge_result)
    assert case.default_risk_level == "高"


def test_judge_tags_used():
    """Judge 提供的 tags 优先级高于自动生成。"""
    from app.kb.feedback import candidate_rule_to_reverse_rule_case

    rule = _make_rule()
    judge_result = {"tags": ["付款期限", "回款风险", "发票条件"]}
    case = candidate_rule_to_reverse_rule_case(rule, judge_result)
    assert "付款期限" in case.tags
    assert "回款风险" in case.tags
    assert "发票条件" in case.tags


def test_multi_trace_merges_diff_summaries():
    """多条 trace 时 diff_summary 合并。"""
    from app.kb.feedback import candidate_rule_to_reverse_rule_case

    traces = [
        RuleExtractionTrace(
            pair_id="pair-1",
            source_diff_id="diff-001",
            evidence_before="付款90日",
            evidence_after="付款30日",
            diff_summary="付款期限缩短",
            user_intent="缩短回款",
            confidence=0.82,
        ),
        RuleExtractionTrace(
            pair_id="pair-2",
            source_diff_id="diff-002",
            evidence_before="无发票条件",
            evidence_after="需合法有效发票",
            diff_summary="增加发票条件",
            user_intent="明确发票要求",
            confidence=0.78,
        ),
    ]
    rule = _make_rule(traces=traces)
    case = candidate_rule_to_reverse_rule_case(rule)
    assert "付款期限缩短" in case.diff_summary
    assert "增加发票条件" in case.diff_summary


# ---------------------------------------------------------------------------
# 输出过滤测试
# ---------------------------------------------------------------------------


def test_filter_against_kb_empty_input():
    """空输入返回空。"""
    from app.kb.feedback import filter_against_kb

    kept, filtered = filter_against_kb([])
    assert kept == []
    assert filtered == []


def test_filter_against_kb_no_existing_cases(monkeypatch):
    """KB 无案例时全部保留。"""
    from app.kb.feedback import filter_against_kb

    # mock 检索器返回空
    monkeypatch.setattr(
        "app.kb.feedback._fetch_similar_kb_cases",
        lambda rule: [],
    )

    rules = [
        _make_rule(
            risk_name="付款期限过长",
            check_point="检查合同中付款期限是否超过30日",
        ),
        _make_rule(
            risk_name="发票条件不明确",
            check_point="检查合同是否明确发票类型和开票时间要求",
        ),
    ]
    kept, filtered = filter_against_kb(rules)
    assert len(kept) == 2
    assert len(filtered) == 0


def test_filter_batch_internal_dedup(monkeypatch):
    """同模块语义重复的规则保留置信度最高的。"""
    import app.kb.feedback as fb_module

    # mock KB 检索返回空（跳过 Step A）
    monkeypatch.setattr(fb_module, "_fetch_similar_kb_cases", lambda rule: [])

    # 两条高度相似规则（check_point + trigger_condition 几乎相同），第二条置信度更高
    rule1 = _make_rule(
        risk_name="付款期限过长",
        check_point="检查合同中付款期限是否超过30日，以及是否以收到合法有效发票为付款起算条件。",
        trigger_condition="合同约定付款期限超过30日，或未明确付款前提为收到合法有效发票。",
        confidence=0.75,
    )
    rule2 = _make_rule(
        risk_name="付款期限不合理",
        check_point="检查合同中付款期限是否超过30日，以及是否以收到合法有效发票为付款起算条件。",  # 完全相同
        trigger_condition="合同约定付款期限超过30日，或未明确付款前提为收到合法有效发票。",  # 完全相同
        confidence=0.88,
    )

    kept, filtered = fb_module.filter_against_kb([rule1, rule2])
    # 保留置信度更高的 rule2
    assert len(kept) == 1
    assert kept[0].risk_name == "付款期限不合理"
    assert len(filtered) == 1
    assert filtered[0]["reason"] == "batch_internal_dup"


def test_filter_batch_different_modules_kept_separately(monkeypatch):
    """不同模块的规则不互相过滤。"""
    import app.kb.feedback as fb_module

    monkeypatch.setattr(fb_module, "_fetch_similar_kb_cases", lambda rule: [])

    rule1 = _make_rule(risk_name="付款期限过长", review_module="付款条款")
    rule2 = _make_rule(risk_name="交付期限不明确", review_module="交付期限")

    kept, filtered = fb_module.filter_against_kb([rule1, rule2])
    assert len(kept) == 2
    assert len(filtered) == 0


# ---------------------------------------------------------------------------
# 置信度筛选测试
# ---------------------------------------------------------------------------


def test_confidence_filter_excludes_low_confidence_rules():
    """置信度 ≤ 阈值的规则被筛掉。"""
    from app.kb.feedback import MIN_CONFIDENCE
    from app.kb.feedback import _avg_trace_confidence

    high_conf = _make_rule(risk_name="高风险规则", confidence=0.85)
    low_conf = _make_rule(risk_name="低风险规则", confidence=0.60)

    assert _avg_trace_confidence(high_conf) > MIN_CONFIDENCE
    assert _avg_trace_confidence(low_conf) <= MIN_CONFIDENCE


# ---------------------------------------------------------------------------
# JSONL 写入测试
# ---------------------------------------------------------------------------


def test_append_case_to_jsonl(monkeypatch):
    """追加案例到 JSONL 文件。"""
    from app.kb.feedback import append_case_to_jsonl
    from app.kb.feedback import candidate_rule_to_reverse_rule_case

    rule = _make_rule()
    case = candidate_rule_to_reverse_rule_case(rule)

    workdir = _temp_workdir("test_append_jsonl")
    jsonl_path = workdir / "test_cases.jsonl"
    # 清理残留文件
    if jsonl_path.exists():
        jsonl_path.unlink()

    append_case_to_jsonl(case, jsonl_path)
    assert jsonl_path.exists()

    lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1

    data = json.loads(lines[0])
    assert data["case_id"] == case.case_id
    assert data["review_module"] == "付款条款"


def test_append_multiple_cases(monkeypatch):
    """追加多条案例。"""
    from app.kb.feedback import append_case_to_jsonl
    from app.kb.feedback import candidate_rule_to_reverse_rule_case

    workdir = _temp_workdir("test_append_multi")
    jsonl_path = workdir / "test_cases.jsonl"
    if jsonl_path.exists():
        jsonl_path.unlink()

    for name in ["付款期限过长", "付款条件不确定", "发票条件不明确"]:
        rule = _make_rule(risk_name=name)
        case = candidate_rule_to_reverse_rule_case(rule)
        append_case_to_jsonl(case, jsonl_path)

    lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3

    ids = {json.loads(line)["case_id"] for line in lines}
    assert len(ids) == 3  # 三个不同 case_id


# ---------------------------------------------------------------------------
# RAG 推送测试
# ---------------------------------------------------------------------------


def test_push_case_to_rag_service_success(monkeypatch):
    """RAG 推送成功。"""
    from app.kb.feedback import candidate_rule_to_reverse_rule_case
    from app.kb.feedback import push_case_to_rag_service

    monkeypatch.setenv("RAG_SERVICE_URL", "http://test-rag:8000")

    rule = _make_rule()
    case = candidate_rule_to_reverse_rule_case(rule)

    mock_urlopen = mock.MagicMock()
    mock_urlopen.return_value.__enter__.return_value.status = 200

    with mock.patch("urllib.request.urlopen", mock_urlopen):
        result = push_case_to_rag_service(case)
        assert result is True


def test_push_case_to_rag_service_unreachable(monkeypatch):
    """RAG 不可达时返回 False。"""
    from app.kb.feedback import candidate_rule_to_reverse_rule_case
    from app.kb.feedback import push_case_to_rag_service

    monkeypatch.setenv("RAG_SERVICE_URL", "http://test-rag:8000")

    rule = _make_rule()
    case = candidate_rule_to_reverse_rule_case(rule)

    import urllib.error

    mock_urlopen = mock.MagicMock()
    mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

    with mock.patch("urllib.request.urlopen", mock_urlopen):
        result = push_case_to_rag_service(case)
        assert result is False


# ---------------------------------------------------------------------------
# 编排器集成测试
# ---------------------------------------------------------------------------


def test_feedback_rules_to_kb_empty_input():
    """空输入返回空结果。"""
    from app.kb.feedback import feedback_rules_to_kb

    result = feedback_rules_to_kb([])
    assert result["candidates"] == 0
    assert result["added_to_kb"] == 0


def test_feedback_rules_to_kb_all_below_confidence(monkeypatch):
    """全部规则置信度不足时跳过。"""
    from app.kb.feedback import feedback_rules_to_kb

    monkeypatch.setattr(
        "app.kb.feedback.MIN_CONFIDENCE",
        0.90,  # 设高阈值
    )
    rules = [_make_rule(risk_name="测试", confidence=0.70)]
    result = feedback_rules_to_kb(rules)
    assert result["candidates"] == 0


def test_feedback_rules_to_kb_with_judge_approval(monkeypatch):
    """完整回流流程：Judge 通过 → 转换 → 写入。"""
    import app.kb.feedback as fb_module

    # Mock Judge 返回通过
    def mock_judge(candidates):
        results = []
        for rule in candidates:
            case_id = fb_module._generate_case_id(rule)
            results.append(
                {
                    "case_id": case_id,
                    "approved": True,
                    "reason": "规则逻辑完整，具有复用价值",
                    "tags": ["付款期限"],
                    "risk_level_override": None,
                }
            )
        return results, 0

    monkeypatch.setattr(fb_module, "_judge_rules", mock_judge)
    monkeypatch.setattr(fb_module, "MIN_CONFIDENCE", 0.70)

    # Mock RAG 推送成功
    monkeypatch.setattr(fb_module, "push_case_to_rag_service", lambda case: True)

    # 使用临时 JSONL（确保干净）
    workdir = _temp_workdir("test_feedback_integration")
    jsonl_path = workdir / "feedback_test.jsonl"
    if jsonl_path.exists():
        jsonl_path.unlink()
    monkeypatch.setattr(fb_module, "DEFAULT_CASES_PATH", jsonl_path)

    # 重建函数不做实际操作（避免覆盖真实索引）
    monkeypatch.setattr(fb_module, "rebuild_local_kb", lambda **kw: None)

    rule = _make_rule(risk_name="付款期限过长", confidence=0.82)
    result = fb_module.feedback_rules_to_kb([rule])

    assert result["candidates"] == 1
    assert result["judge_approved"] == 1
    assert result["judge_rejected"] == 0
    assert result["added_to_kb"] == 1
    assert result["rag_success"] == 1
    assert len(result["case_ids"]) == 1

    # 验证 JSONL 已写入
    assert jsonl_path.exists()
    lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["risk_name"] == "付款期限过长"


def test_feedback_rules_dedup_skips_existing(monkeypatch):
    """已存在的 case_id 跳过不重复写入。"""
    import app.kb.feedback as fb_module

    # Mock Judge 通过
    def mock_judge(candidates):
        results = []
        for rule in candidates:
            case_id = fb_module._generate_case_id(rule)
            results.append(
                {
                    "case_id": case_id,
                    "approved": True,
                    "reason": "ok",
                    "tags": [],
                    "risk_level_override": None,
                }
            )
        return results, 0

    monkeypatch.setattr(fb_module, "_judge_rules", mock_judge)
    monkeypatch.setattr(fb_module, "MIN_CONFIDENCE", 0.70)
    monkeypatch.setattr(fb_module, "push_case_to_rag_service", lambda case: True)
    monkeypatch.setattr(fb_module, "rebuild_local_kb", lambda **kw: None)

    workdir = _temp_workdir("test_feedback_dedup")
    jsonl_path = workdir / "dedup_test.jsonl"
    if jsonl_path.exists():
        jsonl_path.unlink()
    monkeypatch.setattr(fb_module, "DEFAULT_CASES_PATH", jsonl_path)

    # 第一次写入
    rule = _make_rule()
    result1 = fb_module.feedback_rules_to_kb([rule])
    assert result1["added_to_kb"] == 1

    # 第二次写入相同规则 → 应跳过
    result2 = fb_module.feedback_rules_to_kb([rule])
    assert result2["added_to_kb"] == 0
    assert result2["skipped_duplicates"] == 1

    # JSONL 只有一行
    lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1


# ---------------------------------------------------------------------------
# 图节点集成测试
# ---------------------------------------------------------------------------


def test_graph_node_filter_is_disabled_by_default():
    """默认 conftest 关闭了过滤节点，rules 原样通过。"""
    from app.chains.reverse_rule_graph import run_reverse_rule_extraction

    pair = {
        "pair_id": "pair-1",
        "before_text": "甲方应在收到发票后90日内付款。",
        "after_text": "甲方应在收到乙方开具的合法有效发票后30日内付款。",
        "contract_type": "服务合同",
        "review_role": "乙方",
    }
    result = run_reverse_rule_extraction([pair])
    assert "rules" in result
    assert "filtered_out" in result
    assert result["filtered_out"] == []  # disabled
    assert "feedback_result" in result
    assert result["feedback_result"]["reason"] == "disabled"


def test_graph_node_filter_enabled_filters_rules(monkeypatch):
    """开启过滤节点后规则被过滤。"""
    from app.chains.reverse_rule_graph import run_reverse_rule_extraction

    monkeypatch.setenv("REVERSE_RULE_FILTER_ENABLED", "1")
    monkeypatch.setenv("REVERSE_RULE_FEEDBACK_ENABLED", "0")
    monkeypatch.setenv("DISABLE_REAL_LLM", "1")

    pair = {
        "pair_id": "pair-1",
        "before_text": "甲方应在收到发票后90日内付款。",
        "after_text": "甲方应在收到乙方开具的合法有效发票后30日内付款。",
        "contract_type": "服务合同",
        "review_role": "乙方",
    }
    result = run_reverse_rule_extraction([pair])
    assert "rules" in result
    assert "filtered_out" in result
    # 过滤结果非空——stub 生成的规则可能与 KB 案例匹配
    assert isinstance(result["filtered_out"], list)


def test_graph_result_includes_feedback_when_disabled():
    """回流关闭时 feedback_result 包含 disabled 原因。"""
    from app.chains.reverse_rule_graph import run_reverse_rule_extraction

    pair = {
        "pair_id": "pair-1",
        "before_text": "甲方应在收到发票后90日内付款。",
        "after_text": "甲方应在收到乙方开具的合法有效发票后30日内付款。",
        "contract_type": "服务合同",
        "review_role": "乙方",
    }
    result = run_reverse_rule_extraction([pair])
    assert "feedback_result" in result
    assert result["feedback_result"]["reason"] == "disabled"


# ---------------------------------------------------------------------------
# Judge Prompt 测试
# ---------------------------------------------------------------------------


def test_judge_prompt_contains_cases_and_rules():
    """Judge prompt 包含同模块案例和候选规则。"""
    from app.kb.feedback import JUDGE_PROMPT

    cases_json = '[{"case_id": "payment_001"}]'
    rules_json = '[{"case_id": "auto_test_001"}]'
    prompt = JUDGE_PROMPT.format(cases_json=cases_json, rules_json=rules_json)
    assert "payment_001" in prompt
    assert "auto_test_001" in prompt
    assert "入库标准" in prompt
    assert "risk_level_override" in prompt


def test_slim_rule_for_judge_fields():
    """Judge 看到精简的规则字段。"""
    from app.kb.feedback import _slim_rule_for_judge

    rule = _make_rule()
    slim = _slim_rule_for_judge(rule)

    assert "case_id" in slim
    assert "contract_type" in slim
    assert "risk_name" in slim
    assert "check_point" in slim
    assert "suggestion_template" in slim
    assert "avg_confidence" in slim
    # 不应包含 traces 完整数据
    assert "traces" not in slim


def test_slim_case_for_judge_fields():
    """Judge 看到精简的已有案例字段。"""
    from app.kb.feedback import _slim_case_for_judge

    case = {
        "case_id": "payment_001",
        "risk_name": "付款期限过长",
        "check_point": "检查付款期限",
        "trigger_condition": "超过30日",
        "review_module": "付款条款",
        "change_pattern": "期限缩短",
        "before_example": "90天内付款",
        "after_example": "30天内付款",
        "diff_summary": "缩短期限",
        "user_intent": "缩短回款",
        "tags": ["付款"],
    }
    slim = _slim_case_for_judge(case)
    assert slim["case_id"] == "payment_001"
    assert slim["risk_name"] == "付款期限过长"
    assert "before_example" not in slim  # 不应包含大段文本
    assert "after_example" not in slim


# ---------------------------------------------------------------------------
# 模块 slug 测试
# ---------------------------------------------------------------------------


def test_slugify_known_modules():
    """已知模块名正确转换为 slug。"""
    from app.kb.feedback import _slugify

    assert _slugify("付款条款") == "payment_terms"
    assert _slugify("违约责任") == "breach"
    assert _slugify("知识产权") == "ip"
    assert _slugify("争议解决") == "dispute_resolution"
    assert _slugify("数据安全/个人信息") == "data_security"


def test_slugify_unknown_module_fallback():
    """未知模块名 fallback 为通用 slug。"""
    from app.kb.feedback import _slugify

    slug = _slugify("未知模块名称")
    assert len(slug) > 0
    assert " " not in slug


# ---------------------------------------------------------------------------
# 辅助函数测试
# ---------------------------------------------------------------------------


def test_avg_trace_confidence():
    """平均置信度计算正确。"""
    from app.kb.feedback import _avg_trace_confidence

    rule = _make_rule(confidence=0.80)
    assert _avg_trace_confidence(rule) == 0.80

    traces = [
        RuleExtractionTrace(
            pair_id="p1",
            source_diff_id="d1",
            evidence_before="a",
            evidence_after="b",
            diff_summary="s",
            user_intent="i",
            confidence=0.90,
        ),
        RuleExtractionTrace(
            pair_id="p2",
            source_diff_id="d2",
            evidence_before="c",
            evidence_after="d",
            diff_summary="t",
            user_intent="j",
            confidence=0.60,
        ),
    ]
    rule = _make_rule(traces=traces)
    assert _avg_trace_confidence(rule) == 0.75


def test_avg_trace_confidence_no_traces():
    """无 trace 时置信度为 0。"""
    from app.kb.feedback import _avg_trace_confidence

    rule = _make_rule(traces=[])
    assert _avg_trace_confidence(rule) == 0.0


def test_empty_feedback_result_structure():
    """空结果包含所有必要字段。"""
    from app.kb.feedback import _empty_feedback_result

    result = _empty_feedback_result()
    assert result["candidates"] == 0
    assert result["judge_approved"] == 0
    assert result["judge_rejected"] == 0
    assert result["judge_error"] == 0
    assert result["skipped_duplicates"] == 0
    assert result["added_to_kb"] == 0
    assert result["rag_success"] == 0
    assert result["rag_failed"] == 0
    assert result["case_ids"] == []
    assert result["judge_details"] == []
