"""Editable instance settings, separate from deployment trust and License."""

from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DshManagementSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = Field(default=False, description="Allow new DSH logins and model requests across the instance.")
    download_url: str | None = Field(
        default=None, max_length=2048, description="Optional Desktop download HTTP(S) URL."
    )

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
