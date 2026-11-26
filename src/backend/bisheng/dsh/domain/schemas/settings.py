"""Editable instance settings, separate from deployment trust and License."""

import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bisheng.core.config.dsh import normalize_dsh_origin


class DshManagementSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = Field(
        default=True,
        description=(
            "Business access switch for Desktop login, Chat and Work tools; the deployment "
            "switch (BS_DSH_ENABLED) still gates the module."
        ),
    )
    download_url: str | None = Field(
        default="https://www.dshdesktop.com/zh/enterprise/",
        max_length=2048,
        description="Optional Desktop download HTTP(S) URL; null hides the download link.",
    )

    launch_url: str = Field(
        default="bisheng://login",
        max_length=2048,
        description="Desktop native protocol base URL; the browser appends the current platform server parameter.",
    )

    platform_public_url: str | None = Field(
        default=None,
        max_length=2048,
        description=(
            "Public HTTP(S) origin shared by Desktop login, Chat and Work tools; null keeps the "
            "deployment value (BS_DSH_PLATFORM_PUBLIC_URL)."
        ),
    )

    @field_validator("launch_url")
    @classmethod
    def validate_launch(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9+.-]*://[a-zA-Z0-9][a-zA-Z0-9._~/-]*", value):
            raise ValueError("Launch URL must be a native protocol base address without query or fragment")
        if urlsplit(value).scheme in {
            "http",
            "https",
            "ftp",
            "ftps",
            "file",
            "javascript",
            "data",
            "vbscript",
            "blob",
            "about",
        }:
            raise ValueError("Launch URL must use a native application protocol")
        return value

    @field_validator("download_url")
    @classmethod
    def validate_download(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "\\" in value
            or any(char.isspace() or ord(char) < 32 for char in value)
        ):
            raise ValueError("Download URL must be a credential-free HTTP(S) address")
        _ = parsed.port
        return value

    @field_validator("platform_public_url")
    @classmethod
    def validate_platform_public_url(cls, value: str | None) -> str | None:
        """A bare HTTP(S) origin (no path/credentials), or null for the deployment value."""
        if value is None or not value.strip():
            return None
        return normalize_dsh_origin(value.strip())
