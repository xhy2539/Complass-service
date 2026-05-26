"""规则 CSV 导入解析服务。"""

import csv
import io

CSV_FIELD_MAP = {
    "规则编号": "rule_code",
    "合同类型": "contract_type",
    "审核模块": "review_module",
    "风险名称": "risk_name",
    "检查点": "check_point",
    "触发条件": "trigger_condition",
    "默认风险等级": "default_risk_level",
    "修改建议模板": "suggestion_template",
    "示例问题条款": "example_clause",
}

REQUIRED_FIELDS = ["规则编号", "合同类型", "审核模块", "风险名称", "默认风险等级"]
VALID_RISK_LEVELS = {"高", "中", "低"}


def parse_rules_csv(content: bytes) -> tuple[list[dict], list[dict]]:
    """解析规则 CSV，返回合法规则和错误列表。"""
    text = _decode_csv_content(content)
    reader = csv.DictReader(io.StringIO(text))
    errors: list[dict] = []
    rules: list[dict] = []
    seen_codes: set[str] = set()

    header_errors = _validate_headers(reader.fieldnames or [])
    if header_errors:
        return [], header_errors

    for row_index, row in enumerate(reader, start=2):
        normalized = {field: (row.get(field) or "").strip() for field in CSV_FIELD_MAP}
        row_errors = _validate_row(row_index, normalized, seen_codes)

        rule_code = normalized.get("规则编号")
        if rule_code:
            seen_codes.add(rule_code)

        if row_errors:
            errors.extend(row_errors)
            continue

        rules.append({
            target: normalized[source]
            for source, target in CSV_FIELD_MAP.items()
        })

    return rules, errors


def _decode_csv_content(content: bytes) -> str:
    """按常见中文编码解码 CSV。"""
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("gbk")


def _validate_headers(fieldnames: list[str]) -> list[dict]:
    """校验 CSV 表头是否完整。"""
    headers = {name.strip() for name in fieldnames}
    return [
        {"row": 1, "field": field, "message": "缺少必填表头"}
        for field in CSV_FIELD_MAP
        if field not in headers
    ]


def _validate_row(row_index: int, row: dict[str, str], seen_codes: set[str]) -> list[dict]:
    """校验单行规则数据。"""
    errors: list[dict] = []
    for field in REQUIRED_FIELDS:
        if not row.get(field):
            errors.append({"row": row_index, "field": field, "message": "必填字段不能为空"})

    rule_code = row.get("规则编号")
    if rule_code and rule_code in seen_codes:
        errors.append({"row": row_index, "field": "规则编号", "message": "CSV 内规则编号重复"})

    risk_level = row.get("默认风险等级")
    if risk_level and risk_level not in VALID_RISK_LEVELS:
        errors.append({"row": row_index, "field": "默认风险等级", "message": "默认风险等级必须是 高/中/低"})

    return errors
