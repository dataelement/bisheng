"""Request-scoped identity for anonymous publication calls."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PublicApiPrincipal(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: int
    operator_user_id: int
    operator_name: str
    resource_type: Literal["workflow", "assistant"]
    resource_id: str


current_public_api_principal: ContextVar[PublicApiPrincipal | None] = ContextVar(
    "current_public_api_principal",
    default=None,
)


def get_current_public_api_principal() -> PublicApiPrincipal | None:
    return current_public_api_principal.get()


def set_current_public_api_principal(principal: PublicApiPrincipal | None) -> Token:
    return current_public_api_principal.set(principal)


def reset_current_public_api_principal(token: Token) -> None:
    current_public_api_principal.reset(token)


__all__ = [
    "PublicApiPrincipal",
    "get_current_public_api_principal",
    "reset_current_public_api_principal",
    "set_current_public_api_principal",
]
