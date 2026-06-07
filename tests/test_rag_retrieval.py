"""RAG 检索效果测试：熔断器。"""

import json
import os
import time


def _load_rag_module():
    """用 importlib 加载 rag_client 模块，避免 app 包名冲突。"""
    import importlib.util
    import logging
    import urllib.error
    import urllib.request

    spec = importlib.util.spec_from_file_location(
        "rag_client",
        "reverse_rule_workflow/app/kb/rag_client.py",
    )
    mod = importlib.util.module_from_spec(spec)
    mod.logger = logging.getLogger("test")
    mod.json = json
    mod.os = os
    mod.time = time
    mod.urllib = urllib
    mod._rag_dead_until = 0.0
    spec.loader.exec_module(mod)
    return mod


def test_rag_circuit_breaker_opens_on_unreachable():
    """RAG 不可用时熔断器打开，快速返回空列表。"""
    os.environ["RAG_SERVICE_URL"] = "http://127.0.0.1:19999"
    mod = _load_rag_module()

    start = time.monotonic()
    result = mod.rag_search("test query")
    elapsed = time.monotonic() - start

    assert result == [], "Dead RAG should return empty"
    assert elapsed < 5, f"Should timeout quickly, took {elapsed:.1f}s"
    assert mod._rag_dead_until > 0, "Circuit breaker should open"


def test_circuit_breaker_returns_instantly_when_open():
    """熔断器打开后，后续调用立即返回不发起网络请求。"""
    os.environ["RAG_SERVICE_URL"] = "http://127.0.0.1:19999"
    mod = _load_rag_module()
    # 手动设熔断器为打开状态（未来 60s 内）
    mod._rag_dead_until = time.monotonic() + 60

    start = time.monotonic()
    result = mod.rag_search("test query")
    elapsed = time.monotonic() - start

    assert result == [], "Open circuit should return empty"
    assert elapsed < 0.5, (
        f"Circuit open should return near-instantly, took {elapsed:.3f}s"
    )


def test_circuit_breaker_resets_after_cooldown():
    """冷却期结束后熔断器恢复，重新尝试连接。"""
    os.environ["RAG_SERVICE_URL"] = "http://127.0.0.1:19999"
    mod = _load_rag_module()
    # 设熔断器为 1 秒前过期
    mod._rag_dead_until = time.monotonic() - 1

    result = mod.rag_search("test query")

    assert result == [], "Should try connection and fail"
    # 应该重新尝试连接（超时），然后再次打开熔断器
    assert mod._rag_dead_until > time.monotonic(), (
        "Circuit should reopen after retry fails"
    )
