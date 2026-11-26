"""F011 field policies use raw values, never clean historical values on read."""

import pytest

from bisheng.common.errcode.user import AccountFormatError, NicknameValidationError
from bisheng.user.domain.rules.identity import (
    account_key,
    password_meets_policy,
    validate_account,
    validate_nickname,
    validate_nickname_change,
)


@pytest.mark.parametrize("value", ["a", "0", "a" * 64, "AB001", "ab001", "00033", "A._-@9"])
def test_valid_accounts_preserve_original(value):
    """AC-02, AC-03: preserve case and leading zeroes."""
    assert validate_account(value) == value


@pytest.mark.parametrize("value", ["", "a" * 65, "_a", ".a", "-a", "@a", "中文", "a+b", " a", "a ", "a\tb", "a\u200bb"])
def test_invalid_accounts_are_rejected(value):
    """AC-03, AC-05: direct requests reject raw invalid values."""
    with pytest.raises(AccountFormatError):
        validate_account(value)


@pytest.mark.parametrize("value", ["中", "a" * 32, "中" * 32, "𠮷" * 32, "昵称._-@", "😀"])
def test_valid_nicknames(value):
    """AC-04: count Unicode code points, allow duplicate display values."""
    assert validate_nickname(value) == value


@pytest.mark.parametrize(
    "value", ["", "a" * 33, " a", "a b", "a\n", "a\u3000b", "a\u200bb", "a\u2060b", "a\x00b", "a\ufe0f", "\ud800"]
)
def test_invalid_nicknames(value):
    with pytest.raises(NicknameValidationError):
        validate_nickname(value)


def test_unchanged_historical_name_is_allowed():
    """AC-06, AC-07: compare before validating, including a reverted draft."""
    historical = " old name " + "中" * 40
    assert validate_nickname_change(historical, historical) is False
    assert validate_nickname_change(historical, "新昵称") is True
    with pytest.raises(NicknameValidationError):
        validate_nickname_change(historical, "new name")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", False),
        ("Aa1!", False),
        ("Aa1!aaaa", True),
        ("a1!aaaaa", False),
        ("AA1!AAAA", False),
        ("Aa!!aaaa", False),
        ("Aa11aaaa", False),
        ("Aa1  aaaa", False),
        ("Aa1中文aaaa", False),
        ("Aa1_aaaa", True),
        ("Aa1😀aaaa", True),
        ("Aa1!" + "a" * 124, True),
        ("Aa1!" + "a" * 125, False),
    ],
)
def test_password_policy(value, expected):
    """AC-29: real punctuation/symbol, length includes the existing upper bound."""
    assert password_meets_policy(value) is expected


def test_exact_account_keys():
    """AC-09: hash keys do not inherit database text collation."""
    assert len(account_key("AB001")) == 64
    assert account_key("AB001") != account_key("ab001")
