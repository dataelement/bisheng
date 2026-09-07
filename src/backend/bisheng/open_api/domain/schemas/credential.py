"""Credential issue and masked-read schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bisheng.open_api.domain.models.api_credential import ApiCredential


def normalize_scopes(scopes: list[str]) -> list[str]:
    return list(dict.fromkeys(scope.strip() for scope in scopes if scope.strip()))


class DelegateScopeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: Literal["user", "department"]
    subject_id: int = Field(gt=0)


class KeyIssueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    delegate_scopes: list[DelegateScopeInput] = Field(default_factory=list)

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        return normalize_scopes(value)


class KeyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    scopes: list[str] | None = None
    expires_at: datetime | None = None
    delegate_scopes: list[DelegateScopeInput] | None = None

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else normalize_scopes(value)


class KeyItem(BaseModel):
    id: int
    subject_kind: str
    subject_id: int
    name: str
    key_mask: str
    scopes: list[str]
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    revoke_reason: str | None
    is_valid: bool
    created_by: int | None
    create_time: datetime | None
    delegate_scopes: list[DelegateScopeInput] = Field(default_factory=list)

    @classmethod
    def from_row(cls, row: ApiCredential, *, now: datetime | None = None) -> KeyItem:
        moment = now or datetime.now()
        return cls(
            id=row.id,
            subject_kind=row.subject_kind,
            subject_id=row.subject_id,
            name=row.name,
            key_mask=row.key_mask,
            scopes=list(row.scopes or []),
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            last_used_at=row.last_used_at,
            revoke_reason=row.revoke_reason,
            is_valid=row.is_valid_at(moment),
            created_by=row.created_by,
            create_time=row.create_time,
        )


class KeyIssuedResponse(KeyItem):
    plaintext: str = Field(description="Shown once and never stored")


class OpenApiScopeItem(BaseModel):
    code: str
    endpoints: list[str]


class OpenApiScopeCatalog(BaseModel):
    scopes: list[OpenApiScopeItem]
    open_platform_enabled: bool


class WhoamiResourceOwner(BaseModel):
    user_id: int


class WhoamiResponse(BaseModel):
    credential_id: int
    actor_kind: str
    actor_id: int
    actor_name: str
    tenant_id: int
    resource_owner: WhoamiResourceOwner | None
    authorization_subject_type: str
    authorization_subject_id: int
    effective_user_id: int | None
    mode: str
    scopes: list[str]
    key_mask: str
    expires_at: datetime | None
