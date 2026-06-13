"""模型工厂：统一管理所有 LLM/Embedding 提供商，自动降级。

用法:
    from app.services.model_factory import get_completion, get_json, get_embedding

    # 多 provider 自动降级
    result = get_json(prompt, temperature=0)
    text = get_completion(prompt)
    vecs = get_embedding(texts)  # (n, 1024)
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# ---------------------------------------------------------------------------
# Provider registry — 配一个 env var 就注册一个
# ---------------------------------------------------------------------------


def _build_providers() -> list[dict[str, str]]:
    providers: list[dict[str, str]] = []

    # Provider 1: MiniMax M3 (主)
    if _env("MINIMAX_API_KEY"):
        providers.append(
            {
                "name": "minimax",
                "api_key": _env("MINIMAX_API_KEY"),
                "base_url": _env("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1"),
                "model": _env("LLM_MODEL_NAME", "MiniMax-M3"),
            }
        )

    # Provider 2: 千问 Qwen (DashScope key 可同时用 embedding 和对话)
    if _env("DASHSCOPE_API_KEY"):
        providers.append(
            {
                "name": "qwen",
                "api_key": _env("DASHSCOPE_API_KEY"),
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model": _env("QWEN_MODEL_NAME", "qwen-plus"),
            }
        )

    # Provider 3: OpenAI 兼容 (如有独立 key)
    if _env("OPENAI_API_KEY") and _env("OPENAI_BASE_URL"):
        providers.append(
            {
                "name": "openai",
                "api_key": _env("OPENAI_API_KEY"),
                "base_url": _env("OPENAI_BASE_URL"),
                "model": _env("OPENAI_MODEL_NAME", "gpt-4o-mini"),
            }
        )

    return providers


def _build_embedding_providers() -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []

    # DashScope 千问 (主)
    if _env("DASHSCOPE_API_KEY"):
        providers.append(
            {
                "name": "dashscope",
                "api_key": _env("DASHSCOPE_API_KEY"),
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
                "model": "text-embedding-v3",
                "dim": 1024,
            }
        )

    return providers


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_completion(
    prompt: str,
    system: str | None = None,
    temperature: float = 0,
    max_tokens: int = 2048,
    timeout: float = 30.0,
) -> str | None:
    """多 provider 降级的文本补全，返回原始文本。"""
    providers = _build_providers()
    if not providers:
        logger.warning("[ModelFactory] 无可用 LLM provider")
        return None

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    for config in providers:
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    f"{config['base_url']}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {config['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": config["model"],
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                )
                if resp.status_code != 200:
                    logger.warning(
                        "[ModelFactory] %s -> HTTP %d, trying next",
                        config["name"],
                        resp.status_code,
                    )
                    continue

                body = resp.json()
                content = body["choices"][0]["message"]["content"]
                logger.info("[ModelFactory] %s 调用成功", config["name"])
                return content

        except Exception:
            logger.warning(
                "[ModelFactory] %s 异常, trying next",
                config["name"],
                exc_info=True,
            )
            continue

    logger.error("[ModelFactory] 所有 provider 均失败")
    return None


def get_json(
    prompt: str,
    temperature: float = 0,
    max_tokens: int = 2048,
    timeout: float = 30.0,
) -> list[dict[str, Any]] | None:
    """多 provider 降级 + JSON 解析，返回解析后的对象列表。"""
    raw = get_completion(
        prompt, temperature=temperature, max_tokens=max_tokens, timeout=timeout
    )
    if raw is None:
        return None

    # 剥离 <think> 推理块 (MiniMax M3)
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    # 尝试1: JSON 数组 [...]
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start >= 0 and end > start:
        try:
            result = json.loads(cleaned[start : end + 1])
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # 尝试2: JSON Lines {}\n{}
    lines = cleaned.split("\n")
    objects = []
    for line in lines:
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                objects.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if objects:
        return objects

    logger.warning("[ModelFactory] 无法解析 JSON, raw=%s", cleaned[:200])
    return None


def get_embedding(texts: list[str], dim: int = 1024):
    """文本嵌入，主 provider 失败降级为确定性随机向量。"""
    import numpy as np

    providers = _build_embedding_providers()

    if providers:
        config = providers[0]  # 只用主 provider，embedding 不迭代降级
        batch_size = 25
        all_vecs = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.post(
                        config["base_url"],
                        headers={"Authorization": f"Bearer {config['api_key']}"},
                        json={
                            "model": config["model"],
                            "input": batch,
                            "dimensions": dim,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    all_vecs.extend([d["embedding"] for d in data["data"]])
            except Exception:
                logger.warning(
                    "[ModelFactory] embedding batch %d failed, fallback random",
                    i // batch_size + 1,
                )
                rng = np.random.RandomState(sum(len(t) for t in batch) % (2**31))
                fallback = rng.randn(len(batch), dim).astype(np.float32)
                fallback_norm = np.linalg.norm(fallback, axis=1, keepdims=True)
                all_vecs.extend(fallback / fallback_norm)
                continue

        vecs = np.array(all_vecs, dtype=np.float32)
        norm = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / norm

    # 无 provider，全量随机向量
    logger.warning("[ModelFactory] 无 embedding provider，使用随机向量")
    total_len = sum(len(t) for t in texts)
    rng = np.random.RandomState(total_len % (2**31))
    vecs = rng.randn(len(texts), dim).astype(np.float32)
    norm = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / norm


def has_llm() -> bool:
    """是否有可用 LLM provider。"""
    return len(_build_providers()) > 0


def has_embedding() -> bool:
    """是否有可用 embedding provider。"""
    return len(_build_embedding_providers()) > 0
