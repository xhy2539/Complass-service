"""Standalone contract comparison workflow."""

from .rules_client import fetch_audit_rules
from .workflow import analyze_diff_risks_with_llm
from .workflow import classify_compare_contract_type
from .workflow import compare_contracts
from .workflow import identify_differences
from .workflow import normalize_compare_output
from .workflow import parse_compare_rule_response

__all__ = [
    "analyze_diff_risks_with_llm",
    "classify_compare_contract_type",
    "compare_contracts",
    "fetch_audit_rules",
    "identify_differences",
    "normalize_compare_output",
    "parse_compare_rule_response",
]
