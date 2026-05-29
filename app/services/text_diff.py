"""文本比对服务，实现句子级 diff 算法。"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class SentenceDiff:
    """单个句子比对结果。"""

    index: int
    old_text: Optional[str]
    new_text: Optional[str]
    change_type: str  # "added", "deleted", "modified", "unchanged"
    similarity: float = 0.0
    old_position: Optional[dict] = None  # 旧句子的位置信息
    new_position: Optional[dict] = None  # 新句子的位置信息


def split_into_sentences(text: str) -> list[str]:
    """
    将文本拆分成句子。

    Args:
        text: 输入文本

    Returns:
        句子列表
    """
    sentences = re.split(r"(?<=[。！？；\n])\s*", text)
    return [s.strip() for s in sentences if s.strip()]


def compute_similarity(text1: str, text2: str) -> float:
    """
    计算两个文本的相似度（简单实现）。

    Args:
        text1: 文本1
        text2: 文本2

    Returns:
        相似度 0.0 ~ 1.0
    """
    if not text1 or not text2:
        return 0.0

    set1 = set(text1)
    set2 = set(text2)
    intersection = len(set1 & set2)
    union = len(set1 | set2)

    return intersection / union if union > 0 else 0.0


def sentence_diff(
    old_text: str, new_text: str, similarity_threshold: float = 0.6
) -> list[SentenceDiff]:
    """
    对比两个文本，返回句子级差异。

    Args:
        old_text: 旧版本文本
        new_text: 新版本文本
        similarity_threshold: 判断修改的相似度阈值（默认 0.6）

    Returns:
        SentenceDiff 列表
    """
    old_sentences = split_into_sentences(old_text)
    new_sentences = split_into_sentences(new_text)

    result: list[SentenceDiff] = []
    used_old_indices = set()
    used_new_indices = set()

    for i, new_sent in enumerate(new_sentences):
        best_match_idx = -1
        best_similarity = 0.0

        for j, old_sent in enumerate(old_sentences):
            if j in used_old_indices:
                continue
            sim = compute_similarity(new_sent, old_sent)
            if sim > best_similarity:
                best_similarity = sim
                best_match_idx = j

        if best_similarity >= similarity_threshold:
            used_old_indices.add(best_match_idx)
            used_new_indices.add(i)
            result.append(
                SentenceDiff(
                    index=len(result),
                    old_text=old_sentences[best_match_idx],
                    new_text=new_sent,
                    change_type="modified",
                    similarity=best_similarity,
                )
            )
        else:
            used_new_indices.add(i)
            result.append(
                SentenceDiff(
                    index=len(result),
                    old_text=None,
                    new_text=new_sent,
                    change_type="added",
                    similarity=0.0,
                )
            )

    for j, old_sent in enumerate(old_sentences):
        if j not in used_old_indices:
            result.append(
                SentenceDiff(
                    index=len(result),
                    old_text=old_sent,
                    new_text=None,
                    change_type="deleted",
                    similarity=0.0,
                )
            )

    result.sort(key=lambda x: x.index)

    for i, diff in enumerate(result):
        diff.index = i

    return result


def sentence_diff_with_positions(
    old_comparison_data: dict,
    new_comparison_data: dict,
    similarity_threshold: float = 0.6,
) -> list[SentenceDiff]:
    """
    使用带位置的句子数据进行比对（推荐用于生产环境）。

    Args:
        old_comparison_data: 旧文档的 comparison_data（包含 sentences 和 key_clauses）
        new_comparison_data: 新文档的 comparison_data
        similarity_threshold: 相似度阈值

    Returns:
        SentenceDiff 列表，包含位置信息
    """
    old_sentences = old_comparison_data.get("sentences", [])
    new_sentences = new_comparison_data.get("sentences", [])

    result: list[SentenceDiff] = []
    used_old_indices = set()
    used_new_indices = set()

    for i, new_sent in enumerate(new_sentences):
        best_match_idx = -1
        best_similarity = 0.0

        for j, old_sent in enumerate(old_sentences):
            if j in used_old_indices:
                continue
            sim = compute_similarity(new_sent["text"], old_sent["text"])
            if sim > best_similarity:
                best_similarity = sim
                best_match_idx = j

        if best_similarity >= similarity_threshold:
            used_old_indices.add(best_match_idx)
            used_new_indices.add(i)
            result.append(
                SentenceDiff(
                    index=len(result),
                    old_text=old_sentences[best_match_idx]["text"],
                    new_text=new_sentences[i]["text"],
                    change_type="modified",
                    similarity=best_similarity,
                    old_position={
                        "char_offset_start": old_sentences[best_match_idx][
                            "char_offset_start"
                        ],
                        "char_offset_end": old_sentences[best_match_idx][
                            "char_offset_end"
                        ],
                        "paragraph_index": old_sentences[best_match_idx][
                            "paragraph_index"
                        ],
                    },
                    new_position={
                        "char_offset_start": new_sentences[i]["char_offset_start"],
                        "char_offset_end": new_sentences[i]["char_offset_end"],
                        "paragraph_index": new_sentences[i]["paragraph_index"],
                    },
                )
            )
        else:
            used_new_indices.add(i)
            result.append(
                SentenceDiff(
                    index=len(result),
                    old_text=None,
                    new_text=new_sentences[i]["text"],
                    change_type="added",
                    similarity=0.0,
                    new_position={
                        "char_offset_start": new_sentences[i]["char_offset_start"],
                        "char_offset_end": new_sentences[i]["char_offset_end"],
                        "paragraph_index": new_sentences[i]["paragraph_index"],
                    },
                )
            )

    for j, old_sent in enumerate(old_sentences):
        if j not in used_old_indices:
            result.append(
                SentenceDiff(
                    index=len(result),
                    old_text=old_sentences[j]["text"],
                    new_text=None,
                    change_type="deleted",
                    similarity=0.0,
                    old_position={
                        "char_offset_start": old_sentences[j]["char_offset_start"],
                        "char_offset_end": old_sentences[j]["char_offset_end"],
                        "paragraph_index": old_sentences[j]["paragraph_index"],
                    },
                )
            )

    result.sort(key=lambda x: x.index)

    for i, diff in enumerate(result):
        diff.index = i

    return result


def summarize_diff(diffs: list[SentenceDiff]) -> dict:
    """
    汇总差异统计。

    Args:
        diffs: SentenceDiff 列表

    Returns:
        包含统计信息的字典
    """
    added = sum(1 for d in diffs if d.change_type == "added")
    deleted = sum(1 for d in diffs if d.change_type == "deleted")
    modified = sum(1 for d in diffs if d.change_type == "modified")
    unchanged = sum(1 for d in diffs if d.change_type == "unchanged")

    return {
        "total": len(diffs),
        "added": added,
        "deleted": deleted,
        "modified": modified,
        "unchanged": unchanged,
        "added_texts": [d.new_text for d in diffs if d.change_type == "added"],
        "deleted_texts": [d.old_text for d in diffs if d.change_type == "deleted"],
        "modified_texts": [
            {"old": d.old_text, "new": d.new_text, "similarity": d.similarity}
            for d in diffs
            if d.change_type == "modified"
        ],
    }
