from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CASE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
BACKEND_GENERATED_FIELDS = {
    "id",
    "version_id",
    "rule_code",
    "enabled",
    "created_at",
    "updated_at",
}


class ReverseRuleCase(BaseModel):
    """A few-shot case for deriving audit rules from contract edits."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    contract_type: list[str] = Field(min_length=1)
    review_role: list[str] = Field(min_length=1)
    review_module: str
    change_pattern: str
    before_example: str
    after_example: str
    diff_summary: str
    user_intent: str
    risk_name: str
    check_point: str
    trigger_condition: str
    default_risk_level: Literal["低", "中", "高"]
    suggestion_template: str
    example_clause: str
    tags: list[str] = Field(min_length=1)

    @field_validator(
        "case_id",
        "review_module",
        "change_pattern",
        "before_example",
        "after_example",
        "diff_summary",
        "user_intent",
        "risk_name",
        "check_point",
        "trigger_condition",
        "suggestion_template",
        "example_clause",
    )
    @classmethod
    def non_empty_string(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("contract_type", "review_role", "tags")
    @classmethod
    def non_empty_string_list(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = item.strip()
            if not text:
                raise ValueError("list items must not be empty")
            if text not in seen:
                normalized.append(text)
                seen.add(text)
        if not normalized:
            raise ValueError("must contain at least one item")
        return normalized

    @field_validator("case_id")
    @classmethod
    def stable_case_id(cls, value: str) -> str:
        if not CASE_ID_PATTERN.match(value):
            raise ValueError("case_id must use lowercase snake id format")
        return value

    @model_validator(mode="before")
    @classmethod
    def reject_backend_generated_fields(cls, data: object) -> object:
        if isinstance(data, dict):
            forbidden = BACKEND_GENERATED_FIELDS & set(data)
            if forbidden:
                names = ", ".join(sorted(forbidden))
                raise ValueError(f"backend-generated fields are not allowed: {names}")
        return data

    @model_validator(mode="after")
    def examples_should_show_a_change(self) -> "ReverseRuleCase":
        if self.before_example == self.after_example:
            raise ValueError("before_example and after_example must differ")
        return self
