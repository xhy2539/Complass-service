"""索引构建：从 JSONL 加载案例 → embed → FAISS + BM25 + SQLite。"""

import json
import threading
from pathlib import Path

import faiss

from .db import init_db
from .db import upsert_case
from .embedder import DIM
from .embedder import embed

FAISS_PATH = Path(__file__).resolve().parent.parent / "storage" / "faiss.index"
DEFAULT_JSONL = (
    Path(__file__).resolve().parent.parent / "data" / "reverse_rule_cases.jsonl"
)

_lock = threading.Lock()


def _searchable_text(case: dict) -> str:
    extras = [
        case.get("before_example", ""),
        case.get("after_example", ""),
        " ".join(case.get("contract_type", [])),
        " ".join(case.get("review_role", [])),
        " ".join(case.get("tags", [])),
    ]
    parts = [
        _field_text(case, "review_module"),
        _field_text(case, "change_pattern"),
        _field_text(case, "diff_summary"),
        _field_text(case, "user_intent"),
        _field_text(case, "risk_name"),
        _field_text(case, "check_point"),
        _field_text(case, "trigger_condition"),
        _field_text(case, "suggestion_template"),
        _field_text(case, "example_clause"),
    ]
    return "\n".join([*parts, *extras])


def _field_text(case: dict, key: str) -> str:
    val = case.get(key, "")
    return f"{key}: {val}" if val else ""


def _load_jsonl(path: Path) -> list[dict]:
    cases = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def rebuild(jsonl_path: str | None = None) -> dict:
    path = Path(jsonl_path) if jsonl_path else DEFAULT_JSONL
    cases = _load_jsonl(path)
    with _lock:
        # 构建 embedding
        texts = [_searchable_text(c) for c in cases]
        vectors = embed(texts)

        # 构建 FAISS
        index = faiss.IndexFlatIP(DIM)
        index.add(vectors)
        faiss.write_index(index, str(FAISS_PATH))

        # 构建 SQLite
        init_db()
        for c in cases:
            upsert_case(c)

    return {
        "indexed": len(cases),
        "modules": len({c.get("review_module", "") for c in cases}),
    }


def add_case(case: dict) -> None:
    with _lock:
        text = _searchable_text(case)
        vec = embed([text])

        if FAISS_PATH.exists():
            index = faiss.read_index(str(FAISS_PATH))
            index.add(vec)
            faiss.write_index(index, str(FAISS_PATH))
        else:
            index = faiss.IndexFlatIP(DIM)
            index.add(vec)
            faiss.write_index(index, str(FAISS_PATH))

        init_db()
        upsert_case(case)
