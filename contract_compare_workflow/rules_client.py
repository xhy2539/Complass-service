"""Audit rules API client for the contract comparison workflow."""

from __future__ import annotations

from typing import Any

import httpx

from .llm_client import get_config_value


DEFAULT_AUDIT_RULES_API_URL = "http://82.156.132.43:8080/api/audit-rules"


async def fetch_audit_rules(contract_type: str) -> dict[str, Any]:
    """Call GET /api/audit-rules?contract_type=xxx.

    The response body is returned as text because downstream parsing must handle
    objects, JSON strings, and double-encoded JSON strings consistently.
    """

    url = get_config_value("AUDIT_RULES_API_URL", DEFAULT_AUDIT_RULES_API_URL)
    params = {"contract_type": contract_type}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        return {
            "body": "",
            "status_code": 0,
            "error": str(exc),
        }

    return {
        "body": response.text,
        "status_code": response.status_code,
    }
