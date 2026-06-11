"""Minimal live LLM diagnostics for MiniMax connectivity and environment."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from contract_compare_workflow.llm_client import LLMConfig
from contract_compare_workflow.llm_client import _extract_chat_content
from contract_compare_workflow.llm_client import load_project_env

HELLO_PROMPT = '只返回严格 JSON，不要 Markdown，不要解释：{"ok": true, "message": "hello"}'
BASE_URLS = [
    "https://api.minimax.io/v1",
    "https://api.minimaxi.com/v1",
]
PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")


def _preview(value: Any, limit: int = 1000) -> str:
    text = "" if value is None else str(value)
    return text[:limit]


def _chat_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _looks_like_model_error(text: str) -> bool:
    lowered = text.lower()
    return any(
        keyword in lowered
        for keyword in (
            "unknown model",
            "invalid model",
            "model not found",
            "does not exist",
            "unsupported model",
            "model",
        )
    )


def _looks_like_payload_error(text: str) -> bool:
    lowered = text.lower()
    return any(
        keyword in lowered
        for keyword in (
            "invalid request",
            "invalid parameter",
            "messages",
            "content",
            "json",
            "malformed",
            "schema",
            "body",
        )
    )


def classify_failure(
    *,
    endpoint: str,
    status_code: int | None,
    response_text: str,
    exception: Exception | None,
) -> tuple[str, str]:
    if exception is not None:
        if isinstance(exception, httpx.ConnectError):
            return "connect_error", "DNS / 网络连接失败"
        if isinstance(exception, httpx.InvalidURL):
            return "invalid_url", "base_url 拼接错误"
        if isinstance(exception, httpx.UnsupportedProtocol):
            return "invalid_url", "base_url 拼接错误"
        if isinstance(exception, httpx.ConnectTimeout):
            return "connect_timeout", "网络连接超时"
        if isinstance(exception, httpx.ReadTimeout):
            return "read_timeout", "读取响应超时"
        if isinstance(exception, httpx.TimeoutException):
            return "timeout", "网络连接或读取超时"
        if isinstance(exception, httpx.ProxyError):
            return "proxy_error", "代理连接失败"
        if isinstance(exception, httpx.RemoteProtocolError):
            return "tls_or_protocol_error", "TLS / 协议握手异常"
        if isinstance(exception, httpx.HTTPError):
            return "http_error", "HTTP 请求异常"
        return "request_exception", "未知请求异常"

    if status_code is None:
        return "request_exception", "未知请求异常"
    if status_code in {401, 403}:
        return "auth_error", "鉴权失败"
    if status_code == 404 and endpoint.endswith("/chat/completions"):
        return "base_url_error", "base_url 拼接错误"
    if status_code in {400, 404, 422} and _looks_like_model_error(response_text):
        return "model_error", "模型名错误"
    if status_code in {400, 422} and _looks_like_payload_error(response_text):
        return "payload_error", "请求体格式错误"
    if 200 <= status_code < 300:
        return "response_parse_error", "响应字段解析错误"
    if status_code in {408, 504}:
        return "timeout", "服务端超时"
    if status_code >= 500:
        return "server_error", "服务端错误"
    return "unknown_http_error", "未知服务端错误"


async def send_probe(*, base_url: str, trust_env: bool) -> dict[str, Any]:
    env = load_project_env(refresh=True)
    config = LLMConfig.from_env()
    endpoint = _chat_endpoint(base_url)
    payload = {
        "model": config.model_name,
        "messages": [{"role": "user", "content": HELLO_PROMPT}],
        "temperature": 0,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }

    result: dict[str, Any] = {
        "base_url": base_url,
        "endpoint": endpoint,
        "trust_env": trust_env,
        "elapsed_ms": 0.0,
        "http_status_code": None,
        "response_preview": "",
        "exception_type": "",
        "exception_message": "",
        "failure_code": "",
        "failure_type": "",
        "content_preview": "",
    }

    response: httpx.Response | None = None
    exception: Exception | None = None
    started_at = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=config.timeout_seconds, trust_env=trust_env) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
    except Exception as exc:
        exception = exc
    finally:
        result["elapsed_ms"] = round((time.perf_counter() - started_at) * 1000.0, 3)

    if exception is not None:
        failure_code, failure_type = classify_failure(
            endpoint=endpoint,
            status_code=None,
            response_text="",
            exception=exception,
        )
        result["exception_type"] = type(exception).__name__
        result["exception_message"] = str(exception) or repr(exception)
        result["failure_code"] = failure_code
        result["failure_type"] = failure_type
        return result

    assert response is not None
    result["http_status_code"] = response.status_code
    result["response_preview"] = _preview(response.text)

    if not (200 <= response.status_code < 300):
        failure_code, failure_type = classify_failure(
            endpoint=endpoint,
            status_code=response.status_code,
            response_text=response.text,
            exception=None,
        )
        result["failure_code"] = failure_code
        result["failure_type"] = failure_type
        return result

    try:
        response_json = response.json()
    except json.JSONDecodeError as exc:
        result["exception_type"] = type(exc).__name__
        result["exception_message"] = str(exc)
        result["failure_code"] = "response_parse_error"
        result["failure_type"] = "响应字段解析错误"
        return result

    content = _extract_chat_content(response_json if isinstance(response_json, dict) else {})
    if content is None:
        result["failure_code"] = "response_parse_error"
        result["failure_type"] = "响应字段解析错误"
        result["exception_type"] = "LLMContentParseError"
        result["exception_message"] = "LLM response does not contain message content"
        return result

    result["content_preview"] = _preview(content)
    return result


def summarize_recommendation(probes: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [probe for probe in probes if 200 <= int(probe.get("http_status_code") or 0) < 300 and not probe.get("failure_code")]
    if successes:
        preferred = successes[0]
        return {
            "can_reach_llm": True,
            "recommended_base_url": preferred["base_url"],
            "reason": (
                "该 base_url 在当前环境下已成功返回 HTTP 2xx 和可解析内容。"
                "建议将 .env 中的 MINIMAX_BASE_URL 改为这个值。"
            ),
        }

    by_trust = {(probe["base_url"], probe["trust_env"]): probe for probe in probes}
    trust_env_true_success = any(
        probe for probe in probes if probe["trust_env"] is True and not probe["failure_code"]
    )
    trust_env_false_success = any(
        probe for probe in probes if probe["trust_env"] is False and not probe["failure_code"]
    )

    if trust_env_true_success and not trust_env_false_success:
        return {
            "can_reach_llm": False,
            "recommended_base_url": "",
            "reason": "trust_env=True 成功而 trust_env=False 失败，说明 Python 需要走系统/环境代理。",
        }
    if trust_env_false_success and not trust_env_true_success:
        return {
            "can_reach_llm": False,
            "recommended_base_url": "",
            "reason": "trust_env=False 成功而 trust_env=True 失败，说明代理环境变量可能有问题。",
        }

    failure_codes = {probe["failure_code"] for probe in probes}
    if failure_codes == {"connect_error"} or failure_codes == {"connect_error", ""}:
        reason = "两个 base_url 在 trust_env=True/False 下都卡在 ConnectError，更像 DNS、网络出站、防火墙或代理链路问题。"
    elif "tls_or_protocol_error" in failure_codes:
        reason = "至少有一个探针命中 TLS / 协议握手异常，需排查 TLS、证书、代理中间人或 VPN。"
    elif "base_url_error" in failure_codes:
        reason = "至少有一个探针命中 base_url / endpoint 错误。"
    else:
        reason = "两个 base_url 当前都不可用，需结合 failure_code 继续排查网络、代理、地区或服务端限制。"

    return {
        "can_reach_llm": False,
        "recommended_base_url": "",
        "reason": reason,
    }


async def main() -> None:
    env = load_project_env(refresh=True)
    env_summary = {
        "LLM_PROVIDER_exists": bool(env.get("LLM_PROVIDER")),
        "LLM_MODEL_NAME_exists": bool(env.get("LLM_MODEL_NAME")),
        "MINIMAX_API_KEY_exists": bool(env.get("MINIMAX_API_KEY")),
        "MINIMAX_BASE_URL_exists": bool(env.get("MINIMAX_BASE_URL")),
        "proxy_env": {
            key: {
                "exists": bool(os.environ.get(key)),
                "preview": _preview(os.environ.get(key, ""), 200) if os.environ.get(key) else "",
            }
            for key in PROXY_KEYS
        },
    }

    probes: list[dict[str, Any]] = []
    for base_url in BASE_URLS:
        for trust_env in (True, False):
            probes.append(await send_probe(base_url=base_url, trust_env=trust_env))

    output = {
        "environment": env_summary,
        "probes": probes,
        "recommendation": summarize_recommendation(probes),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
