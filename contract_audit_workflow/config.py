"""Configuration loading for the contract audit workflow."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path


DEFAULT_AUDIT_RULES_API_URL = "http://82.156.132.43:8080/api/audit-rules"
DEFAULT_AUDIT_RULES_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class AuditWorkflowSettings:
    llm_provider: str
    llm_model_name: str
    minimax_api_key: str
    minimax_base_url: str
    audit_rules_api_url: str
    audit_rules_timeout_seconds: int = DEFAULT_AUDIT_RULES_TIMEOUT_SECONDS


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_dotenv_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        values[key] = value
    return values


def _get_value(key: str, dotenv_values: dict[str, str], default: str = "") -> str:
    value = os.getenv(key)
    if value is not None and value != "":
        return value
    return dotenv_values.get(key, default)


@lru_cache(maxsize=1)
def get_settings() -> AuditWorkflowSettings:
    dotenv_values = _load_dotenv_file(_repo_root() / ".env")
    timeout_value = _get_value(
        "AUDIT_RULES_TIMEOUT_SECONDS",
        dotenv_values,
        str(DEFAULT_AUDIT_RULES_TIMEOUT_SECONDS),
    )
    try:
        timeout_seconds = int(timeout_value)
    except ValueError:
        timeout_seconds = DEFAULT_AUDIT_RULES_TIMEOUT_SECONDS

    return AuditWorkflowSettings(
        llm_provider=_get_value("LLM_PROVIDER", dotenv_values).strip().lower(),
        llm_model_name=_get_value("LLM_MODEL_NAME", dotenv_values).strip(),
        minimax_api_key=_get_value("MINIMAX_API_KEY", dotenv_values).strip(),
        minimax_base_url=_get_value("MINIMAX_BASE_URL", dotenv_values).strip(),
        audit_rules_api_url=_get_value(
            "AUDIT_RULES_API_URL",
            dotenv_values,
            DEFAULT_AUDIT_RULES_API_URL,
        ).strip(),
        audit_rules_timeout_seconds=timeout_seconds,
    )


def clear_settings_cache() -> None:
    get_settings.cache_clear()
