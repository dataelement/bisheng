"""Operator-owned WeKnora connection for a specific control-plane instance."""

import re
from ipaddress import IPv4Address, IPv4Network
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, SecretStr, field_validator, model_validator


class WeKnoraSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    endpoint: str
    api_key: SecretStr | None = Field(default=None, repr=False, exclude=True)
    tenant_id: PositiveInt | None = None
    instance_id: PositiveInt | None = None
    remote_scope_id: str | None = None
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    connect_timeout_seconds: float = Field(default=5, gt=0, le=60)
    deployment: dict | None = Field(default=None, repr=False, exclude=True)

    @field_validator("endpoint")
    @classmethod
    def normalize_endpoint(cls, value: str) -> str:
        # Only accept ordinary reverse-proxy paths; credentials never belong in a URL.
        if not re.fullmatch(r"https?://[A-Za-z0-9.-]+(?::[1-9][0-9]{0,4})?(?:/[A-Za-z0-9._~-]+)*/?", value):
            raise ValueError("Expected an absolute WeKnora endpoint without credentials or URL parameters")
        url = urlsplit(value)
        if not url.hostname or url.port == 0 or any(s in {".", ".."} for s in url.path.split("/")):
            raise ValueError("Invalid WeKnora endpoint")
        base = value.removesuffix("/").removesuffix("/api/v1")
        if url.scheme == "http":
            host = IPv4Address(url.hostname)
            if base != f"http://{url.netloc}" or not any(
                host in IPv4Network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
            ):
                raise ValueError("Cleartext WeKnora connections require one private LAN origin")
        return base

    @model_validator(mode="after")
    def require_binding(self):
        if self.api_key and self.api_key.get_secret_value() or self.deployment is not None:
            if (
                not self.tenant_id
                or not self.instance_id
                or not self.remote_scope_id
                or not re.fullmatch(r"[0-9]+", self.remote_scope_id)
            ):
                raise ValueError("Set tenant_id, instance_id and remote_scope_id for the WeKnora connection")
        return self
