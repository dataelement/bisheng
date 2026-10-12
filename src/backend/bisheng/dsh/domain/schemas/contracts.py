"""DSH domain DTOs, independent of HTTP, ORM and application startup."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SubjectId = Annotated[str, Field(strict=True, pattern=r"^[0-9]+$")]
NonnegativeInt = Annotated[int, Field(strict=True, ge=0, le=9223372036854775807)]
DisplayText = Annotated[str, Field(strict=True, min_length=1)]


class DshContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DshUserDisplay(DshContract):
    id: SubjectId
    username: DisplayText
    display_name: DisplayText


class DshTenantDisplay(DshContract):
    id: SubjectId
    name: DisplayText


class DshIdentitySnapshot(DshContract):
    tenant_id: SubjectId
    user_id: SubjectId
    active: bool
    reason: str | None = None
    user: DshUserDisplay | None = None
    tenant: DshTenantDisplay | None = None
    profile_version: NonnegativeInt | None = None

    @model_validator(mode="after")
    def check_subjects(self):
        if self.active:
            if self.reason is not None or self.user is None or self.tenant is None or self.profile_version is None:
                raise ValueError("Active identity requires current display data and profile version")
            if self.user.id != self.user_id or self.tenant.id != self.tenant_id:
                raise ValueError("Display subjects must match the authenticated subjects")
        elif not self.reason or self.user is not None or self.tenant is not None or self.profile_version is not None:
            raise ValueError("Inactive identity requires a reason and must omit display data")
        return self


class DshTokenTotals(DshContract):
    input_tokens: NonnegativeInt | None = None
    output_tokens: NonnegativeInt | None = None
    total_tokens: NonnegativeInt | None = None

    @model_validator(mode="after")
    def check_reliable_usage(self):
        values = (self.input_tokens, self.output_tokens, self.total_tokens)
        if all(value is None for value in values):
            return self
        if any(value is None for value in values) or self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("Usage must be entirely unknown or a complete consistent measurement")
        return self


class DshTokenUsage(DshTokenTotals):
    cache_read_tokens: NonnegativeInt | None = None
    cache_creation_tokens: NonnegativeInt | None = None


class DshOperationAction(StrEnum):
    REVOKE = "REVOKE"
    REASSIGN = "REASSIGN"
    UPDATE_POLICY = "UPDATE_POLICY"
    RECONCILE_USAGE = "RECONCILE_USAGE"
    SYNC_PROFILE = "SYNC_PROFILE"


class DshOperationStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class DshPolicySyncState(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    FROZEN = "FROZEN"


class DshUserPolicyInput(DshContract):
    operation_id: str = Field(min_length=1, max_length=36)
    expected_version: NonnegativeInt
    monthly_token_limit: NonnegativeInt
    enabled: bool


class DshErrorDetail(DshContract):
    message: str
    type: str
    code: str


class DshErrorResponse(DshContract):
    error: DshErrorDetail
    request_id: str


class DshDisabledConfig(DshContract):
    enabled: Literal[False] = False


class DshEnabledConfig(DshContract):
    enabled: Literal[True] = True
    client_id: Literal["dsh-desktop"] = "dsh-desktop"
    contract_version: Literal["0.5.0"] = "0.5.0"
