"""Immutable identities propagated through Open API execution paths."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Literal

from pydantic import BaseModel, ConfigDict


class OpenApiPrincipal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    credential_id: int
    actor_kind: Literal["service_account", "natural_person"]
    actor_id: int
    actor_name: str
    tenant_id: int
    resource_owner_user_id: int | None
    scopes: frozenset[str]
    mode: Literal["S", "D"] = "S"
    authorization_subject_type: Literal["service_account", "user"]
    authorization_subject_id: int
    effective_user_id: int | None
    on_behalf_of_user_id: int | None = None
    end_user_id: str | None = None

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


class OpenApiExecutionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: int
    actor_kind: Literal["service_account", "natural_person"]
    actor_id: int
    authorization_subject_type: Literal["service_account", "user"]
    authorization_subject_id: int
    resource_owner_user_id: int | None
    effective_user_id: int | None
    mode: Literal["S", "D"]
    credential_id: int | None
    trace_id: str
    channel: Literal["open_api_v2", "public_v3"]

    @classmethod
    def from_principal(cls, principal: OpenApiPrincipal, *, trace_id: str) -> OpenApiExecutionSnapshot:
        return cls(
            tenant_id=principal.tenant_id,
            actor_kind=principal.actor_kind,
            actor_id=principal.actor_id,
            authorization_subject_type=principal.authorization_subject_type,
            authorization_subject_id=principal.authorization_subject_id,
            resource_owner_user_id=principal.resource_owner_user_id,
            effective_user_id=principal.effective_user_id,
            mode=principal.mode,
            credential_id=principal.credential_id,
            trace_id=trace_id,
            channel="open_api_v2",
        )


current_open_api_principal: ContextVar[OpenApiPrincipal | None] = ContextVar("current_open_api_principal", default=None)


def get_current_open_api_principal() -> OpenApiPrincipal | None:
    return current_open_api_principal.get()


def set_current_open_api_principal(principal: OpenApiPrincipal | None) -> Token:
    return current_open_api_principal.set(principal)


def reset_current_open_api_principal(token: Token) -> None:
    current_open_api_principal.reset(token)
