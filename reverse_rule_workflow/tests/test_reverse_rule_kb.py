from pathlib import Path
import tempfile

import pytest
from pydantic import ValidationError


REQUIRED_REVIEW_MODULES = {
    "付款条款",
    "验收条款",
    "违约责任",
    "赔偿责任上限",
    "解除条款",
    "通知条款",
    "保密条款",
    "知识产权",
    "争议解决",
    "管辖法院",
    "不可抗力",
    "转包/分包",
    "交付期限",
    "质量保证",
    "单方免责",
    "数据安全/个人信息",
    "竞业限制或不招揽",
    "发票开具",
    "审计权",
    "合同生效条件",
}


def _test_storage_dir(name: str) -> Path:
    return Path(tempfile.gettempdir()) / "reverse_rule_workflow_tests" / name


def test_schema_rejects_backend_generated_fields():
    from app.kb.schema import ReverseRuleCase

    payload = {
        "case_id": "payment_001",
        "contract_type": ["服务合同"],
        "review_role": ["乙方"],
        "review_module": "付款条款",
        "change_pattern": "付款期限由90日缩短为30日",
        "before_example": "甲方应在收到发票后90日内付款。",
        "after_example": "甲方应在收到乙方发票后30日内付款。",
        "diff_summary": "用户缩短付款期限。",
        "user_intent": "降低回款风险。",
        "risk_name": "付款期限过长",
        "check_point": "检查付款期限是否过长。",
        "trigger_condition": "付款期限超过30日。",
        "default_risk_level": "中",
        "suggestion_template": "建议约定30日内付款。",
        "example_clause": "甲方应在收到发票后90日内付款。",
        "tags": ["付款期限"],
        "id": "backend-generated",
        "rule_code": "backend-generated",
        "enabled": 1,
    }

    with pytest.raises(ValidationError):
        ReverseRuleCase.model_validate(payload)


def test_loads_at_least_20_cases_and_covers_required_modules():
    from app.kb.loader import load_reverse_rule_cases

    cases = load_reverse_rule_cases()
    modules = {case.review_module for case in cases}

    assert len(cases) >= 20
    assert REQUIRED_REVIEW_MODULES <= modules


def test_document_contains_required_content_and_metadata():
    from app.kb.loader import case_to_document, load_reverse_rule_cases

    case = load_reverse_rule_cases()[0]
    document = case_to_document(case)

    for field in [
        "review_module",
        "change_pattern",
        "diff_summary",
        "user_intent",
        "risk_name",
        "check_point",
        "trigger_condition",
        "suggestion_template",
        "example_clause",
    ]:
        assert getattr(case, field) in document.page_content

    assert document.metadata == {
        "case_id": case.case_id,
        "contract_type": case.contract_type,
        "review_role": case.review_role,
        "review_module": case.review_module,
        "default_risk_level": case.default_risk_level,
        "tags": case.tags,
    }


def test_build_index_creates_persisted_kb():
    from app.kb.loader import load_reverse_rule_cases
    from app.kb.retriever import build_reverse_rule_kb

    persist_dir = _test_storage_dir("test_reverse_rule_kb_build")
    result = build_reverse_rule_kb(load_reverse_rule_cases(), persist_dir)
    index_path = persist_dir / "index.json"

    assert result == index_path
    assert index_path.exists()
    import json

    records = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(records["records"]) >= 20
    assert "embedding_dim" in records


def test_retrieves_payment_case_for_payment_query(monkeypatch):
    from app.kb.loader import load_reverse_rule_cases
    from app.kb import retriever

    persist_dir = _test_storage_dir("test_reverse_rule_kb_payment")
    retriever.build_reverse_rule_kb(load_reverse_rule_cases(), persist_dir)
    monkeypatch.setattr(retriever, "DEFAULT_PERSIST_DIR", str(persist_dir))

    results = retriever.retrieve_reverse_rule_cases(
        "用户把付款期限从90日改成30日，并要求收到合法有效发票后付款",
        review_module="付款条款",
        k=3,
    )

    assert results
    assert results[0]["review_module"] == "付款条款"
    assert "付款" in results[0]["risk_name"]
    assert "score" in results[0]


def test_retrieves_data_security_case_for_personal_info_query(monkeypatch):
    from app.kb.loader import load_reverse_rule_cases
    from app.kb import retriever

    persist_dir = _test_storage_dir("test_reverse_rule_kb_data")
    retriever.build_reverse_rule_kb(load_reverse_rule_cases(), persist_dir)
    monkeypatch.setattr(retriever, "DEFAULT_PERSIST_DIR", str(persist_dir))

    results = retriever.retrieve_reverse_rule_cases(
        "新增个人信息保护、数据安全措施、删除或返还数据的要求",
        k=3,
    )

    assert results
    assert results[0]["review_module"] == "数据安全/个人信息"


def test_retrieves_ip_case_for_ownership_query(monkeypatch):
    from app.kb.loader import load_reverse_rule_cases
    from app.kb import retriever

    persist_dir = _test_storage_dir("test_reverse_rule_kb_ip")
    retriever.build_reverse_rule_kb(load_reverse_rule_cases(), persist_dir)
    monkeypatch.setattr(retriever, "DEFAULT_PERSIST_DIR", str(persist_dir))

    results = retriever.retrieve_reverse_rule_cases(
        "修改后明确交付成果知识产权归属乙方，甲方仅有使用权",
        k=3,
    )

    assert results
    assert results[0]["review_module"] == "知识产权"


def test_filters_by_review_module_contract_type_and_review_role(monkeypatch):
    from app.kb.loader import load_reverse_rule_cases
    from app.kb import retriever

    persist_dir = _test_storage_dir("test_reverse_rule_kb_filters")
    retriever.build_reverse_rule_kb(load_reverse_rule_cases(), persist_dir)
    monkeypatch.setattr(retriever, "DEFAULT_PERSIST_DIR", str(persist_dir))

    results = retriever.retrieve_reverse_rule_cases(
        "审计权范围从无限制现场审计改为提前通知并限于合同相关资料",
        review_module="审计权",
        contract_type="服务合同",
        review_role="被审计方",
        k=5,
    )

    assert results
    assert all(result["review_module"] == "审计权" for result in results)
    assert all("服务合同" in result["contract_type"] for result in results)
    assert all("被审计方" in result["review_role"] for result in results)
def test_generic_review_role_does_not_block_jurisdiction_case(monkeypatch):
    from app.kb.loader import load_reverse_rule_cases
    from app.kb import retriever

    persist_dir = _test_storage_dir("test_reverse_rule_kb_generic_role")
    retriever.build_reverse_rule_kb(load_reverse_rule_cases(), persist_dir)
    monkeypatch.setattr(retriever, "DEFAULT_PERSIST_DIR", str(persist_dir))

    results = retriever.retrieve_reverse_rule_cases(
        "争议管辖由乙方所在地法院调整为甲方所在地有管辖权的人民法院",
        review_module="管辖法院",
        contract_type="采购合同",
        review_role="通用",
        k=5,
    )

    assert results
    assert results[0]["case_id"] == "jurisdiction_001"


def test_granular_review_role_matches_normalized_perspective(monkeypatch):
    from app.kb.loader import load_reverse_rule_cases
    from app.kb import retriever

    persist_dir = _test_storage_dir("test_reverse_rule_kb_normalized_role")
    retriever.build_reverse_rule_kb(load_reverse_rule_cases(), persist_dir)
    monkeypatch.setattr(retriever, "DEFAULT_PERSIST_DIR", str(persist_dir))

    results = retriever.retrieve_reverse_rule_cases(
        "审计权范围从无限制现场审计改为提前通知并限于合同相关资料",
        review_module="审计权",
        contract_type="服务合同",
        review_role="服务方",
        k=5,
    )

    assert results
    assert results[0]["case_id"] == "audit_001"
