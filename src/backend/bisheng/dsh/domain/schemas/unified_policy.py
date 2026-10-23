"""Shared model visibility and personal credit rules for Chat and Work."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TOKENS_PER_CREDIT = 1_000_000
MAX_TOKEN_LIMIT = 9_223_372_036_854_775_807


def credits_from_tokens(tokens: int) -> str:
    """Keep accounting exact, including consumption below one credit."""
    if type(tokens) is not int or tokens < 0:
        raise ValueError("Token amounts must be nonnegative integers")
    return format(Decimal(tokens) / TOKENS_PER_CREDIT, "f")


class PolicySubject(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    kind: Literal["DEPARTMENT", "ROLE", "USER"]
    id: int = Field(gt=0, le=MAX_TOKEN_LIMIT)


class ModelVisibilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = Field(ge=0)
    credit_multiplier: str = Field(default="1", pattern=r"^(0|[1-9][0-9]{0,3})(\.[0-9]{1,2})?$")
    everyone: bool = False
    subjects: list[PolicySubject] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def validate_scope(self):
        if not 1 <= self.credit_rate <= 100000:
            raise ValueError("Credit multiplier must be between 0.01 and 1000")
        if self.everyone and self.subjects:
            raise ValueError("Everyone visibility has an empty subject list")
        if len(set(self.subjects)) != len(self.subjects):
            raise ValueError("Visibility subjects must be unique")
        return self

    @property
    def credit_rate(self) -> int:
        return int(Decimal(self.credit_multiplier) * 100)

    def permits(self, *, user_id: int, departments: set[int], roles: set[int]) -> bool:
        memberships = {"USER": {user_id}, "DEPARTMENT": departments, "ROLE": roles}
        return self.everyone or any(subject.id in memberships[subject.kind] for subject in self.subjects)


class CreditRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = Field(ge=0)
    monthly_credits: str = Field(pattern=r"^(0|[1-9][0-9]{0,12})(\.[0-9]{1,6})?$")

    @model_validator(mode="after")
    def validate_limit(self):
        if self.monthly_token_limit > MAX_TOKEN_LIMIT:
            raise ValueError("Credit limit exceeds the accounting range")
        return self

    enabled: bool = True

    @property
    def monthly_token_limit(self) -> int:
        return int(Decimal(self.monthly_credits) * TOKENS_PER_CREDIT)


def effective_token_limit(*, user_id: int, departments: set[int], roles: set[int], rules: list[dict]) -> int:
    """Use the highest enabled allowance across matching users, departments and roles."""
    memberships = {"USER": {user_id}, "DEPARTMENT": departments, "ROLE": roles}
    matching = [
        rule for rule in rules if rule["enabled"] and rule["subject_id"] in memberships.get(rule["subject_type"], set())
    ]
    return max((rule["monthly_token_limit"] for rule in matching), default=0)


def credit_balance(*, limit: int, used: int | None) -> dict:
    return {
        "limit": credits_from_tokens(limit),
        "used": credits_from_tokens(used) if used is not None else None,
        "remaining": credits_from_tokens(max(0, limit - used)) if used is not None else None,
        "tokens_per_credit": TOKENS_PER_CREDIT,
    }
