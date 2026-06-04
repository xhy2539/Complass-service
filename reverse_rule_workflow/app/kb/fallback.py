from app.models.reverse_rule import DiffResult
from app.models.reverse_rule import RetrievedCase


def fallback_reverse_rule_cases(
    diff_result: DiffResult, k: int = 3
) -> list[RetrievedCase]:
    cases: list[RetrievedCase] = []
    for clause in diff_result.changed_clauses:
        if not clause.is_substantive:
            continue
        if clause.review_module == "付款条款":
            cases.append(
                RetrievedCase(
                    case_id="fallback-payment-001",
                    contract_type="服务合同",
                    review_role=["甲方", "乙方"],
                    review_module="付款条款",
                    change_pattern="付款期限或付款条件发生变化",
                    before_example=clause.before,
                    after_example=clause.after,
                    diff_summary=clause.diff_summary,
                    user_intent="缩短付款期限或增加付款前置条件",
                    risk_name="付款条件不明确或期限不合理",
                    check_point="检查付款期限、付款前置条件及发票要求是否清晰、合理且可执行。",
                    trigger_condition="合同约定付款期限、付款条件、发票条件发生变化时触发。",
                    default_risk_level="中",
                    suggestion_template="建议明确付款起算节点、付款期限和发票要求，避免付款义务长期悬而未决。",
                    example_clause=clause.before,
                )
            )
        elif clause.review_module == "违约责任":
            cases.append(
                RetrievedCase(
                    case_id="fallback-breach-001",
                    contract_type="服务合同",
                    review_role=["甲方", "乙方"],
                    review_module="违约责任",
                    change_pattern="违约赔偿范围或费用承担发生变化",
                    before_example=clause.before,
                    after_example=clause.after,
                    diff_summary=clause.diff_summary,
                    user_intent="扩大违约方赔偿范围",
                    risk_name="违约责任范围过宽",
                    check_point="检查违约赔偿范围、间接损失和维权费用承担是否明确且合理。",
                    trigger_condition="合同新增或扩大违约赔偿、全部损失、律师费等责任时触发。",
                    default_risk_level="中",
                    suggestion_template="建议限定赔偿范围、排除不合理间接损失，并明确维权费用承担条件。",
                    example_clause=clause.before,
                )
            )
    return cases[:k]
