"""Minimal LLM client for the contract comparison workflow."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


DEFAULT_MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_LLM_PROVIDER = "minimax"

_ENV_CACHE: dict[str, str] | None = None


class LLMClientError(RuntimeError):
    """Raised when the LLM client cannot complete a request."""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _unquote_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_project_env(refresh: bool = False) -> dict[str, str]:
    """Read root .env and merge it with process env.

    Process environment values take precedence so deployment-time injection can
    override the local .env without changing this module.
    """

    global _ENV_CACHE
    if _ENV_CACHE is not None and not refresh:
        return dict(_ENV_CACHE)

    values: dict[str, str] = {}
    env_path = _project_root() / ".env"

    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            values[key] = _unquote_env_value(value)

    merged = {**values, **os.environ}
    _ENV_CACHE = {key: str(value) for key, value in merged.items()}
    return dict(_ENV_CACHE)


def get_config_value(key: str, default: str | None = None) -> str | None:
    value = load_project_env().get(key)
    if value is None or value == "":
        return default
    return value


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model_name: str
    api_key: str
    base_url: str
    timeout_seconds: float = 600.0

    @classmethod
    def from_env(cls) -> "LLMConfig":
        provider = get_config_value("LLM_PROVIDER", DEFAULT_LLM_PROVIDER) or DEFAULT_LLM_PROVIDER
        model_name = get_config_value("LLM_MODEL_NAME", "")
        api_key = get_config_value("MINIMAX_API_KEY", "")
        base_url = get_config_value("MINIMAX_BASE_URL", DEFAULT_MINIMAX_BASE_URL) or DEFAULT_MINIMAX_BASE_URL

        if provider.lower() != "minimax":
            raise LLMClientError(f"Unsupported LLM_PROVIDER: {provider}")
        if not model_name:
            raise LLMClientError("LLM_MODEL_NAME is required")
        if not api_key:
            raise LLMClientError("MINIMAX_API_KEY is required")

        return cls(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
        )


class LLMClient:
    """OpenAI-compatible chat completions client for MiniMax."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()

    @property
    def chat_completions_url(self) -> str:
        base_url = self.config.base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    async def chat(self, prompt: str, *, json_mode: bool = False) -> str:
        payload = {
            "model": self.config.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                trust_env=False,
            ) as client:
                response = await client.post(self.chat_completions_url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMClientError(
                f"LLM request failed: timeout ({type(exc).__name__}) endpoint={self.chat_completions_url}"
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMClientError(
                f"LLM request failed: connect_error ({type(exc).__name__}) endpoint={self.chat_completions_url}"
            ) from exc
        except httpx.NetworkError as exc:
            raise LLMClientError(
                f"LLM request failed: network_error ({type(exc).__name__}) endpoint={self.chat_completions_url}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMClientError(
                f"LLM request failed: http_error ({type(exc).__name__}) endpoint={self.chat_completions_url}"
            ) from exc

        if response.status_code < 200 or response.status_code >= 300:
            response_preview = _preview_text(response.text)
            raise LLMClientError(
                f"LLM request failed with status {response.status_code} endpoint={self.chat_completions_url}: {response_preview}"
            )

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise LLMClientError("LLM response is not valid JSON") from exc

        content = _extract_chat_content(data)
        if content is None:
            raise LLMClientError("LLM response does not contain message content")
        return content


def _extract_chat_content(data: dict[str, Any]) -> str | None:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
            if isinstance(first.get("text"), str):
                return first["text"]

    if isinstance(data.get("reply"), str):
        return data["reply"]
    if isinstance(data.get("output_text"), str):
        return data["output_text"]

    nested_data = data.get("data")
    if isinstance(nested_data, dict):
        return _extract_chat_content(nested_data)

    return None


async def chat_completion(prompt: str, *, json_mode: bool = False) -> str:
    return await LLMClient().chat(prompt, json_mode=json_mode)


def _preview_text(value: Any, limit: int = 500) -> str:
    text = value if isinstance(value, str) else str(value)
    if len(text) <= limit:
        return text
    return text[:limit]
