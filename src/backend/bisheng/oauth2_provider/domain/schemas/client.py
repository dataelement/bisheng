"""Pydantic schemas for OAuth 2.0 / OIDC client administration."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from bisheng.oauth2_provider.domain.models.client import DEFAULT_ALLOWED_SCOPES, DEFAULT_GRANT_TYPES


class OAuth2ClientCreate(BaseModel):
    client_id: str | None = Field(default=None, min_length=3, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    client_name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    client_type: Literal["public", "confidential"] = "confidential"
    redirect_uris: list[str] = Field(min_length=1, max_length=32)
    allow_loopback_port: bool = False
    allowed_scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_ALLOWED_SCOPES))
    grant_types: list[str] = Field(default_factory=lambda: list(DEFAULT_GRANT_TYPES))
    require_pkce: bool = True
    require_consent: bool = True
    enabled: bool = True
    access_token_ttl: int = Field(default=3600, ge=60, le=86400)
    refresh_token_ttl: int = Field(default=1209600, ge=300, le=7776000)


class OAuth2ClientUpdate(BaseModel):
    client_name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    redirect_uris: list[str] | None = Field(default=None, min_length=1, max_length=32)
    allow_loopback_port: bool | None = None
    allowed_scopes: list[str] | None = None
    grant_types: list[str] | None = None
    require_pkce: bool | None = None
    require_consent: bool | None = None
    enabled: bool | None = None
    access_token_ttl: int | None = Field(default=None, ge=60, le=86400)
    refresh_token_ttl: int | None = Field(default=None, ge=300, le=7776000)


class OAuth2ClientResponse(BaseModel):
    id: int
    client_id: str
    client_name: str
    description: str | None = None
    client_type: Literal["public", "confidential"]
    has_secret: bool = False
    redirect_uris: list[str]
    allow_loopback_port: bool
    allowed_scopes: list[str]
    grant_types: list[str]
    require_pkce: bool
    require_consent: bool
    enabled: bool
    is_builtin: bool
    access_token_ttl: int
    refresh_token_ttl: int
    create_time: datetime | None = None
    update_time: datetime | None = None


class OAuth2ClientSecretResponse(BaseModel):
    client: OAuth2ClientResponse
    client_secret: str | None = None
