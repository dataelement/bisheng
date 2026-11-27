"""Typed value received only from the authoritative first-party session seam."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PLATFORM_SESSION_TOKEN_TYPE = "urn:bisheng:params:oauth:token-type:platform-session"


class OAuth2PlatformSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field(strict=True, gt=0)
    tenant_id: int = Field(strict=True, gt=0)
    client_id: Literal["bisheng-web", "bisheng-mobile"]
    expires_at: int = Field(strict=True, gt=0)
    session_expires_at: int = Field(strict=True, gt=0)
    reference: dict
