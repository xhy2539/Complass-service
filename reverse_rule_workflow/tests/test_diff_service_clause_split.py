from app.chains.reverse_rule_graph import run_reverse_rule_extraction
from app.models.reverse_rule import ContractPair
from app.services.diff_service import diff_contract_pair


def purchase_contract_pair() -> dict:
    return {
        "pair_id": "purchase-01",
        "contract_type": "采购合同",
        "review_role": "通用",
        "before_text": """
智能设备采购合同
设备采购及安装调试项目
第一条 合同标的
一.1 乙方向甲方供应智能巡检终端、边缘计算网关及配套安装服务。
一.2 本合同项下设备数量为智能巡检终端60台、边缘计算网关12台、安装调试服务1项。
一.3 乙方不得以停产、供应商调整或内部审批为由单方替换核心部件。
第二条 价款与支付
二.1 合同价款为固定总价。
二.2 甲方收到合法有效的增值税专用发票及对应付款申请后15个工作日内支付相应款项。
二.3 乙方未按期交付或验收不合格的，甲方有权顺延付款且不构成逾期付款。
第三条 交付、验收与风险转移
三.1 乙方应将设备交付至甲方指定项目现场。
三.2 甲方应在设备安装调试完成后10个工作日内组织初验。
三.3 设备所有权自甲方支付至合同总价90%时转移；灭失、毁损风险自最终验收合格并完成交接时转移。
第四条 违约责任
四.1 乙方每逾期一日，应按逾期交付部分价款的0.3%向甲方支付违约金，累计不超过合同总价的15%。
四.2 乙方提供的设备存在质量缺陷且影响甲方正常使用的，甲方有权要求修理、更换、退货并主张因此产生的直接损失。
第五条 争议解决
五.1 因本合同引起或与本合同有关的争议，双方应先友好协商；协商不成的，提交上海仲裁委员会仲裁。
五.2 本合同适用中华人民共和国法律。
""",
        "after_text": """
智能设备采购合同
设备采购及安装调试项目
第一条 合同标的
一.1 乙方向甲方供应智能巡检终端、边缘计算网关及配套安装服务。
一.2 本合同项下设备数量为智能巡检终端72台、边缘计算网关12台、安装调试服务1项，其中新增12台终端用于二期试点。
一.3 乙方不得以停产、供应商调整或内部审批为由单方替换核心部件。
第二条 价款与支付
二.1 合同价款为固定总价。
二.2 甲方收到合法有效的增值税专用发票及对应付款申请后30个自然日内支付相应款项。
二.3 乙方未按期交付或验收不合格的，甲方有权顺延付款且不构成逾期付款。
第三条 交付、验收与风险转移
三.1 乙方应将设备交付至甲方指定项目现场。
三.2 甲方应在设备安装调试完成后10个工作日内组织初验。
三.3 设备所有权及灭失、毁损风险自到货签收时转移至甲方。
第四条 违约责任
四.1 乙方每逾期一日，应按逾期交付部分价款的0.1%向甲方支付违约金，累计不超过合同总价的5%。
四.2 乙方提供的设备存在质量缺陷且影响甲方正常使用的，甲方有权要求修理、更换、退货并主张因此产生的直接损失。
第五条 争议解决
五.1 因本合同引起或与本合同有关的争议，任何一方均可向乙方所在地人民法院提起诉讼。
五.2 本合同适用中华人民共和国法律。
""",
    }


def test_diff_contract_pair_splits_purchase_contract_into_multiple_substantive_changes():
    diff = diff_contract_pair(ContractPair.model_validate(purchase_contract_pair()))

    modules = [clause.review_module for clause in diff.changed_clauses if clause.is_substantive]

    assert len(diff.changed_clauses) == 5
    assert modules == ["合同标的", "付款条款", "所有权/风险转移", "违约责任", "管辖法院"]
    assert all(len(clause.before) < 220 for clause in diff.changed_clauses)
    assert all(len(clause.after) < 220 for clause in diff.changed_clauses)


def test_reverse_rule_extraction_generates_five_rules_for_purchase_contract():
    result = run_reverse_rule_extraction([purchase_contract_pair()])

    modules = {rule["review_module"] for rule in result["rules"]}

    assert len(result["rules"]) == 5
    assert {"合同标的", "付款条款", "所有权/风险转移", "违约责任", "管辖法院"} <= modules
    scope_rule = next(rule for rule in result["rules"] if rule["review_module"] == "合同标的")
    assert scope_rule["traces"][0]["confidence"] < 0.6
