from decimal import Decimal

import pytest
from pydantic import ValidationError

from bisheng.dsh.domain.schemas.unified_policy import (
    CreditRuleInput,
    ModelVisibilityInput,
    PolicySubject,
    credit_balance,
    credits_from_tokens,
    effective_token_limit,
)


def test_visibility_is_independent_of_credit_balance():
    visibility = ModelVisibilityInput(version=0, subjects=[PolicySubject(kind="ROLE", id=8)])
    assert visibility.permits(user_id=3, departments=set(), roles={8})
    assert effective_token_limit(user_id=3, departments=set(), roles={8}, rules=[]) == 0
    assert not visibility.permits(user_id=3, departments={8}, roles=set())


def test_membership_changes_and_everyone():
    policy = ModelVisibilityInput(version=2, subjects=[PolicySubject(kind="DEPARTMENT", id=4)])
    assert policy.permits(user_id=3, departments={4, 5}, roles=set())
    assert not policy.permits(user_id=3, departments={6}, roles=set())
    assert ModelVisibilityInput(version=0, everyone=True).permits(user_id=3, departments=set(), roles=set())


@pytest.mark.parametrize(
    "personal,department,role,expected",
    [
        (10000, 5000, 8000, 10000),
        (1000, 5000, 8000, 8000),
        (1000, 5000, 2000, 5000),
        (0, 5000, 8000, 8000),
        (5000, 5000, 5000, 5000),
    ],
)
def test_matching_credit_allowances_use_maximum(personal, department, role, expected):
    rules = [
        {"subject_type": "USER", "subject_id": 3, "enabled": True, "monthly_token_limit": personal * 1_000_000},
        {"subject_type": "DEPARTMENT", "subject_id": 4, "enabled": True, "monthly_token_limit": department * 1_000_000},
        {"subject_type": "ROLE", "subject_id": 8, "enabled": True, "monthly_token_limit": role * 1_000_000},
    ]
    assert effective_token_limit(user_id=3, departments={4}, roles={8}, rules=rules) == expected * 1_000_000


def test_only_enabled_matching_allowances_contribute():
    rules = [
        {"subject_type": "USER", "subject_id": 3, "enabled": False, "monthly_token_limit": 10000},
        {"subject_type": "USER", "subject_id": 9, "enabled": True, "monthly_token_limit": 20000},
        {"subject_type": "DEPARTMENT", "subject_id": 4, "enabled": True, "monthly_token_limit": 5000},
        {"subject_type": "ROLE", "subject_id": 8, "enabled": True, "monthly_token_limit": 8000},
    ]
    assert effective_token_limit(user_id=3, departments={4}, roles={8}, rules=rules) == 8000
    assert effective_token_limit(user_id=3, departments={4}, roles=set(), rules=rules) == 5000
    assert effective_token_limit(user_id=3, departments=set(), roles=set(), rules=rules) == 0


def test_conversion_preserves_small_usage_and_clamps_display_balance():
    assert CreditRuleInput(version=0, monthly_credits="500").monthly_token_limit == 500_000_000
    assert Decimal(credits_from_tokens(1)) == Decimal("0.000001")
    assert credit_balance(limit=500_000_000, used=499_000_001)["remaining"] == "0.999999"
    assert credit_balance(limit=0, used=1)["remaining"] == "0"
    assert credit_balance(limit=100, used=None)["remaining"] is None


def test_ambiguous_or_duplicate_scope_is_rejected():
    subject = PolicySubject(kind="USER", id=3)
    with pytest.raises(ValidationError):
        ModelVisibilityInput(version=0, everyone=True, subjects=[subject])
    with pytest.raises(ValidationError):
        ModelVisibilityInput(version=0, subjects=[subject, subject])
    with pytest.raises(ValidationError):
        CreditRuleInput(version=0, monthly_credits=True)


@pytest.mark.parametrize(
    "credits",
    ["-1", "1e3", "0.01", "1.00", "1000000.1", "1000001", "0.0000001", "9223372036854.775808", "NaN", "01", 500, True],
)
def test_credit_input_preserves_exact_decimal_contract(credits):
    with pytest.raises(ValidationError):
        CreditRuleInput(version=0, monthly_credits=credits)


def test_credit_input_accepts_smallest_allowance_increment():
    assert CreditRuleInput(version=0, monthly_credits="0.1").monthly_token_limit == 100_000


@pytest.mark.parametrize("multiplier,rate", [("1", 100), ("1.1", 110), ("1.25", 125), ("0.01", 1), ("1000", 100000)])
def test_model_multiplier_uses_exact_fixed_point(multiplier, rate):
    assert ModelVisibilityInput(version=0, credit_multiplier=multiplier).credit_rate == rate


@pytest.mark.parametrize("multiplier", ["0", "-1", "1000.01", "1.001", "NaN", "1e2", True, 1.25])
def test_invalid_model_multiplier_is_rejected(multiplier):
    with pytest.raises(ValidationError):
        ModelVisibilityInput(version=0, credit_multiplier=multiplier)


@pytest.mark.parametrize(
    "credits,tokens",
    [("0", 0), ("999999.9", 999999900000), ("1000000", 1000000000000), ("1000000.0", 1000000000000)],
)
def test_credit_allowance_accepts_business_boundaries(credits, tokens):
    assert CreditRuleInput(version=0, monthly_credits=credits).monthly_token_limit == tokens
