"""Contract type classification node."""

from __future__ import annotations

import re

from .audit_prompts import CONTRACT_TYPE_CLASSIFIER_PROMPT
from .llm_client import get_llm_client


SUPPORTED_CONTRACT_TYPES = ("采购合同", "服务合同", "合作协议", "其他")


async def classify_contract_type(content: str) -> str:
    if not str(content or "").strip():
        return "其他"

    prompt = CONTRACT_TYPE_CLASSIFIER_PROMPT.replace("{{content}}", content)
    raw_result = await get_llm_client().complete(
        prompt,
        step="classify_contract_type",
    )
    return normalize_contract_type(raw_result)


def normalize_contract_type(raw_value: str) -> str:
    candidate = str(raw_value or "").strip()
    candidate = candidate.strip(" \t\r\n\"'`。！？；;：:，,、“”‘’")
    if candidate in SUPPORTED_CONTRACT_TYPES:
        return candidate

    compact = re.sub(r"\s+", "", candidate)
    matches: list[tuple[int, str]] = []
    for contract_type in SUPPORTED_CONTRACT_TYPES:
        index = compact.find(contract_type)
        if index != -1:
            matches.append((index, contract_type))

    if matches:
        matches.sort(key=lambda item: (item[0], SUPPORTED_CONTRACT_TYPES.index(item[1])))
        return matches[0][1]

    return "其他"
