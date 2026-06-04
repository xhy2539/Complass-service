from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from langchain_core.documents import Document
from pydantic import ValidationError

from app.kb.schema import ReverseRuleCase

DEFAULT_CASES_PATH = Path("data/reverse_rule_cases.jsonl")
CONTENT_FIELDS = [
    "review_module",
    "change_pattern",
    "diff_summary",
    "user_intent",
    "risk_name",
    "check_point",
    "trigger_condition",
    "suggestion_template",
    "example_clause",
]


def load_reverse_rule_cases(
    path: str | Path = DEFAULT_CASES_PATH,
) -> list[ReverseRuleCase]:
    jsonl_path = Path(path)
    cases: list[ReverseRuleCase] = []

    with jsonl_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
                cases.append(ReverseRuleCase.model_validate(payload))
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                raise ValueError(
                    f"Invalid reverse rule case at line {line_number}: {exc}"
                ) from exc

    return cases


def case_to_document(case: ReverseRuleCase) -> Document:
    page_content = "\n".join(
        f"{field}: {getattr(case, field)}" for field in CONTENT_FIELDS
    )
    metadata = {
        "case_id": case.case_id,
        "contract_type": case.contract_type,
        "review_role": case.review_role,
        "review_module": case.review_module,
        "default_risk_level": case.default_risk_level,
        "tags": case.tags,
    }
    return Document(page_content=page_content, metadata=metadata)


def cases_to_documents(cases: Iterable[ReverseRuleCase]) -> list[Document]:
    return [case_to_document(case) for case in cases]
