"""LLM client wrapper used by the audit workflow."""

from __future__ import annotations

import asyncio
from http.client import RemoteDisconnected
import json
import logging
import time
from typing import Any
from urllib import error, request

from .config import AuditWorkflowSettings, get_settings
from .schemas import LLMConfigError, LLMRequestError, preview_text


logger = logging.getLogger(__name__)
NODE_REQUEST_WINDOW_SECONDS = 600.0
RETRYABLE_RETRY_DELAY_SECONDS = 1.0


class LLMClient:
    def __init__(self, settings: AuditWorkflowSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self._no_proxy_opener = request.build_opener(request.ProxyHandler({}))

    async def complete(
        self,
        prompt: str,
        *,
        step: str = "llm_complete",
        max_window_seconds: float | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._complete_sync,
            prompt,
            step,
            max_window_seconds,
        )

    def _complete_sync(
        self,
        prompt: str,
        step: str,
        max_window_seconds: float | None,
    ) -> str:
        provider = self.settings.llm_provider
        if provider != "minimax":
            raise LLMConfigError(f"Unsupported LLM_PROVIDER: {provider or '<empty>'}")
        if not self.settings.minimax_api_key:
            raise LLMConfigError("MINIMAX_API_KEY is required.")
        if not self.settings.llm_model_name:
            raise LLMConfigError("LLM_MODEL_NAME is required.")
        if not self.settings.minimax_base_url:
            raise LLMConfigError("MINIMAX_BASE_URL is required.")

        endpoint = self._chat_completions_endpoint(self.settings.minimax_base_url)
        payload = {
            "model": self.settings.llm_model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "stream": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.settings.minimax_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        started_at = time.perf_counter()
        response_body = ""
        status = 0
        request_window_seconds = (
            max_window_seconds
            if max_window_seconds is not None
            else NODE_REQUEST_WINDOW_SECONDS
        )
        attempt = 0
        while True:
            attempt += 1
            elapsed_seconds = time.perf_counter() - started_at
            remaining_seconds = request_window_seconds - elapsed_seconds
            if remaining_seconds <= 0:
                raise LLMRequestError(
                    "LLM request failed "
                    f"[step={step} endpoint={endpoint} attempt={attempt} "
                    f"elapsed_ms={round(elapsed_seconds * 1000, 2)} exception=RetryWindowExceeded]: "
                    "retry window exhausted before receiving a valid response."
                )
            try:
                with self._no_proxy_opener.open(
                    req,
                    timeout=min(request_window_seconds, remaining_seconds),
                ) as response:
                    status = response.getcode()
                    charset = response.headers.get_content_charset() or "utf-8"
                    response_body = response.read().decode(charset)
                break
            except RemoteDisconnected as exc:
                elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
                if (time.perf_counter() - started_at) < request_window_seconds:
                    logger.warning(
                        "LLM request disconnected, retrying [step=%s endpoint=%s attempt=%s elapsed_ms=%s exception=%s]: %s",
                        step,
                        endpoint,
                        attempt,
                        elapsed_ms,
                        type(exc).__name__,
                        exc,
                    )
                    time.sleep(RETRYABLE_RETRY_DELAY_SECONDS)
                    continue
                logger.error(
                    "LLM request disconnected [step=%s endpoint=%s attempt=%s elapsed_ms=%s exception=%s]: %s",
                    step,
                    endpoint,
                    attempt,
                    elapsed_ms,
                    type(exc).__name__,
                    exc,
                )
                raise LLMRequestError(
                    "LLM request failed "
                    f"[step={step} endpoint={endpoint} attempt={attempt} "
                    f"elapsed_ms={elapsed_ms} exception={type(exc).__name__}]: {exc}"
                ) from exc
            except error.HTTPError as exc:
                elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
                error_body = exc.read().decode("utf-8", errors="replace")
                logger.error(
                    "LLM request failed [step=%s endpoint=%s status=%s elapsed_ms=%s exception=%s]: %s",
                    step,
                    endpoint,
                    exc.code,
                    elapsed_ms,
                    type(exc).__name__,
                    preview_text(error_body, 500),
                )
                raise LLMRequestError(
                    "LLM request failed "
                    f"[step={step} endpoint={endpoint} status={exc.code} elapsed_ms={elapsed_ms} "
                    f"exception={type(exc).__name__}]: {preview_text(error_body, 500)}"
                ) from exc
            except error.URLError as exc:
                elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
                if (time.perf_counter() - started_at) < request_window_seconds:
                    logger.warning(
                        "LLM request failed, retrying [step=%s endpoint=%s attempt=%s elapsed_ms=%s exception=%s]: %s",
                        step,
                        endpoint,
                        attempt,
                        elapsed_ms,
                        type(exc).__name__,
                        exc,
                    )
                    time.sleep(RETRYABLE_RETRY_DELAY_SECONDS)
                    continue
                logger.error(
                    "LLM request failed [step=%s endpoint=%s attempt=%s elapsed_ms=%s exception=%s]: %s",
                    step,
                    endpoint,
                    attempt,
                    elapsed_ms,
                    type(exc).__name__,
                    exc,
                )
                raise LLMRequestError(
                    "LLM request failed "
                    f"[step={step} endpoint={endpoint} attempt={attempt} elapsed_ms={elapsed_ms} "
                    f"exception={type(exc).__name__}]: {exc}"
                ) from exc

        try:
            data = json.loads(response_body)
        except json.JSONDecodeError as exc:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            raise LLMRequestError(
                "LLM response is not valid JSON. "
                f"[step={step} endpoint={endpoint} status={status} elapsed_ms={elapsed_ms}] "
                f"body_preview={preview_text(response_body, 500)!r}"
            ) from exc
        return self._extract_content(data)

    @staticmethod
    def _chat_completions_endpoint(base_url: str) -> str:
        base = base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    @staticmethod
    def _extract_content(data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict) and message.get("content") is not None:
                    return str(message["content"])
                if first.get("text") is not None:
                    return str(first["text"])

        for key in ("reply", "output_text", "content"):
            if data.get(key) is not None:
                return str(data[key])

        raise LLMRequestError("LLM response does not contain message content.")


def get_llm_client() -> LLMClient:
    return LLMClient()
