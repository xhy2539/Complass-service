import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.models.reverse_rule import ContractPair
from app.models.reverse_rule import DiffClause
from app.models.reverse_rule import DiffResult

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
    "数量",
    "新增",
    "试点",
    "所有权",
    "风险",
    "灭失",
    "毁损",
)

LEADING_NUMBERING_PATTERN = re.compile(
    r"^\s*(?:第?[一二三四五六七八九十百]+[章节条款项、.)）]|[（(]?[0-9]+[).、）])\s*"
)
MAJOR_CLAUSE_PATTERN = re.compile(r"^\s*第([一二三四五六七八九十百]+)条\s*(.*)$")
SUB_CLAUSE_PATTERN = re.compile(
    r"^\s*([一二三四五六七八九十百]+[.．、]\d+|[0-9]+(?:\.[0-9]+)?)\s*(.*)$"
)


@dataclass(frozen=True)
class ClauseSegment:
    clause_id: str
    title: str
    text: str


def diff_contract_pair(pair: ContractPair) -> DiffResult:
    before = pair.before_text.strip()
    after = pair.after_text.strip()
    if before == after:
        return DiffResult(pair_id=pair.pair_id, changed_clauses=[])

    before_segments = split_contract_clauses(before)
    after_segments = split_contract_clauses(after)
    if len(before_segments) > 1 or len(after_segments) > 1:
        return DiffResult(
            pair_id=pair.pair_id,
            changed_clauses=_diff_clause_segments(before_segments, after_segments),
        )

    review_module = _infer_review_module(before, after)
    is_substantive = _is_substantive_change(before, after)
    reason = (
        "涉及权利义务、期限、金额、责任或条件变化"
        if is_substantive
        else "仅疑似措辞或格式润色"
    )
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


def split_contract_clauses(text: str) -> list[ClauseSegment]:
    segments: list[ClauseSegment] = []
    current_id: str | None = None
    current_title = ""
    current_lines: list[str] = []
    current_major = ""

    def flush() -> None:
        nonlocal current_id, current_title, current_lines
        if current_id and current_lines:
            body = "\n".join(current_lines).strip()
            segments.append(
                ClauseSegment(current_id, current_title or current_id, body)
            )
        current_id = None
        current_title = ""
        current_lines = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        major_match = MAJOR_CLAUSE_PATTERN.match(line)
        if major_match:
            flush()
            current_major = f"第{major_match.group(1)}条"
            continue

        sub_match = SUB_CLAUSE_PATTERN.match(line)
        if sub_match:
            flush()
            current_id = sub_match.group(1).replace("．", ".").replace("、", ".")
            current_title = f"{current_major} {current_id}".strip()
            current_lines = [line]
            continue

        if current_id:
            current_lines.append(line)

    flush()
    if segments:
        return segments
    stripped = text.strip()
    return [ClauseSegment("full-text", "全文", stripped)] if stripped else []


def _diff_clause_segments(
    before_segments: list[ClauseSegment],
    after_segments: list[ClauseSegment],
) -> list[DiffClause]:
    changed: list[DiffClause] = []
    pairs = _align_clause_segments(before_segments, after_segments)
    for before_segment, after_segment in pairs:
        before_text = before_segment.text if before_segment else ""
        after_text = after_segment.text if after_segment else ""
        if before_text == after_text:
            continue

        review_module = _infer_review_module(before_text, after_text)
        is_substantive = _is_substantive_change(before_text, after_text)
        if not is_substantive:
            continue
        reason = "涉及权利义务、期限、金额、责任或条件变化"
        changed.append(
            DiffClause(
                review_module=review_module,
                change_type=_change_type(before_segment, after_segment),
                before=before_text,
                after=after_text,
                diff_summary=_summarize_diff(
                    review_module, before_text, after_text, is_substantive
                ),
                is_substantive=True,
                substantive_reason=reason,
            )
        )
    return changed


def _align_clause_segments(
    before_segments: list[ClauseSegment],
    after_segments: list[ClauseSegment],
) -> list[tuple[ClauseSegment | None, ClauseSegment | None]]:
    after_by_id = {segment.clause_id: segment for segment in after_segments}
    used_after_ids: set[str] = set()
    pairs: list[tuple[ClauseSegment | None, ClauseSegment | None]] = []

    for before_segment in before_segments:
        after_segment = after_by_id.get(before_segment.clause_id)
        if after_segment is not None:
            used_after_ids.add(after_segment.clause_id)
            pairs.append((before_segment, after_segment))
            continue
        best = _best_unmatched_segment(before_segment, after_segments, used_after_ids)
        if best is not None:
            used_after_ids.add(best.clause_id)
            pairs.append((before_segment, best))
        else:
            pairs.append((before_segment, None))

    for after_segment in after_segments:
        if after_segment.clause_id not in used_after_ids:
            pairs.append((None, after_segment))
    return pairs


def _best_unmatched_segment(
    before_segment: ClauseSegment,
    after_segments: list[ClauseSegment],
    used_after_ids: set[str],
) -> ClauseSegment | None:
    candidates = [
        segment for segment in after_segments if segment.clause_id not in used_after_ids
    ]
    if not candidates:
        return None
    best = max(
        candidates,
        key=lambda segment: SequenceMatcher(
            None, before_segment.text, segment.text
        ).ratio(),
    )
    score = SequenceMatcher(None, before_segment.text, best.text).ratio()
    return best if score >= 0.55 else None


def _change_type(
    before_segment: ClauseSegment | None,
    after_segment: ClauseSegment | None,
) -> str:
    if before_segment is None:
        return "新增"
    if after_segment is None:
        return "删除"
    return "修改"


def _infer_review_module(before: str, after: str) -> str:
    text = before + after
    if any(
        word in text
        for word in (
            "所有权",
            "风险转移",
            "灭失",
            "毁损",
            "到货签收",
            "验收合格并完成交接",
        )
    ):
        return "所有权/风险转移"
    if any(word in text for word in ("合同标的", "设备数量", "新增", "试点")):
        return "合同标的"
    if any(word in text for word in ("管辖", "法院", "仲裁")):
        return "管辖法院"
    if "争议" in text:
        return "争议解决"
    if "保密" in text:
        return "保密条款"
    if "解除" in text or "终止" in text:
        return "解除条款"
    if any(
        word in text
        for word in (
            "责任上限",
            "赔偿总额",
            "赔偿上限",
            "已收取费用总额",
            "合同总价为上限",
        )
    ):
        return "赔偿责任上限"
    if any(word in text for word in ("违约", "赔偿", "损失", "律师费")):
        if "上限" in text and "赔偿" in text:
            return "赔偿责任上限"
        return "违约责任"
    if any(
        word in text for word in ("付款", "支付", "款项", "付款申请", "支付相应款项")
    ):
        return "付款条款"
    if "发票" in text and not any(
        word in text for word in ("90日", "30日", "付款期限", "支付期限")
    ):
        return "发票开具"
    if any(word in text for word in ("付款", "支付", "费用", "发票", "服务费", "款项")):
        return "付款条款"
    return "通用条款"


def _is_substantive_change(before: str, after: str) -> bool:
    if not any(keyword in before + after for keyword in SUBSTANTIVE_KEYWORDS):
        return False
    if any(
        keyword in before + after
        for keyword in ("管辖", "法院", "仲裁", "责任上限", "赔偿总额")
    ):
        return _normalize_polish(before) != _normalize_polish(after)
    ratio = SequenceMatcher(
        None, _normalize_polish(before), _normalize_polish(after)
    ).ratio()
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


def _summarize_diff(
    review_module: str, before: str, after: str, is_substantive: bool
) -> str:
    if is_substantive:
        return f"{review_module}发生实质性修改：由“{before}”调整为“{after}”。"
    return f"{review_module}疑似仅发生措辞润色：由“{before}”调整为“{after}”。"
