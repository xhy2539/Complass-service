from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from app.kb.loader import case_to_document, load_reverse_rule_cases
from app.kb.schema import ReverseRuleCase
from app.services.review_perspective import is_generic_review_role, normalize_review_perspective


DEFAULT_PERSIST_DIR = "storage/reverse_rule_kb"
INDEX_FILE_NAME = "index.json"
EMBEDDING_DIM = 512
MIN_RELEVANCE_SCORE = 0.02

WORD_PATTERN = re.compile(r"[a-zA-Z0-9_]+")


class ReverseRuleCaseRetriever(BaseRetriever):
    """LangChain retriever backed by a small deterministic local index."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    persist_dir: str = DEFAULT_PERSIST_DIR
    k: int = 3
    records: list[dict[str, Any]] = Field(default_factory=list)

    def __init__(self, persist_dir: str = DEFAULT_PERSIST_DIR, k: int = 3, **kwargs: Any) -> None:
        records = _load_index(Path(persist_dir))["records"]
        super().__init__(persist_dir=str(persist_dir), k=k, records=records, **kwargs)

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        results = _search_records(self.records, query=query, k=self.k)
        documents: list[Document] = []
        for result in results:
            metadata = dict(result["metadata"])
            metadata["score"] = result["score"]
            documents.append(Document(page_content=result["page_content"], metadata=metadata))
        return documents


def get_reverse_rule_retriever(
    persist_dir: str = DEFAULT_PERSIST_DIR,
    k: int = 3,
) -> ReverseRuleCaseRetriever:
    return ReverseRuleCaseRetriever(persist_dir=persist_dir, k=k)


def retrieve_reverse_rule_cases(
    query: str,
    review_module: str | None = None,
    contract_type: str | None = None,
    review_role: str | None = None,
    k: int = 3,
) -> list[dict[str, Any]]:
    if _is_non_substantive_query(query):
        return []

    index = _load_index(Path(DEFAULT_PERSIST_DIR))
    results = _search_records(
        index["records"],
        query=query,
        review_module=review_module,
        contract_type=contract_type,
        review_role=review_role,
        k=k,
    )

    output: list[dict[str, Any]] = []
    for result in results:
        if result["score"] < MIN_RELEVANCE_SCORE:
            continue
        item = dict(result["case"])
        item["score"] = result["score"]
        output.append(item)
    return output


def build_reverse_rule_kb(
    cases: list[ReverseRuleCase] | None = None,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
) -> Path:
    case_list = cases if cases is not None else load_reverse_rule_cases()
    target_dir = Path(persist_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for case in case_list:
        document = case_to_document(case)
        searchable_text = _searchable_text(case, document)
        records.append(
            {
                "case": case.model_dump(),
                "page_content": document.page_content,
                "metadata": document.metadata,
                "searchable_text": searchable_text,
                "vector": embed_text(searchable_text),
            }
        )

    payload = {
        "embedding": "deterministic-char-ngram-hash",
        "embedding_dim": EMBEDDING_DIM,
        "records": records,
    }
    index_path = target_dir / INDEX_FILE_NAME
    index_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return index_path


def embed_text(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    vector = [0.0] * dim
    for token in _tokens(text):
        digest = hashlib.md5(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _tokens(text: str) -> list[str]:
    normalized = "".join(text.lower().split())
    tokens: list[str] = []
    tokens.extend(WORD_PATTERN.findall(text.lower()))
    for size in (1, 2, 3, 4):
        if len(normalized) >= size:
            tokens.extend(normalized[index : index + size] for index in range(len(normalized) - size + 1))
    return tokens


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _search_records(
    records: list[dict[str, Any]],
    *,
    query: str,
    k: int,
    review_module: str | None = None,
    contract_type: str | None = None,
    review_role: str | None = None,
) -> list[dict[str, Any]]:
    query_vector = embed_text(query)
    filter_tiers = [
        {
            "review_module": review_module,
            "contract_type": contract_type,
            "review_role": review_role,
        },
        {
            "review_module": review_module,
            "contract_type": contract_type,
            "review_role": None,
        },
        {
            "review_module": review_module,
            "contract_type": None,
            "review_role": None,
        },
        {
            "review_module": None,
            "contract_type": None,
            "review_role": None,
        },
    ]

    for filters in filter_tiers:
        scored = _score_matching_records(records, query_vector=query_vector, **filters)
        if scored:
            return scored[:k]
    return []


def _score_matching_records(
    records: list[dict[str, Any]],
    *,
    query_vector: list[float],
    review_module: str | None,
    contract_type: str | None,
    review_role: str | None,
) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for record in records:
        if not _metadata_matches(
            record["metadata"],
            review_module=review_module,
            contract_type=contract_type,
            review_role=review_role,
        ):
            continue
        scored.append(
            {
                **record,
                "score": round(_cosine(query_vector, record["vector"]), 6),
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored


def _metadata_matches(
    metadata: dict[str, Any],
    *,
    review_module: str | None,
    contract_type: str | None,
    review_role: str | None,
) -> bool:
    if review_module and metadata.get("review_module") != review_module:
        return False
    if contract_type and contract_type not in metadata.get("contract_type", []):
        return False
    if review_role and not is_generic_review_role(review_role):
        metadata_roles = metadata.get("review_role", [])
        if review_role not in metadata_roles:
            review_perspective = normalize_review_perspective(review_role)
            metadata_perspectives = {
                normalize_review_perspective(role)
                for role in metadata_roles
            }
            if review_perspective not in metadata_perspectives:
                return False
    return True


def _load_index(persist_dir: Path) -> dict[str, Any]:
    index_path = persist_dir / INDEX_FILE_NAME
    if not index_path.exists():
        if persist_dir == Path(DEFAULT_PERSIST_DIR) and Path("data/reverse_rule_cases.jsonl").exists():
            build_reverse_rule_kb(persist_dir=persist_dir)
        else:
            raise FileNotFoundError(f"Reverse rule KB index not found: {index_path}")
    return json.loads(index_path.read_text(encoding="utf-8"))


def _searchable_text(case: ReverseRuleCase, document: Document) -> str:
    extra_parts = [
        case.before_example,
        case.after_example,
        " ".join(case.contract_type),
        " ".join(case.review_role),
        " ".join(case.tags),
    ]
    return "\n".join([document.page_content, *extra_parts])


def _is_non_substantive_query(query: str) -> bool:
    normalized = "".join(query.split())
    return any(
        marker in normalized
        for marker in (
            "普通润色",
            "仅措辞润色",
            "非实质",
            "未发生实质",
            "格式变化",
            "标点变化",
        )
    )
