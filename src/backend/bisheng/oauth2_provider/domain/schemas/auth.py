"""Pydantic schemas for OAuth 2.0 / OIDC authorization, consent, token and userinfo."""

from typing import Literal

from pydantic import BaseModel


class OAuth2ConsentDetails(BaseModel):
    request_id: str
    client_id: str
    client_name: str
    client_description: str | None = None
    scopes: list[str]
    redirect_uri: str
    state: str | None = None
    require_consent: bool = True
    expires_in: int


class OAuth2ConsentDecision(BaseModel):
    decision: Literal["approve", "deny"] = "approve"


class OAuth2ConsentDecisionResponse(BaseModel):
    redirect_uri: str


class OAuth2TokenResponse(BaseModel):
    token_type: Literal["Bearer"] = "Bearer"
    access_token: str
    expires_in: int
    scope: str
    refresh_token: str | None = None
    refresh_expires_in: int | None = None
    id_token: str | None = None
    session_id: str | None = None


class OAuth2UserInfoResponse(BaseModel):
    sub: str
    preferred_username: str | None = None
    name: str | None = None
    email: str | None = None
    tenant_id: str
    tenant_name: str
