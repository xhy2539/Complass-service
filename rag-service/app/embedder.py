"""千问 text-embedding-v3 API embedding，1024 维。"""

import logging
import os

import httpx
import numpy as np

logger = logging.getLogger(__name__)
DIM = 1024
_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"


def embed(texts: list[str]) -> np.ndarray:
    if not _API_KEY:
        logger.warning(
            "DASHSCOPE_API_KEY not set, using random vectors. Set the key for real embeddings."
        )
        rng = np.random.RandomState(sum(len(t) for t in texts) % (2**31))
        vecs = rng.randn(len(texts), DIM).astype(np.float32)
        norm = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / norm

    batch_size = 25
    all_vecs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        try:
            resp = httpx.post(
                _BASE,
                headers={"Authorization": f"Bearer {_API_KEY}"},
                json={
                    "model": "text-embedding-v3",
                    "input": batch,
                    "dimensions": DIM,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            all_vecs.extend([d["embedding"] for d in data["data"]])
        except Exception:
            logger.exception(
                "DashScope API call failed for batch %d/%d. Falling back to random vectors.",
                i // batch_size + 1,
                (len(texts) + batch_size - 1) // batch_size,
            )
            rng = np.random.RandomState(sum(len(t) for t in batch) % (2**31))
            fallback = rng.randn(len(batch), DIM).astype(np.float32)
            fallback_norm = np.linalg.norm(fallback, axis=1, keepdims=True)
            all_vecs.extend(fallback / fallback_norm)

    vecs = np.array(all_vecs, dtype=np.float32)
    norm = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / norm
