"""Standalone contract comparison workflow."""

from .rules_client import fetch_audit_rules
from .workflow import (
    analyze_diff_risks_with_llm,
    classify_compare_contract_type,
    compare_contracts,
    identify_differences,
    normalize_compare_output,
    parse_compare_rule_response,
)

__all__ = [
    "analyze_diff_risks_with_llm",
    "classify_compare_contract_type",
    "compare_contracts",
    "fetch_audit_rules",
    "identify_differences",
    "normalize_compare_output",
    "parse_compare_rule_response",
]
