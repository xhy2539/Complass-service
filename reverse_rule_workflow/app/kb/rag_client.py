"""RAG 服务 HTTP 客户端适配器。

调用独立 RAG 检索服务，失败时返回空列表让 caller 走降级链。
不影响现有本地 retriever 和 fallback。
"""

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

RAG_URL = os.getenv("RAG_SERVICE_URL", "http://rag-service:8000")
TIMEOUT = 5


def rag_search(
    query: str,
    review_module: str | None = None,
    contract_type: str | None = None,
    review_role: str | None = None,
    top_k: int = 3,
) -> list[dict]:
    try:
        payload = json.dumps(
            {
                "query": query,
                "review_module": review_module,
                "contract_type": contract_type,
                "review_role": review_role,
                "top_k": top_k,
            }
        ).encode()
        req = urllib.request.Request(
            f"{RAG_URL}/search",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read())
            results = body.get("results", [])
            if results:
                logger.info(
                    "[RAG] search returned %d results for query='%s'",
                    len(results),
                    query[:60],
                )
            return results
    except urllib.error.URLError as e:
        logger.debug("[RAG] service unreachable: %s", e)
    except Exception as e:
        logger.warning("[RAG] search failed: %s", e)
    return []
