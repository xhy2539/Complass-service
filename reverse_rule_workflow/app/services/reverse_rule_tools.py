import re
from dataclasses import dataclass
from typing import Any

from app.models.reverse_rule import CandidateRuleForDB
from app.models.reverse_rule import DiffClause
from app.services.diff_service import ClauseSegment
from app.services.diff_service import ContractContextIndex
from app.services.diff_service import split_and_index_contract


@dataclass(frozen=True)
class ContextSnippet:
    text: str
    location: str
    score: float = 0.0


@dataclass(frozen=True)
class ContextPack:
    diff_id: str
    local_context: list[ContextSnippet]
    related_context: list[ContextSnippet]
    references: list[ContextSnippet]
    outline: list[str]

    def model_dump(self) -> dict[str, Any]:
        return {
            "diff_id": self.diff_id,
            "local_context": [snippet.__dict__ for snippet in self.local_context],
            "related_context": [snippet.__dict__ for snippet in self.related_context],
            "references": [snippet.__dict__ for snippet in self.references],
            "outline": self.outline,
        }


def get_local_context(
    context_index: ContractContextIndex,
    diff: DiffClause,
    window: int = 1,
) -> list[ContextSnippet]:
    snippets: list[ContextSnippet] = []
    for version, target_text in (("before", diff.before), ("after", diff.after)):
        if not target_text:
            continue
        segments = (
            context_index.before_segments
            if version == "before"
            else context_index.after_segments
        )
        index = _find_segment_index(segments, target_text)
        if index is None:
            continue
        start = max(0, index - window)
        end = min(len(segments), index + window + 1)
        for segment in segments[start:end]:
            snippets.append(
                ContextSnippet(text=segment.text, location=segment.location, score=1.0)
            )
    return _dedupe_snippets(snippets)


def semantic_context_search(
    context_index: ContractContextIndex,
    query: str,
    top_k: int = 3,
) -> list[ContextSnippet]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    candidates: list[ContextSnippet] = []
    seen_text: set[str] = set()
    for segment in [*context_index.before_segments, *context_index.after_segments]:
        if segment.text in seen_text:
            continue
        seen_text.add(segment.text)
        score = _weighted_score(query_tokens, segment.text)
        if score <= 0:
            continue
        candidates.append(
            ContextSnippet(text=segment.text, location=segment.location, score=score)
        )
    candidates.sort(key=lambda snippet: snippet.score, reverse=True)
    return candidates[:top_k]


def resolve_references(
    context_index: ContractContextIndex,
    diff: DiffClause,
    terms: list[str],
) -> list[ContextSnippet]:
    reference_terms = [
        term for term in terms if term and term in f"{diff.before}{diff.after}"
    ]
    if not reference_terms:
        reference_terms = [
            term
            for term in (
                "附件",
                "验收标准",
                "本条",
                "上述",
                "服务费",
                "定义",
                "交付成果",
                "保密信息",
            )
            if term in f"{diff.before}{diff.after}"
        ]
    snippets: list[ContextSnippet] = []
    for term in reference_terms:
        snippets.extend(semantic_context_search(context_index, term, top_k=2))
    return _dedupe_snippets(snippets)


def get_contract_outline(context_index: ContractContextIndex) -> list[str]:
    return context_index.outline


def build_context_pack(
    pair_id: str,
    before_text: str,
    after_text: str,
    diff: DiffClause,
    context_index: ContractContextIndex | None = None,
) -> ContextPack:
    if context_index is None:
        context_index = split_and_index_contract(pair_id, before_text, after_text)
    query = _context_query(diff)
    local = get_local_context(context_index, diff)
    related = semantic_context_search(context_index, query, top_k=4) if query else []
    references = resolve_references(
        context_index,
        diff,
        ["附件", "验收标准", "服务费", "定义", "交付成果", "保密信息"],
    )
    return ContextPack(
        diff_id=diff.diff_id,
        local_context=local,
        related_context=related,
        references=references,
        outline=get_contract_outline(context_index),
    )


def validate_evidence(
    candidate_rule: CandidateRuleForDB,
    diff: DiffClause,
    context_pack: ContextPack | None = None,
) -> bool:
    evidence_pool = "\n".join(
        [
            diff.before,
            diff.after,
            *(
                snippet.text
                for snippet in (
                    []
                    if context_pack is None
                    else [
                        *context_pack.local_context,
                        *context_pack.related_context,
                        *context_pack.references,
                    ]
                )
            ),
        ]
    )
    for trace in candidate_rule.traces:
        if trace.source_diff_id and trace.source_diff_id != diff.diff_id:
            return False
        if not trace.source_diff_id:
            return False
        if trace.evidence_before and trace.evidence_before not in evidence_pool:
            return False
        if trace.evidence_after and trace.evidence_after not in evidence_pool:
            return False
    return True


def _context_query(diff: DiffClause) -> str:
    text = f"{diff.review_module} {diff.before} {diff.after}"
    if diff.review_module == "服务水平":
        return f"{text} SLA 响应时间 恢复时间 服务费 扣减 未达标"
    if diff.review_module == "知识产权":
        return f"{text} 源代码 交付成果 既有组件 技术文档 权利归属"
    if diff.review_module == "交付验收":
        return f"{text} 验收标准 验收期限 整改 不合格"
    if diff.review_module == "押金退还":
        return f"{text} 押金 退还 交接 结清 工作日"
    return text


def _find_segment_index(segments: list[ClauseSegment], text: str) -> int | None:
    for index, segment in enumerate(segments):
        if segment.text == text:
            return index
    for index, segment in enumerate(segments):
        if text and (text in segment.text or segment.text in text):
            return index
    return None


def _tokens(text: str) -> list[str]:
    normalized = "".join(text.lower().split())
    tokens = re.findall(r"[a-zA-Z0-9%]+", text.lower())
    tokens.extend(re.findall(r"[\u4e00-\u9fff]{2,}", text))
    for size in (2, 3, 4):
        if len(normalized) >= size:
            tokens.extend(
                normalized[index : index + size]
                for index in range(len(normalized) - size + 1)
            )
    return tokens


def _weighted_score(query_tokens: list[str], text: str) -> float:
    normalized_text = "".join(text.lower().split())
    score = 0.0
    for token in query_tokens:
        if token and token in normalized_text:
            score += max(1.0, min(len(token), 8) / 2)
    return score


def _dedupe_snippets(snippets: list[ContextSnippet]) -> list[ContextSnippet]:
    deduped: list[ContextSnippet] = []
    seen: set[tuple[str, str]] = set()
    for snippet in snippets:
        key = (snippet.location, snippet.text)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(snippet)
    return deduped
