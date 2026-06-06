import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.models.reverse_rule import ContractPair
from app.models.reverse_rule import DiffClause
from app.models.reverse_rule import DiffResult

SUBSTANTIVE_KEYWORDS = (
    "日",
    "天",
    "分钟",
    "小时",
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
    "验收",
    "整改",
    "标准",
    "源代码",
    "知识产权",
    "交付成果",
    "技术文档",
    "接口文档",
    "SLA",
    "响应",
    "恢复",
    "故障",
    "扣减",
    "扣款",
    "未达标",
    "押金",
    "退还",
    "数据",
    "个人信息",
    "删除",
    "返还",
    "书面证明",
)

LEADING_NUMBERING_PATTERN = re.compile(
    r"^\s*(?:第?[一二三四五六七八九十百]+[章节条款项、.)）]|[（(]?[0-9]+[).、）])\s*"
)
MAJOR_CLAUSE_PATTERN = re.compile(r"^\s*第([一二三四五六七八九十百0-9]+)条\s*(.*)$")
SUB_CLAUSE_PATTERN = re.compile(
    r"^\s*(?:[（(]?([0-9]+(?:\.[0-9]+)*|[一二三四五六七八九十百]+)[).、）．]\s*)(.*)$"
)
SENTENCE_PATTERN = re.compile(r"[^。；;！？!?]+[。；;！？!?]?")


@dataclass(frozen=True)
class ClauseSegment:
    clause_id: str
    title: str
    text: str
    version: str = ""
    order: int = 0

    @property
    def normalized(self) -> str:
        return _normalize_for_alignment(self.text)

    @property
    def location(self) -> str:
        return f"{self.title} / {self.clause_id}" if self.title else self.clause_id


@dataclass(frozen=True)
class ContractContextIndex:
    pair_id: str
    before_segments: list[ClauseSegment]
    after_segments: list[ClauseSegment]
    outline: list[str]


def diff_contract_pair(pair: ContractPair) -> DiffResult:
    index = split_and_index_contract(pair.pair_id, pair.before_text, pair.after_text)
    return DiffResult(
        pair_id=pair.pair_id,
        changed_clauses=detect_candidate_diffs(pair.pair_id, index),
    )


def split_and_index_contract(
    pair_id: str,
    before_text: str,
    after_text: str,
) -> ContractContextIndex:
    before_segments = split_contract_clauses(before_text, version="before")
    after_segments = split_contract_clauses(after_text, version="after")
    outline = _contract_outline([*before_segments, *after_segments])
    return ContractContextIndex(
        pair_id=pair_id,
        before_segments=before_segments,
        after_segments=after_segments,
        outline=outline,
    )


def detect_candidate_diffs(
    pair_id: str,
    context_index: ContractContextIndex,
) -> list[DiffClause]:
    before_segments = context_index.before_segments
    after_segments = context_index.after_segments
    if [segment.normalized for segment in before_segments] == [
        segment.normalized for segment in after_segments
    ]:
        return []

    matcher = SequenceMatcher(
        None,
        [segment.normalized for segment in before_segments],
        [segment.normalized for segment in after_segments],
        autojunk=False,
    )
    raw_deletes: list[ClauseSegment] = []
    raw_inserts: list[ClauseSegment] = []
    clauses: list[DiffClause] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        before_chunk = before_segments[i1:i2]
        after_chunk = after_segments[j1:j2]
        if tag == "equal":
            continue
        if tag == "delete":
            raw_deletes.extend(before_chunk)
            continue
        if tag == "insert":
            raw_inserts.extend(after_chunk)
            continue
        if tag == "replace":
            changes, deletes, inserts = _pair_replaced_segments(
                before_chunk, after_chunk
            )
            clauses.extend(changes)
            raw_deletes.extend(deletes)
            raw_inserts.extend(inserts)

    move_clauses, remaining_deletes, remaining_inserts = _detect_moves(
        raw_deletes, raw_inserts
    )
    clauses.extend(move_clauses)
    clauses.extend(_single_side_clauses(remaining_deletes, "删除"))
    clauses.extend(_single_side_clauses(remaining_inserts, "新增"))
    return _with_diff_ids(pair_id, clauses)


def split_contract_clauses(text: str, version: str = "") -> list[ClauseSegment]:
    segments: list[ClauseSegment] = []
    current_section = "全文"
    order = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        major_match = MAJOR_CLAUSE_PATTERN.match(line)
        if major_match:
            current_section = f"第{major_match.group(1)}条"
            rest = major_match.group(2).strip()
            if rest:
                order = _append_sentence_segments(
                    segments,
                    rest,
                    current_section,
                    version,
                    order,
                )
            continue

        sub_match = SUB_CLAUSE_PATTERN.match(line)
        if sub_match:
            title = f"{current_section} {sub_match.group(1)}".strip()
            body = sub_match.group(2).strip()
            if body:
                order = _append_sentence_segments(segments, body, title, version, order)
            continue

        order = _append_sentence_segments(
            segments, line, current_section, version, order
        )

    if segments:
        return segments
    stripped = text.strip()
    return (
        [ClauseSegment("s-0001", "全文", stripped, version=version, order=1)]
        if stripped
        else []
    )


def _append_sentence_segments(
    segments: list[ClauseSegment],
    text: str,
    title: str,
    version: str,
    order: int,
) -> int:
    for sentence in _split_sentences(text):
        normalized = _normalize_for_alignment(sentence)
        if not normalized:
            continue
        order += 1
        segments.append(
            ClauseSegment(
                clause_id=f"s-{order:04d}",
                title=title,
                text=sentence,
                version=version,
                order=order,
            )
        )
    return order


def _split_sentences(text: str) -> list[str]:
    return [
        match.group(0).strip()
        for match in SENTENCE_PATTERN.finditer(text)
        if match.group(0).strip()
    ]


def _pair_replaced_segments(
    before_chunk: list[ClauseSegment],
    after_chunk: list[ClauseSegment],
) -> tuple[list[DiffClause], list[ClauseSegment], list[ClauseSegment]]:
    clauses: list[DiffClause] = []
    deletes: list[ClauseSegment] = []
    inserts: list[ClauseSegment] = []
    used_after: set[int] = set()

    for before_segment in before_chunk:
        best_index = _best_segment_index(before_segment, after_chunk, used_after)
        if best_index is None:
            deletes.append(before_segment)
            continue
        used_after.add(best_index)
        after_segment = after_chunk[best_index]
        if before_segment.normalized == after_segment.normalized:
            clauses.append(_move_clause(before_segment, after_segment))
        else:
            clauses.append(_changed_clause(before_segment, after_segment))

    for index, after_segment in enumerate(after_chunk):
        if index not in used_after:
            inserts.append(after_segment)
    return clauses, deletes, inserts


def _best_segment_index(
    before_segment: ClauseSegment,
    after_chunk: list[ClauseSegment],
    used_after: set[int],
) -> int | None:
    candidates = [
        (index, segment)
        for index, segment in enumerate(after_chunk)
        if index not in used_after
    ]
    if not candidates:
        return None
    best_index, best_segment = max(
        candidates,
        key=lambda item: _similarity(before_segment.normalized, item[1].normalized),
    )
    score = _similarity(before_segment.normalized, best_segment.normalized)
    return best_index if score >= 0.22 else None


def _detect_moves(
    deletes: list[ClauseSegment],
    inserts: list[ClauseSegment],
) -> tuple[list[DiffClause], list[ClauseSegment], list[ClauseSegment]]:
    move_clauses: list[DiffClause] = []
    remaining_deletes: list[ClauseSegment] = []
    used_inserts: set[int] = set()

    for before_segment in deletes:
        best_index = _best_move_index(before_segment, inserts, used_inserts)
        if best_index is None:
            remaining_deletes.append(before_segment)
            continue
        used_inserts.add(best_index)
        move_clauses.append(_move_clause(before_segment, inserts[best_index]))

    remaining_inserts = [
        segment for index, segment in enumerate(inserts) if index not in used_inserts
    ]
    return move_clauses, remaining_deletes, remaining_inserts


def _best_move_index(
    before_segment: ClauseSegment,
    inserts: list[ClauseSegment],
    used_inserts: set[int],
) -> int | None:
    candidates = [
        (index, segment)
        for index, segment in enumerate(inserts)
        if index not in used_inserts
    ]
    if not candidates:
        return None
    best_index, best_segment = max(
        candidates,
        key=lambda item: _similarity(before_segment.normalized, item[1].normalized),
    )
    score = _similarity(before_segment.normalized, best_segment.normalized)
    return best_index if score >= 0.92 else None


def _single_side_clauses(
    segments: list[ClauseSegment],
    change_type: str,
) -> list[DiffClause]:
    clauses: list[DiffClause] = []
    for segment in segments:
        before_text = segment.text if change_type == "删除" else ""
        after_text = segment.text if change_type == "新增" else ""
        review_module = _infer_review_module(before_text, after_text)
        is_substantive = _is_substantive_change(before_text, after_text)
        clauses.append(
            DiffClause(
                review_module=review_module,
                change_type=change_type,
                before=before_text,
                after=after_text,
                before_location=segment.location if change_type == "删除" else None,
                after_location=segment.location if change_type == "新增" else None,
                diff_summary=_summarize_diff(
                    review_module,
                    before_text,
                    after_text,
                    is_substantive,
                    change_type=change_type,
                ),
                is_substantive=is_substantive,
                substantive_reason=_substantive_reason(is_substantive, change_type),
                confidence=0.72 if is_substantive else 0.42,
            )
        )
    return clauses


def _changed_clause(
    before_segment: ClauseSegment, after_segment: ClauseSegment
) -> DiffClause:
    before_text = before_segment.text
    after_text = after_segment.text
    review_module = _infer_review_module(before_text, after_text)
    is_substantive = _is_substantive_change(before_text, after_text)
    return DiffClause(
        review_module=review_module,
        change_type="更改",
        before=before_text,
        after=after_text,
        before_location=before_segment.location,
        after_location=after_segment.location,
        diff_summary=_summarize_diff(
            review_module,
            before_text,
            after_text,
            is_substantive,
            change_type="更改",
        ),
        is_substantive=is_substantive,
        substantive_reason=_substantive_reason(is_substantive, "更改"),
        confidence=0.82 if is_substantive else 0.45,
    )


def _move_clause(
    before_segment: ClauseSegment, after_segment: ClauseSegment
) -> DiffClause:
    review_module = _infer_review_module(before_segment.text, after_segment.text)
    return DiffClause(
        review_module=review_module,
        change_type="移位",
        before=before_segment.text,
        after=after_segment.text,
        before_location=before_segment.location,
        after_location=after_segment.location,
        diff_summary=(
            f"{review_module}发生条款移位：由“{before_segment.location}”移动到"
            f"“{after_segment.location}”。"
        ),
        is_substantive=False,
        substantive_reason="文本内容基本一致，仅位置或编号发生变化",
        confidence=0.86,
    )


def _with_diff_ids(pair_id: str, clauses: list[DiffClause]) -> list[DiffClause]:
    return [
        clause.model_copy(
            update={"diff_id": clause.diff_id or f"{pair_id}-diff-{index}"}
        )
        for index, clause in enumerate(clauses, start=1)
    ]


def _infer_review_module(before: str, after: str) -> str:
    text = before + after
    if any(
        word in text
        for word in (
            "知识产权",
            "源代码",
            "交付成果",
            "技术文档",
            "接口文档",
            "既有技术",
            "通用组件",
        )
    ):
        return "知识产权"
    if any(
        word in text
        for word in (
            "SLA",
            "服务水平",
            "响应",
            "恢复",
            "故障",
            "未达标",
            "扣减",
            "扣款",
        )
    ):
        return "服务水平"
    if any(word in text for word in ("押金", "退还", "无息退还", "剩余押金")):
        return "押金退还"
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
    if "保密" in text:
        return "保密条款"
    if "解除" in text or "终止" in text:
        return "解除条款"
    if any(
        word in text
        for word in ("数据", "个人信息", "删除", "返还", "书面证明", "加密", "访问控制")
    ):
        return "数据安全"
    if any(
        word in text
        for word in (
            "付款",
            "支付",
            "款项",
            "付款申请",
            "支付相应款项",
            "服务费",
            "发票",
        )
    ):
        return "付款条款"
    if any(
        word in text
        for word in (
            "验收标准",
            "组织验收",
            "验收期限",
            "验收不合格",
            "免费整改",
            "整改",
        )
    ):
        return "交付验收"
    if any(word in text for word in ("管辖", "法院", "仲裁")):
        return "管辖法院"
    if "争议" in text:
        return "争议解决"
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
    return "通用条款"


def _is_substantive_change(before: str, after: str) -> bool:
    text = before + after
    if not any(keyword in text for keyword in SUBSTANTIVE_KEYWORDS):
        return False
    if not before or not after:
        return True
    if any(
        keyword in text
        for keyword in (
            "管辖",
            "法院",
            "仲裁",
            "责任上限",
            "赔偿总额",
            "知识产权",
            "源代码",
            "SLA",
            "响应",
            "扣减",
        )
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
        "相关服务": "服务",
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


def _normalize_for_alignment(text: str) -> str:
    normalized = _normalize_polish(text)
    normalized = re.sub(r"[：:]", "", normalized)
    return normalized


def _strip_leading_numbering(text: str) -> str:
    current = text.strip()
    while True:
        updated = LEADING_NUMBERING_PATTERN.sub("", current, count=1)
        if updated == current:
            return current
        current = updated.strip()


def _summarize_diff(
    review_module: str,
    before: str,
    after: str,
    is_substantive: bool,
    change_type: str = "更改",
) -> str:
    if change_type == "新增":
        return (
            f"{review_module}新增实质内容：“{after}”。"
            if is_substantive
            else f"{review_module}新增非实质内容：“{after}”。"
        )
    if change_type == "删除":
        return (
            f"{review_module}删除实质内容：“{before}”。"
            if is_substantive
            else f"{review_module}删除非实质内容：“{before}”。"
        )
    if is_substantive:
        return f"{review_module}发生实质性更改：由“{before}”调整为“{after}”。"
    return f"{review_module}疑似仅发生措辞润色：由“{before}”调整为“{after}”。"


def _substantive_reason(is_substantive: bool, change_type: str) -> str:
    if change_type == "移位":
        return "文本内容基本一致，仅位置或编号发生变化"
    if is_substantive:
        return "涉及权利义务、期限、金额、责任、条件或可复用审核要点变化"
    return "仅疑似措辞、格式、编号或标点变化"


def _similarity(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def _contract_outline(segments: list[ClauseSegment]) -> list[str]:
    outline: list[str] = []
    for segment in segments:
        if segment.title and segment.title not in outline:
            outline.append(segment.title)
    return outline
