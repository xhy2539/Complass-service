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

    text = before + after
    if any(word in text for word in ("SLA", "响应", "恢复", "故障", "扣减", "未达标")):
        return "SLA响应时间恢复时间未达标扣减" + (
            f" {number_direction}" if number_direction else ""
        )
    if any(
        word in text
        for word in ("知识产权", "源代码", "交付成果", "技术文档", "接口文档")
    ):
        return "源代码交付成果知识产权归属"
    if any(word in text for word in ("验收标准", "组织验收", "验收不合格", "整改")):
        return "验收标准验收期限不合格整改" + (
            f" {number_direction}" if number_direction else ""
        )
    if any(word in text for word in ("押金", "退还", "交接")):
        return "押金退还交接期限" + (f" {number_direction}" if number_direction else "")
    if number_direction:
        return number_direction

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
