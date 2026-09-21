"""Editable instance settings, separate from deployment trust and License."""

import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DshManagementSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = Field(default=False, description="Allow new DSH logins and model requests across the instance.")
    download_url: str | None = Field(
        default=None, max_length=2048, description="Optional Desktop download HTTP(S) URL."
    )

    launch_url: str = Field(
        default="dsh-desktop://login",
        max_length=2048,
        description="Desktop native protocol base URL; the browser appends the current platform server parameter.",
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
