"""Token exchange protocol constants and policy schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

EXCHANGE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"
IDENTITY_SCOPES = frozenset({"openid", "profile", "email"})


class OAuth2ExchangePolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed_scopes: list[str] = Field(min_length=1, max_length=3)
    enabled: bool = True


class OAuth2ExchangePolicyResponse(BaseModel):
    source_client_id: str
    target_client_id: str
    allowed_scopes: list[str]
    enabled: bool
    created_by: int
    updated_by: int
    create_time: datetime | None = None
    update_time: datetime | None = None
