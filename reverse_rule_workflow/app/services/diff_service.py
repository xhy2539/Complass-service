import re
from difflib import SequenceMatcher

from app.models.reverse_rule import ContractPair, DiffClause, DiffResult


SUBSTANTIVE_KEYWORDS = (
    "日",
    "天",
    "金额",
    "费用",
    "付款",
    "支付",
    "发票",
    "赔偿",
    "损失",
    "违约",
    "解除",
    "保密",
    "期限",
    "比例",
    "律师费",
    "上限",
    "法院",
    "仲裁",
    "管辖",
    "争议",
)

LEADING_NUMBERING_PATTERN = re.compile(
    r"^\s*(?:第?[一二三四五六七八九十百]+[章节条款项、.)）]|[（(]?[0-9]+[).、）])\s*"
)


def diff_contract_pair(pair: ContractPair) -> DiffResult:
    before = pair.before_text.strip()
    after = pair.after_text.strip()
    if before == after:
        return DiffResult(pair_id=pair.pair_id, changed_clauses=[])

    review_module = _infer_review_module(before, after)
    is_substantive = _is_substantive_change(before, after)
    reason = "涉及权利义务、期限、金额、责任或条件变化" if is_substantive else "仅疑似措辞或格式润色"
    diff_summary = _summarize_diff(review_module, before, after, is_substantive)

    return DiffResult(
        pair_id=pair.pair_id,
        changed_clauses=[
            DiffClause(
                review_module=review_module,
                change_type="修改",
                before=before,
                after=after,
                diff_summary=diff_summary,
                is_substantive=is_substantive,
                substantive_reason=reason,
            )
        ],
    )


def _infer_review_module(before: str, after: str) -> str:
    text = before + after
    if any(word in text for word in ("管辖", "法院", "仲裁")):
        return "管辖法院"
    if "争议" in text:
        return "争议解决"
    if "保密" in text:
        return "保密条款"
    if "解除" in text or "终止" in text:
        return "解除条款"
    if any(word in text for word in ("责任上限", "赔偿总额", "赔偿上限", "已收取费用总额", "合同总价为上限")):
        return "赔偿责任上限"
    if any(word in text for word in ("违约", "赔偿", "损失", "律师费")):
        if "上限" in text and "赔偿" in text:
            return "赔偿责任上限"
        return "违约责任"
    if "发票" in text and not any(word in text for word in ("90日", "30日", "付款期限", "支付期限")):
        return "发票开具"
    if any(word in text for word in ("付款", "支付", "费用", "发票", "服务费", "款项")):
        return "付款条款"
    return "通用条款"


def _is_substantive_change(before: str, after: str) -> bool:
    if not any(keyword in before + after for keyword in SUBSTANTIVE_KEYWORDS):
        return False
    if any(keyword in before + after for keyword in ("管辖", "法院", "仲裁", "责任上限", "赔偿总额")):
        return _normalize_polish(before) != _normalize_polish(after)
    ratio = SequenceMatcher(None, _normalize_polish(before), _normalize_polish(after)).ratio()
    if ratio > 0.82 and not _has_number_change(before, after):
        return False
    return True


def _has_number_change(before: str, after: str) -> bool:
    return re.findall(r"\d+", _strip_leading_numbering(before)) != re.findall(
        r"\d+",
        _strip_leading_numbering(after),
    )


def _normalize_polish(text: str) -> str:
    replacements = {
        "应当": "应",
        "按照": "按",
        "服务费用": "服务费",
        "。": "",
        "，": "",
        ",": "",
        ".": "",
        " ": "",
        "\n": "",
        "\t": "",
        "、": "",
        "；": "",
        ";": "",
        "（": "",
        "）": "",
        "(": "",
        ")": "",
    }
    normalized = _strip_leading_numbering(text)
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    return normalized


def _strip_leading_numbering(text: str) -> str:
    current = text.strip()
    while True:
        updated = LEADING_NUMBERING_PATTERN.sub("", current, count=1)
        if updated == current:
            return current
        current = updated.strip()


def _summarize_diff(review_module: str, before: str, after: str, is_substantive: bool) -> str:
    if is_substantive:
        return f"{review_module}发生实质性修改：由“{before}”调整为“{after}”。"
    return f"{review_module}疑似仅发生措辞润色：由“{before}”调整为“{after}”。"
