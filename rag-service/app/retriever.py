"""混合检索：BM25 关键词 + FAISS 向量 + SQLite 过滤 → Top-N。"""

import json
import threading
from pathlib import Path

import faiss
from rank_bm25 import BM25Okapi

from .db import filter_ids
from .db import load_cases
from .embedder import embed

FAISS_PATH = Path(__file__).resolve().parent.parent / "storage" / "faiss.index"
_lock = threading.Lock()

_FAISS_INDEX: faiss.IndexFlatIP | None = None
_BM25_INDEX: dict[str, BM25Okapi] = {}
_BM25_DOCS: dict[str, list[str]] = {}
_BM25_IDS: dict[str, list[str]] = {}


def _get_faiss_index() -> faiss.IndexFlatIP:
    global _FAISS_INDEX
    if _FAISS_INDEX is None:
        with _lock:
            if _FAISS_INDEX is None and FAISS_PATH.exists():
                _FAISS_INDEX = faiss.read_index(str(FAISS_PATH))
    return _FAISS_INDEX


def _tokenize(text: str) -> list[str]:
    import re

    tokens = re.findall(r"[一-鿿]+|[a-zA-Z0-9]+", text.lower())
    bigrams = [text[i : i + 2] for i in range(len(text) - 1) if text[i : i + 2].strip()]
    return tokens + bigrams


def _build_bm25() -> None:
    global _BM25_INDEX, _BM25_DOCS, _BM25_IDS
    from .db import _conn

    with _lock:
        c = _conn()
        rows = c.execute(
            "SELECT case_id, review_module, data_json FROM cases"
        ).fetchall()
        docs_by_module: dict[str, list[list[str]]] = {}
        ids_by_module: dict[str, list[str]] = {}

        for row in rows:
            data = json.loads(row["data_json"])
            module = row["review_module"] or "__all__"
            text = " ".join(
                [
                    data.get("change_pattern", ""),
                    data.get("risk_name", ""),
                    data.get("check_point", ""),
                    data.get("trigger_condition", ""),
                    data.get("diff_summary", ""),
                    data.get("user_intent", ""),
                ]
            )
            tokens = _tokenize(text)
            docs_by_module.setdefault(module, []).append(tokens)
            ids_by_module.setdefault(module, []).append(row["case_id"])

        _BM25_DOCS = docs_by_module
        _BM25_IDS = ids_by_module
        for module, docs in docs_by_module.items():
            _BM25_INDEX[module] = BM25Okapi(docs)
        c.close()


def hybrid_search(
    query: str,
    review_module: str | None = None,
    contract_type: str | None = None,
    review_role: str | None = None,
    n_candidates: int = 10,
) -> list[dict]:
    # 1. FAISS 向量检索 Top-100
    faiss_index = _get_faiss_index()
    faiss_scores: dict[str, float] = {}
    if faiss_index is not None:
        qv = embed([query])[0].reshape(1, -1)
        distances, indices = faiss_index.search(qv, min(100, faiss_index.ntotal))
        # map FAISS idx → case_id via DB
        from .db import _conn

        c = _conn()
        all_ids = [row[0] for row in c.execute("SELECT case_id FROM cases").fetchall()]
        c.close()
        for dist, idx in zip(distances[0], indices[0]):
            if idx < len(all_ids):
                faiss_scores[all_ids[idx]] = float(dist)

    # 2. BM25 关键词检索
    bm25_scores: dict[str, float] = {}
    if not _BM25_INDEX:
        _build_bm25()
    q_tokens = _tokenize(query)
    for module, bm25 in _BM25_INDEX.items():
        if review_module and module != review_module:
            continue
        scores = bm25.get_scores(q_tokens)
        for i, score in enumerate(scores):
            cid = _BM25_IDS[module][i]
            bm25_scores[cid] = max(bm25_scores.get(cid, 0), float(score))
    # normalize BM25 to 0-1 range
    if bm25_scores:
        max_bm = max(bm25_scores.values())
        if max_bm > 0:
            bm25_scores = {k: v / max_bm for k, v in bm25_scores.items()}

    # 3. 加权融合 (0.6 × FAISS + 0.4 × BM25)
    all_ids = set(faiss_scores) | set(bm25_scores)
    merged = {}
    for cid in all_ids:
        fs = faiss_scores.get(cid, 0.0)
        bs = bm25_scores.get(cid, 0.0)
        # if only one source has it, still include it
        if fs == 0.0:
            merged[cid] = 0.4 * bs
        elif bs == 0.0:
            merged[cid] = 0.6 * fs
        else:
            merged[cid] = 0.6 * fs + 0.4 * bs

    # 4. SQLite metadata filter
    meta_ids = filter_ids(
        review_module=review_module,
        contract_type=contract_type,
        review_role=review_role,
    )
    if meta_ids:
        merged = {k: v for k, v in merged.items() if k in meta_ids}

    # 5. Sort and return top-N
    ranked = sorted(merged.items(), key=lambda x: x[1], reverse=True)
    top_ids = [cid for cid, _ in ranked[:n_candidates]]

    return load_cases(top_ids)
