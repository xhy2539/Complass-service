from typing import Any

from fastapi import APIRouter

from app.chains.reverse_rule_graph import run_reverse_rule_extraction

router = APIRouter(prefix="/reverse-rule", tags=["reverse-rule"])


@router.post("/extract")
def extract_reverse_rules(contract_pairs: list[dict[str, Any]]) -> dict[str, Any]:
    return run_reverse_rule_extraction(contract_pairs)
