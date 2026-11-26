"""Operator input for one WeKnora connection. Secrets are write-only."""

from pydantic import BaseModel, ConfigDict, Field


class ProviderInstanceWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(min_length=1, max_length=512)
    remote_scope_id: str = Field(min_length=1, max_length=32)
    api_key: str = Field(min_length=1, max_length=200)
    upload_signed_token_secret: str | None = Field(default=None, max_length=200)


class ProviderInstanceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(min_length=1, max_length=512)
    remote_scope_id: str = Field(min_length=1, max_length=32)
    api_key: str | None = Field(default=None, max_length=200)
    upload_signed_token_secret: str | None = Field(default=None, max_length=200)


class ProviderInstanceView(BaseModel):
    id: int
    endpoint: str
    remote_scope_id: str
    state: str
    capability_revision: int
    has_api_key: bool
    has_upload_signed_token_secret: bool
