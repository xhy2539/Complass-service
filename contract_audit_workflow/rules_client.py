"""Audit rules HTTP client."""

from __future__ import annotations

import asyncio
from http.client import RemoteDisconnected
import logging
import time
from urllib import error, parse, request

from .config import get_settings
from .schemas import LLMOutputError, RulesFetchError, parse_json_like, preview_text


logger = logging.getLogger(__name__)


async def fetch_audit_rules(contract_type: str) -> dict:
    return await asyncio.to_thread(_fetch_audit_rules_sync, contract_type)


def _fetch_audit_rules_sync(contract_type: str) -> dict:
    settings = get_settings()
    if not settings.audit_rules_api_url:
        raise RulesFetchError("AUDIT_RULES_API_URL is required.")

    step = "fetch_audit_rules"
    query = parse.urlencode({"contract_type": contract_type})
    separator = "&" if "?" in settings.audit_rules_api_url else "?"
    url = f"{settings.audit_rules_api_url}{separator}{query}"
    req = request.Request(url, method="GET")

    started_at = time.perf_counter()
    try:
        with request.urlopen(req, timeout=settings.audit_rules_timeout_seconds) as response:
            status = response.getcode()
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset)
    except error.HTTPError as exc:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        error_body = exc.read().decode("utf-8", errors="replace")
        logger.error(
            "Audit rules request failed [step=%s url=%s contract_type=%s status=%s elapsed_ms=%s exception=%s]: %s",
            step,
            url,
            contract_type,
            exc.code,
            elapsed_ms,
            type(exc).__name__,
            preview_text(error_body, 500),
        )
        raise RulesFetchError(
            "Audit rules request failed "
            f"[step={step} url={url} contract_type={contract_type} status={exc.code} "
            f"elapsed_ms={elapsed_ms} exception={type(exc).__name__}]: "
            f"{preview_text(error_body, 500)}"
        ) from exc
    except RemoteDisconnected as exc:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.error(
            "Audit rules request disconnected [step=%s url=%s contract_type=%s elapsed_ms=%s exception=%s]: %s",
            step,
            url,
            contract_type,
            elapsed_ms,
            type(exc).__name__,
            exc,
        )
        raise RulesFetchError(
            "Audit rules request failed "
            f"[step={step} url={url} contract_type={contract_type} "
            f"elapsed_ms={elapsed_ms} exception={type(exc).__name__}]: {exc}"
        ) from exc
    except error.URLError as exc:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.error(
            "Audit rules request failed [step=%s url=%s contract_type=%s elapsed_ms=%s exception=%s]: %s",
            step,
            url,
            contract_type,
            elapsed_ms,
            type(exc).__name__,
            exc,
        )
        raise RulesFetchError(
            "Audit rules request failed "
            f"[step={step} url={url} contract_type={contract_type} "
            f"elapsed_ms={elapsed_ms} exception={type(exc).__name__}]: {exc}"
        ) from exc

    if status < 200 or status >= 300:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        raise RulesFetchError(
            "Audit rules request failed "
            f"[step={step} url={url} contract_type={contract_type} status={status} "
            f"elapsed_ms={elapsed_ms}]: {preview_text(body, 500)}"
        )

    try:
        parsed = parse_json_like(body)
    except LLMOutputError as exc:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        raise RulesFetchError(
            "Audit rules response is not valid JSON. "
            f"[step={step} url={url} contract_type={contract_type} status={status} "
            f"elapsed_ms={elapsed_ms}] body_preview={preview_text(body, 500)!r} "
            f"parse_error={type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        raise RulesFetchError(
            "Audit rules response must be a JSON object. "
            f"[step={step} url={url} contract_type={contract_type} status={status} "
            f"elapsed_ms={elapsed_ms}] parsed_type={type(parsed).__name__}"
        )
    return parsed
