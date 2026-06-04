from app.models.reverse_rule import DiffResult


def build_retrieval_queries(
    diff_result: DiffResult,
    contract_type: str | None,
    review_role: str | None,
) -> list[str]:
    grouped: dict[str, list[str]] = {}
    for clause in diff_result.changed_clauses:
        if not clause.is_substantive:
            continue
        grouped.setdefault(clause.review_module, []).append(
            _change_direction(clause.before, clause.after)
        )

    queries: list[str] = []
    for review_module, directions in grouped.items():
        parts = [
            contract_type or "通用合同",
            review_role or "通用角色",
            review_module,
            "；".join(dict.fromkeys(directions)),
            "逆向生成审核规则",
        ]
        queries.append(" ".join(part for part in parts if part))
    return queries


def _change_direction(before: str, after: str) -> str:
    number_direction = _number_direction(before, after)
    if number_direction:
        return number_direction

    text = before + after
    if "随时解除" in before and "通知" in after:
        return "随时解除改提前通知"
    if "全部损失" in before and "上限" in after:
        return "全部损失改赔偿责任上限"
    if "普通发票" in before and "合法有效" in after:
        return "普通发票改合法有效发票"
    if "保密" in text and "期限" in text:
        return "保密期限调整"
    if any(word in text for word in ("管辖", "法院", "仲裁")):
        return "争议解决或管辖安排调整"
    return "实质性修改"


def _number_direction(before: str, after: str) -> str | None:
    import re

    pattern = re.compile(r"(\d+)\s*(日|天|年|个月|月|%|％)?")
    before_numbers = pattern.findall(before)
    after_numbers = pattern.findall(after)
    if not before_numbers or not after_numbers or before_numbers == after_numbers:
        return None

    before_text = "".join(before_numbers[0])
    after_text = "".join(after_numbers[0])
    if before_text and after_text:
        return f"{before_text}改{after_text}"
    return None
