"""Configuration contracts for assistant-bound E+ robots."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator


@dataclass(frozen=True, slots=True)
class AssistantSnapshot:
    assistant_id: str
    tenant_id: int
    is_deleted: bool
    is_online: bool


class EPlusBotConfigUpsert(BaseModel):
    bot_id: str = Field(min_length=1, max_length=128)
    connection_url: str = Field(min_length=1, max_length=1024)
    secret: str | None = Field(default=None, min_length=1)
    ca_pem: bytes | None = None
    remove_ca: bool = False
    media_hosts: list[str] = Field(default_factory=list)
    space_ids: list[int] = Field(default_factory=list)
    enabled: bool = False

    @field_validator("connection_url")
    @classmethod
    def validate_connection_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
            raise ValueError("connection_url must be an absolute ws:// or wss:// URL")
        return value

    @field_validator("media_hosts")
    @classmethod
    def normalize_media_hosts(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            host = value.strip().lower().rstrip(".")
            if not host or "://" in host or "/" in host:
                raise ValueError("media_hosts must contain host names only")
            normalized.append(host)
        return sorted(set(normalized))

    @field_validator("space_ids")
    @classmethod
    def normalize_space_ids(cls, values: list[int]) -> list[int]:
        if any(int(value) <= 0 for value in values):
            raise ValueError("space_ids must be positive integers")
        return sorted({int(value) for value in values})

    @model_validator(mode="after")
    def validate_ca_mutation(self):
        if self.ca_pem is not None and self.remove_ca:
            raise ValueError("ca_pem and remove_ca cannot be supplied together")
        return self


@dataclass(frozen=True, slots=True)
class EPlusBotConfigView:
    id: int
    assistant_id: str
    bot_id: str
    connection_url: str
    credential_version: int
    scope_version: int
    enabled: bool
    is_deleted: bool
    connection_status: str
    secret_configured: bool
    ca_configured: bool
    ca_sha256: str | None
    media_hosts: tuple[str, ...]
    space_ids: tuple[int, ...]
    insecure_transport: bool


@dataclass(frozen=True, slots=True)
class EPlusConnectionTarget:
    tenant_id: int
    bot_config_id: int
    assistant_id: str
    bot_id: str
    connection_url: str
    secret: str
    ca_object_key: str | None
    media_hosts: tuple[str, ...]
    credential_version: int
    scope_version: int
