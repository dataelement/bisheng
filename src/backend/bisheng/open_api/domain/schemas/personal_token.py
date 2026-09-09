"""Personal-token settings, issuance, and ledger contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from bisheng.open_api.domain.schemas.credential import KeyIssuedResponse, KeyItem


class PersonalTokenSettingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pat_enabled: bool
    pat_ttl_days: int = Field(ge=1, le=365)


class PersonalTokenSettingResponse(BaseModel):
    deployment_enabled: bool
    pat_enabled: bool
    effective_enabled: bool
    pat_ttl_days: int


class PersonalTokenStatus(BaseModel):
    enabled: bool
    token: KeyItem | None
    holder_is_admin: bool


class PersonalTokenIssued(KeyIssuedResponse):
    holder_is_admin: bool


class PersonalTokenLedgerItem(BaseModel):
    id: int
    holder_user_id: int
    holder_name: str
    key_mask: str
    scopes: list[str]
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    revoke_reason: str | None
    is_valid: bool
    holder_is_admin: bool
    create_time: datetime | None


class PersonalTokenLedgerPage(BaseModel):
    data: list[PersonalTokenLedgerItem]
    total: int


class PersonalTokenInstallPrompt(BaseModel):
    prompt: str
    skill_pack_url: str
