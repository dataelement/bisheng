"""Strict Gateway management replies; invalid dependencies never become empty data."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator

from bisheng.dsh.domain.schemas.contracts import DshContract, NonnegativeInt, SubjectId


class SeatItem(DshContract):
    seat_id: str = Field(min_length=1)
    tenant_id: SubjectId
    user_id: SubjectId
    state: Literal["ASSIGNED", "REVOKED"]
    grant_version: Annotated[int, Field(strict=True, ge=1)]
    username: str
    display_name: str
    profile_version: NonnegativeInt | None
    profile_synced_at: str | None
    last_login_at: str | None
    last_seen_at: str | None
    active_session_count: NonnegativeInt
    login_state: Literal["HAS_SESSIONS", "NO_SESSIONS", "UNAVAILABLE"]
    created_at: str

    @field_validator("profile_synced_at", "last_login_at", "last_seen_at", "created_at")
    @classmethod
    def timestamp(cls, value):
        if value is not None and datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is None:
            raise ValueError("UTC offset is required")
        return value


class SessionItem(DshContract):
    session_id: str = Field(min_length=1)
    seat_id: str = Field(min_length=1)
    device_label: str | None
    client_version: str | None
    state: str = Field(min_length=1)
    expires_at: str
    last_seen_at: str | None
    created_at: str

    @field_validator("expires_at", "last_seen_at", "created_at")
    @classmethod
    def timestamp(cls, value):
        return SeatItem.timestamp(value)


class LicenseSnapshot(DshContract):
    status: Literal["active", "license_invalid", "license_expired", "dsh_disabled"]
    seat_limit: NonnegativeInt
    assigned: NonnegativeInt
    available: NonnegativeInt
    as_of: str
    license_id: str | None
    expires_at: str | None

    @field_validator("as_of", "expires_at")
    @classmethod
    def timestamp(cls, value):
        return SeatItem.timestamp(value)


class CommandResult(DshContract):
    operation_id: str = Field(min_length=1, max_length=36)
    status: Literal["UNKNOWN", "SUCCEEDED", "FAILED"]
    result_grant_version: Annotated[int, Field(strict=True, ge=1)] | None
    result_code: str | None


class AvailableModel(DshContract):
    id: Annotated[int, Field(strict=True, ge=1)]
    name: str
    is_root_shared: bool


class LastCallSnapshot(DshContract):
    request_id: str = Field(min_length=1, max_length=36)
    model_id: Annotated[int, Field(strict=True, ge=1)]
    status: Literal["RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "USAGE_UNKNOWN"]
    started_at: str | None
    finished_at: str | None
    total_tokens: NonnegativeInt | None
    projected_at: str | None

    @field_validator("started_at", "finished_at", "projected_at")
    @classmethod
    def timestamp(cls, value):
        return SeatItem.timestamp(value)
