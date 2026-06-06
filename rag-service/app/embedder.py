"""bge-base-zh-v1.5 embedding，单例加载。"""

import threading
from typing import Any

import numpy as np

_EMBEDDER: Any = None
_LOCK = threading.Lock()
DIM = 768


def get_embedder() -> Any:
    global _EMBEDDER
    if _EMBEDDER is None:
        with _LOCK:
            if _EMBEDDER is None:
                from sentence_transformers import SentenceTransformer

                _EMBEDDER = SentenceTransformer("BAAI/bge-base-zh-v1.5", device="cpu")
    return _EMBEDDER


def embed(texts: list[str]) -> np.ndarray:
    model = get_embedder()
    vecs = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        batch_size=32,
    )
    return np.array(vecs, dtype=np.float32)
