def test_normalizes_granular_roles_to_rule_library_perspectives():
    from app.services.review_perspective import normalize_review_perspective

    assert normalize_review_perspective("起诉方") == "甲方"
    assert normalize_review_perspective("采购方") == "甲方"
    assert normalize_review_perspective("收款方") == "乙方"
    assert normalize_review_perspective("服务方") == "乙方"
    assert normalize_review_perspective("被审计方") == "乙方"
    assert normalize_review_perspective("双方") == "通用"
    assert normalize_review_perspective("合同相对方") == "通用"
    assert normalize_review_perspective("") == "通用"
    assert normalize_review_perspective(None) == "通用"
    assert normalize_review_perspective("通用角色") == "通用"
