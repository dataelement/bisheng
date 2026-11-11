"""Raw-value identity rules shared by every human-account write path."""

from collections.abc import Sequence
from hashlib import sha256
from typing import Protocol, TypeVar

import regex

from bisheng.common.errcode.user import (
    AccountFormatError,
    AmbiguousAccountError,
    NicknameValidationError,
    UserForbiddenError,
)


class LoginCandidate(Protocol):
    delete: int


Identity = TypeVar("Identity")
LoginIdentity = TypeVar("LoginIdentity", bound=LoginCandidate)


def resolve_external_candidates(candidates: Sequence[Identity]) -> Identity | None:
    if len(candidates) > 1:
        raise AmbiguousAccountError()
    return candidates[0] if candidates else None


def resolve_login_candidates(candidates: Sequence[LoginIdentity]) -> LoginIdentity | None:
    active = [user for user in candidates if user.delete == 0]
    if len(active) > 1:
        raise AmbiguousAccountError()
    if active:
        return active[0]
    if candidates:
        raise UserForbiddenError()
    return None


_ACCOUNT = regex.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,63}\Z")
_WHITESPACE = regex.compile(r"[\s\p{Z}\u200B\u2060]")
_INVISIBLE = regex.compile(r"[\p{Cc}\p{Cf}\p{Cs}\p{Default_Ignorable_Code_Point}]")
_SYMBOL = regex.compile(r"[\p{P}\p{S}]")


def account_key(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def validate_account(value: str) -> str:
    if not isinstance(value, str) or not _ACCOUNT.fullmatch(value):
        raise AccountFormatError(field="external_id")
    return value


def validate_nickname(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise NicknameValidationError(field="user_name", reason="nicknameRequired")
    if _WHITESPACE.search(value):
        raise NicknameValidationError(field="user_name", reason="whitespace")
    if _INVISIBLE.search(value):
        raise NicknameValidationError(field="user_name", reason="nicknameInvisible")
    if len(value) > 32:
        raise NicknameValidationError(field="user_name", reason="nicknameLength")
    return value


def validate_nickname_change(original: str, proposed: str) -> bool:
    if proposed == original:
        return False
    validate_nickname(proposed)
    return True


def password_meets_policy(value: str | None) -> bool:
    return bool(
        isinstance(value, str)
        and 8 <= len(value) <= 128
        and regex.search(r"[A-Z]", value)
        and regex.search(r"[a-z]", value)
        and regex.search(r"[0-9]", value)
        and _SYMBOL.search(value)
    )
