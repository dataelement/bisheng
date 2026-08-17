"""API key (``bs-sak-``) DTOs (F049 design §4.2).

``KeyIssuedResponse`` is the **only** model that ever carries ``plaintext``
(AC-02); every other surface renders ``key_mask`` = ``bs-sak-********`` + last4.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from bisheng.open_api.domain.models.api_credential import (
    KEY_PREFIX,
    ApiCredential,
    mask_key,
)


def _normalize_scopes(scopes: list[str]) -> list[str]:
    """Trim, drop empties, de-duplicate preserving order. Existence is checked by the service (26025 / 26023 / 26024)."""
    seen: dict[str, None] = {}
    for scope in scopes:
        code = scope.strip()
        if code:
            seen.setdefault(code, None)
    return list(seen)


class KeyIssueRequest(BaseModel):
    """``POST /api/v1/service-accounts/{id}/keys``. Scopes default to none (AC-06)."""

    name: str = Field(..., min_length=1, max_length=128)
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = Field(default=None, description="Absolute expiry; null = never expires")

    @field_validator("scopes")
    @classmethod
    def _norm_scopes(cls, value: list[str]) -> list[str]:
        return _normalize_scopes(value)


class KeyUpdateRequest(BaseModel):
    """``PATCH /api/v1/service-accounts/{id}/keys/{key_id}`` - name / scopes / expiry.

    Absent fields stay unchanged; ``expires_at: null`` explicitly clears the
    expiry (distinguish via ``model_fields_set``). Changes take effect on the
    existing key immediately (AC-08, cache actively invalidated).
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)
    scopes: list[str] | None = None
    expires_at: datetime | None = None

    @field_validator("scopes")
    @classmethod
    def _norm_scopes(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _normalize_scopes(value)


class KeyItem(BaseModel):
    """Masked view of one key - list / detail / audit metadata."""

    id: int
    name: str
    key_mask: str = Field(description="bs-sak-******** + last four characters")
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    revoke_reason: str | None = None
    last_used_at: datetime | None = None
    is_valid: bool = Field(description="revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now)")
    created_by: int | None = None
    creator_name: str | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None

    @classmethod
    def from_row(cls, row: ApiCredential, *, now: datetime, creator_name: str | None = None) -> KeyItem:
        return cls(
            id=row.id,
            name=row.name,
            key_mask=mask_key(row.last4, row.key_prefix),
            scopes=list(row.scopes or []),
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            revoke_reason=row.revoke_reason,
            last_used_at=row.last_used_at,
            is_valid=row.is_valid_at(now),
            created_by=row.created_by,
            creator_name=creator_name,
            create_time=row.create_time,
            update_time=row.update_time,
        )


class KeyIssuedResponse(KeyItem):
    """Issue response - the single place the plaintext appears (AC-02)."""

    plaintext: str = Field(description=f"{KEY_PREFIX}<43 urlsafe chars>; shown once, never stored")


class WhoamiServiceAccount(BaseModel):
    id: int
    name: str


class WhoamiResponse(BaseModel):
    """``GET /api/v2/auth/whoami`` - credential check only, no scope check (F053 login probe)."""

    subject_kind: str
    service_account: WhoamiServiceAccount | None = None
    tenant_id: int
    scopes: list[str] = Field(default_factory=list)
    key_mask: str
    expires_at: datetime | None = None


class OpenApiScopeEndpoint(BaseModel):
    """One ``(method, path)`` pair a scope unlocks - the issue form's hover text (AC-44)."""

    method: str = Field(description="HTTP verb, or 'WS' for a WebSocket route")
    path: str


class OpenApiScopeItem(BaseModel):
    """``GET /api/v1/service-accounts/scopes`` row - one grantable permission bit.

    Copy is *not* included: only i18n keys, resolved by the front end from the
    ``serviceAccount`` namespace (design §4.3 "no UI copy in the backend").
    """

    code: str
    group: str
    label_key: str
    desc_key: str
    endpoints: list[OpenApiScopeEndpoint] = Field(default_factory=list)
    requires_open_platform: bool = False
    # Set when the bit is issuable but its endpoints ship in a later version
    # (``chat:invoke``); the form shows this note instead of an endpoint list.
    pending_note_key: str | None = None
    # Extra warnings the form must render prominently (AC-13).
    hint_keys: list[str] = Field(default_factory=list)

    @classmethod
    def from_registry(cls, scope) -> OpenApiScopeItem:
        return cls(
            code=scope.code,
            group=scope.group,
            label_key=scope.label_key,
            desc_key=scope.desc_key,
            endpoints=[OpenApiScopeEndpoint(method=method, path=path) for method, path in scope.endpoints],
            requires_open_platform=scope.requires_open_platform,
            pending_note_key=scope.pending_note_key,
            hint_keys=list(scope.hint_keys),
        )


class OpenApiScopeCatalog(BaseModel):
    """The scope清单 as one deployment shows it (AC-13 / AC-49)."""

    scopes: list[OpenApiScopeItem]
    open_platform_enabled: bool
