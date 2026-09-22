"""Strict Gateway management replies; invalid dependencies never become empty data."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

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
    source: Literal["builtin", "signed"] | None = None
    signed_license_status: Literal["active", "not_granted", "license_invalid", "license_expired"] | None = None
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


class ModelAccessUser(DshContract):
    user_id: Annotated[int, Field(strict=True, ge=1)]
    user_name: str
    version: Annotated[int, Field(strict=True, ge=0)]
    enabled: bool
    monthly_token_limit: NonnegativeInt
    pending_operation_id: str | None


class UserPermissionDepartment(DshContract):
    id: Annotated[int, Field(strict=True, ge=1)]
    name: str = Field(min_length=1)
    is_primary: bool


class UserPermissionRole(DshContract):
    id: Annotated[int, Field(strict=True, ge=1)]
    name: str = Field(min_length=1)


class UserPermissionSource(DshContract):
    subject_type: Literal["DEPARTMENT", "ROLE", "USER"]
    subject_id: Annotated[int, Field(strict=True, ge=1)]
    name: str = Field(min_length=1)
    monthly_token_limit: NonnegativeInt
    inherited: bool
    winning: bool


class ModelUserPermission(DshContract):
    access_status: (
        Literal[
            "UNAUTHORIZED",
            "AUTHORIZED",
            "PENDING_LOGIN",
            "SEAT_LIMIT_REACHED",
            "REVOKED",
            "LICENSE_UNAVAILABLE",
            "UNAVAILABLE",
        ]
        | None
    ) = None
    user_id: Annotated[int, Field(strict=True, ge=1)]
    user_name: str = Field(min_length=1)
    direct_version: NonnegativeInt
    direct_enabled: bool
    direct_monthly_token_limit: NonnegativeInt
    direct_pending_operation_id: str | None
    departments: list[UserPermissionDepartment]
    roles: list[UserPermissionRole]
    authorized: bool
    monthly_token_limit: NonnegativeInt
    sources: list[UserPermissionSource]
    department_match: Literal["DIRECT", "DESCENDANT"] | None

    @model_validator(mode="after")
    def consistent_effective_result(self):
        if self.authorized != (bool(self.sources) and self.monthly_token_limit > 0):
            raise ValueError("Authorization must match the effective sources")
        candidates = (
            [source for source in self.sources if source.subject_type == "USER"]
            if self.direct_enabled
            else self.sources
        )
        expected = (
            self.direct_monthly_token_limit
            if self.direct_enabled
            else max((source.monthly_token_limit for source in candidates), default=0)
        )
        if self.monthly_token_limit != expected:
            raise ValueError("Effective quota must follow personal override or inherited quota")
        if any(
            source.winning != (source in candidates and source.monthly_token_limit == expected)
            for source in self.sources
        ):
            raise ValueError("Quota source must match personal precedence")
        if self.sources and not any(source.winning for source in self.sources):
            raise ValueError("An effective source must win the quota calculation")
        return self


class ModelUserPermissionPage(DshContract):
    tenant_id: Annotated[int, Field(strict=True, ge=1)]
    model: AvailableModel
    items: list[ModelUserPermission]
    next_cursor: str | None
    has_more: bool

    @model_validator(mode="after")
    def consistent_cursor(self):
        if self.has_more != bool(self.next_cursor):
            raise ValueError("A paged result needs a cursor exactly when more rows exist")
        return self


class SubjectPolicyInput(DshContract):
    expected_version: NonnegativeInt
    enabled: bool
    monthly_token_limit: NonnegativeInt

    @model_validator(mode="after")
    def zero_quota_disables_access(self):
        if self.monthly_token_limit == 0:
            self.enabled = False
        return self


class SubjectPolicyState(DshContract):
    subject_type: Literal["DEPARTMENT", "ROLE"]
    subject_id: Annotated[int, Field(strict=True, ge=1)]
    name: str = Field(min_length=1)
    version: NonnegativeInt
    enabled: bool
    monthly_token_limit: NonnegativeInt


class DepartmentPolicyState(SubjectPolicyState):
    subject_type: Literal["DEPARTMENT"]
    parent_id: Annotated[int, Field(strict=True, ge=1)] | None
    depth: NonnegativeInt


class RolePolicyState(SubjectPolicyState):
    subject_type: Literal["ROLE"]
    role_type: Literal["global", "tenant"]
    department_id: Annotated[int, Field(strict=True, ge=1)] | None


class SubjectPolicyInventory(DshContract):
    tenant_id: Annotated[int, Field(strict=True, ge=1)]
    model_id: Annotated[int, Field(strict=True, ge=1)]
    departments: list[DepartmentPolicyState]
    roles: list[RolePolicyState]


class SubjectPolicyUpdateResult(DshContract):
    subject_type: Literal["DEPARTMENT", "ROLE"]
    subject_id: Annotated[int, Field(strict=True, ge=1)]
    model_id: Annotated[int, Field(strict=True, ge=1)]
    name: str = Field(min_length=1)
    version: Annotated[int, Field(strict=True, ge=1)]
    enabled: bool
    monthly_token_limit: NonnegativeInt


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


class UsageMetrics(DshContract):
    message_count: NonnegativeInt
    qa_count: NonnegativeInt
    failed_count: NonnegativeInt
    cancelled_count: NonnegativeInt
    running_count: NonnegativeInt
    usage_unknown_count: NonnegativeInt
    recorded_usage_count: NonnegativeInt
    missing_usage_count: NonnegativeInt
    input_tokens: NonnegativeInt | None
    output_tokens: NonnegativeInt | None
    total_tokens: NonnegativeInt | None

    @model_validator(mode="after")
    def consistent_counts_and_tokens(self):
        if (
            self.qa_count + self.failed_count + self.cancelled_count + self.running_count + self.usage_unknown_count
            != self.message_count
        ):
            raise ValueError("Message status counts must equal the total")
        if self.recorded_usage_count + self.missing_usage_count != self.message_count:
            raise ValueError("Usage evidence counts must equal the total")
        tokens = (self.input_tokens, self.output_tokens, self.total_tokens)
        usage_is_unknown = self.message_count > 0 and self.recorded_usage_count == 0
        if usage_is_unknown:
            if any(value is not None for value in tokens):
                raise ValueError("Token totals remain unknown without recorded usage")
        elif any(value is None for value in tokens) or self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("Recorded token totals must be complete and consistent")
        return self


class UsageTimeBucket(UsageMetrics):
    start_at: str
    end_at: str

    @field_validator("start_at", "end_at")
    @classmethod
    def timestamp(cls, value):
        return SeatItem.timestamp(value)


class UsageTimeSummary(DshContract):
    start_at: str
    end_at: str
    timezone: Literal["Asia/Shanghai"]
    granularity: Literal["hour", "day"]
    totals: UsageMetrics
    points: list[UsageTimeBucket]

    @field_validator("start_at", "end_at")
    @classmethod
    def timestamp(cls, value):
        return SeatItem.timestamp(value)


class UsageOverviewUser(DshContract):
    user_id: Annotated[int, Field(strict=True, ge=1)]
    user_name: str = Field(min_length=1)
    department_id: Annotated[int, Field(strict=True, ge=1)] | None
    department_name: str | None
    metrics: UsageMetrics


class UsageOverviewPage(DshContract):
    tenant_id: Annotated[int, Field(strict=True, ge=1)]
    start_at: str
    end_at: str
    timezone: Literal["Asia/Shanghai"]
    department_id: Annotated[int, Field(strict=True, ge=1)] | None
    totals: UsageMetrics
    summary: UsageTimeSummary | None = None
    items: list[UsageOverviewUser]
    next_cursor: str | None
    has_more: bool

    @field_validator("start_at", "end_at")
    @classmethod
    def timestamp(cls, value):
        return SeatItem.timestamp(value)

    @model_validator(mode="after")
    def consistent_cursor(self):
        if self.has_more != bool(self.next_cursor):
            raise ValueError("A paged result needs a cursor exactly when more rows exist")
        return self
