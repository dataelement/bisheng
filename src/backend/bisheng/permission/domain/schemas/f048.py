"""F048 permission Catalog, Grant, and action contracts.

Request models are deliberately separate from server-owned DTOs. In
particular, HTTP callers cannot provide tenant scope, assignment provenance,
protection flags, derived levels, or resource business state.
"""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    model_validator,
)

_VERIFIED_TARGET_CONTEXT_KEY = "permission_business_target_verification"
_VERIFIED_TARGET_TOKEN = object()


class PermissionActionLevel(IntEnum):
    """The four ordered Catalog action levels."""

    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3
    LEVEL_4 = 4


class PermissionModelKind(StrEnum):
    STANDARD = "STANDARD"
    CUSTOM = "CUSTOM"


class PermissionConfigScope(StrEnum):
    PLATFORM = "PLATFORM"


class PermissionMode(StrEnum):
    INHERIT = "INHERIT"
    CUSTOM = "CUSTOM"


class GrantMutationOperation(StrEnum):
    ADD = "ADD"
    MOVE = "MOVE"
    REMOVE = "REMOVE"


class PermissionTupleAction(StrEnum):
    WRITE = "WRITE"
    DELETE = "DELETE"


class CatalogChangeType(StrEnum):
    ASSIGN_ACTION_LEVEL = "ASSIGN_ACTION_LEVEL"
    SET_ACTION_ACTIVE = "SET_ACTION_ACTIVE"
    CREATE_MODEL = "CREATE_MODEL"
    UPDATE_MODEL = "UPDATE_MODEL"
    SET_MODEL_ACTIVE = "SET_MODEL_ACTIVE"
    DELETE_MODEL = "DELETE_MODEL"
    SET_ALLOW_SAME_LEVEL = "SET_ALLOW_SAME_LEVEL"


class VisibilityEnumerationStatus(StrEnum):
    """Terminal states that are safe to hand to a business list caller."""

    NORMAL = "NORMAL"


class StrictRequestModel(BaseModel):
    """Base class that rejects undeclared, server-owned request fields."""

    model_config = ConfigDict(extra="forbid")


class VerifiedPermissionTarget(BaseModel):
    """Resource scope verified by its owning business Service.

    This DTO is internal. Permission code may trust its canonical tenant,
    parent, and optimistic resource version, but must not query business tables
    to recreate or enrich them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: int = Field(gt=0)
    resource_type: str = Field(min_length=1, max_length=64)
    resource_id: str = Field(min_length=1, max_length=64)
    resource_version: int = Field(ge=0)
    parent_type: str | None = Field(default=None, min_length=1, max_length=64)
    parent_id: str | None = Field(default=None, min_length=1, max_length=64)
    context_version: str = Field(min_length=1, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def require_business_service_verification(
        cls,
        value: Any,
        info: ValidationInfo,
    ) -> Any:
        context = info.context or {}
        if context.get(_VERIFIED_TARGET_CONTEXT_KEY) is not _VERIFIED_TARGET_TOKEN:
            raise ValueError("VerifiedPermissionTarget must be created by a business Service")
        return value

    @model_validator(mode="after")
    def validate_parent_pair(self) -> VerifiedPermissionTarget:
        if (self.parent_type is None) != (self.parent_id is None):
            raise ValueError("parent_type and parent_id must be provided together")
        return self

    @classmethod
    def from_business_service(
        cls,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str,
        resource_version: int,
        context_version: str,
        parent_type: str | None = None,
        parent_id: str | None = None,
    ) -> VerifiedPermissionTarget:
        """Build the internal DTO after the owning Service verified its row."""

        return cls.model_validate(
            {
                "tenant_id": tenant_id,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "resource_version": resource_version,
                "parent_type": parent_type,
                "parent_id": parent_id,
                "context_version": context_version,
            },
            context={
                _VERIFIED_TARGET_CONTEXT_KEY: _VERIFIED_TARGET_TOKEN,
            },
        )


class PermissionActionDTO(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    level: PermissionActionLevel | None = None
    active: bool
    sort_order: int = 0
    resource_types: tuple[str, ...] = ()


class PermissionModelDTO(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    kind: PermissionModelKind
    config_scope: PermissionConfigScope = PermissionConfigScope.PLATFORM
    derived_level: PermissionActionLevel | None = None
    active: bool
    allow_same_level: bool
    action_codes: tuple[str, ...] = ()
    version: int


class CatalogReleaseDTO(BaseModel):
    id: int
    release_key: str
    version: int
    status: str
    authorization_model_id: str
    checksum: str = Field(min_length=64, max_length=64)
    actions: tuple[PermissionActionDTO, ...] = ()
    models: tuple[PermissionModelDTO, ...] = ()
    published_at: datetime | None = None


class CatalogChangeRequest(StrictRequestModel):
    type: CatalogChangeType
    action_code: str | None = Field(default=None, max_length=64)
    level: PermissionActionLevel | None = None
    model_key: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    action_codes: tuple[str, ...] | None = None
    active: bool | None = None
    allow_same_level: bool | None = None


class CatalogDraftRequest(StrictRequestModel):
    idempotency_key: str = Field(min_length=1, max_length=64)
    base_release_id: int = Field(gt=0)
    # A draft carries the whole edit batch. One change per draft forced the UI to
    # open a fresh draft off the CURRENT release for every edit, so publishing
    # applied only the last one and silently dropped the rest.
    changes: tuple[CatalogChangeRequest, ...] = Field(min_length=1, max_length=50)


class CatalogActionChangeDTO(BaseModel):
    action_code: str
    action_name: str
    before_level: PermissionActionLevel | None = None
    after_level: PermissionActionLevel | None = None
    before_active: bool
    after_active: bool


class CatalogModelChangeDTO(BaseModel):
    model_key: str
    model_name: str
    kind: Literal["STANDARD", "CUSTOM"]
    before_level: PermissionActionLevel | None = None
    after_level: PermissionActionLevel | None = None
    added_action_codes: tuple[str, ...] = ()
    removed_action_codes: tuple[str, ...] = ()
    affected_assignee_count: int = Field(ge=0)


class CatalogImpactDTO(BaseModel):
    checksum: str = Field(min_length=64, max_length=64)
    resource_count: int = Field(ge=0)
    grant_count: int = Field(ge=0)
    assignee_count: int = Field(ge=0)
    expansion_count: int = Field(ge=0)
    revocation_count: int = Field(ge=0)
    action_changes: tuple[CatalogActionChangeDTO, ...] = ()
    model_changes: tuple[CatalogModelChangeDTO, ...] = ()
    blockers: tuple[str, ...] = ()
    expires_at: datetime


class CatalogPublishRequest(StrictRequestModel):
    expected_current_release_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=64)
    confirmed: Literal[True]


class GrantSubjectInput(StrictRequestModel):
    type: Literal["user", "department", "user_group"]
    id: str = Field(min_length=1, max_length=64)
    userset_relation: str | None = Field(default=None, max_length=64)
    include_children: bool = False

    @model_validator(mode="after")
    def validate_subject_options(self) -> GrantSubjectInput:
        if self.type == "user" and (self.userset_relation or self.include_children):
            raise ValueError("direct users cannot use userset options")
        if self.include_children and self.type != "department":
            raise ValueError("include_children is only valid for departments")
        return self


class GrantMutationChange(StrictRequestModel):
    op: GrantMutationOperation
    model_key: str | None = Field(default=None, max_length=64)
    subject: GrantSubjectInput | None = None
    # Carried as a decimal string: row ids are 60-62 bit, past the 2^53 that a
    # JSON number survives in a browser, and a rounded id matches no assignee.
    assignee_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,19}$")
    expected_assignee_version: int | None = Field(default=None, ge=0)
    target_model_key: str | None = Field(default=None, max_length=64)

    @property
    def assignee_row_id(self) -> int | None:
        return None if self.assignee_id is None else int(self.assignee_id)

    @model_validator(mode="after")
    def validate_operation_shape(self) -> GrantMutationChange:
        if self.op == GrantMutationOperation.ADD:
            if not self.model_key or self.subject is None:
                raise ValueError("ADD requires model_key and subject")
            if (
                self.assignee_id is not None
                or self.expected_assignee_version is not None
                or self.target_model_key is not None
            ):
                raise ValueError("ADD cannot address an existing assignee")
        elif self.op == GrantMutationOperation.MOVE:
            if self.assignee_id is None or self.expected_assignee_version is None or not self.target_model_key:
                raise ValueError("MOVE requires assignee_id, expected_assignee_version, and target_model_key")
            if self.model_key is not None or self.subject is not None:
                raise ValueError("MOVE cannot create a subject")
        else:
            if self.assignee_id is None or self.expected_assignee_version is None:
                raise ValueError("REMOVE requires assignee_id and expected_assignee_version")
            if self.model_key is not None or self.subject is not None or self.target_model_key is not None:
                raise ValueError("REMOVE only accepts the assignee identity and version")
        return self


class GrantMutationRequest(StrictRequestModel):
    idempotency_key: str = Field(min_length=1, max_length=64)
    expected_resource_version: int = Field(ge=0)
    expected_catalog_release_id: int = Field(gt=0)
    changes: tuple[GrantMutationChange, ...] = Field(min_length=1, max_length=50)


class GrantSubjectDTO(BaseModel):
    type: str
    id: str
    name: str | None = None


class GrantModelDTO(BaseModel):
    key: str
    name: str
    level: PermissionActionLevel | None
    active: bool


class GrantSourceDTO(BaseModel):
    type: str
    include_children: bool = False


class GrantAssigneeDTO(BaseModel):
    assignee_id: str
    assignee_version: int
    subject: GrantSubjectDTO
    model: GrantModelDTO
    source: GrantSourceDTO
    scope: Literal["LOCAL", "INHERITED"]
    inherited_from: str | None = None
    inherited_from_name: str | None = None
    protected: bool
    editable: bool


class PermissionCursor(BaseModel):
    """Decoded server cursor bound to one immutable roster snapshot."""

    tenant_id: int
    resource_type: str
    resource_id: str
    catalog_release_id: int
    resource_version: int
    after_id: int = 0


class GrantCursorPageDTO(BaseModel):
    items: tuple[GrantAssigneeDTO, ...] = ()
    next_cursor: str | None = None


class ResourcePermissionModeDTO(BaseModel):
    mode: PermissionMode
    parent_type: str | None = None
    parent_id: str | None = None
    resource_version: int
    projection_state: str


class PermissionModeDraftRequest(StrictRequestModel):
    target_mode: PermissionMode
    expected_resource_version: int = Field(ge=0)
    expected_catalog_release_id: int = Field(gt=0)


class PermissionModeDraftDTO(BaseModel):
    draft_id: str
    target_mode: PermissionMode
    impact_checksum: str = Field(min_length=64, max_length=64)
    affected_assignees: int = Field(ge=0)
    expires_at: datetime


class PermissionModeApplyRequest(StrictRequestModel):
    idempotency_key: str = Field(min_length=1, max_length=64)
    expected_resource_version: int = Field(ge=0)
    expected_catalog_release_id: int = Field(gt=0)
    confirmed: Literal[True]


class PermissionMutation(BaseModel):
    """Canonical internal tuple delta emitted by permission policies."""

    action: PermissionTupleAction
    fga_user: str = Field(min_length=1, max_length=256)
    relation: str = Field(min_length=1, max_length=64)
    fga_object: str = Field(min_length=1, max_length=256)


class VisibleObjectEnumerationRequest(BaseModel):
    """Bounded internal request for one complete visible-object enumeration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: int = Field(gt=0)
    resource_type: str = Field(min_length=1, max_length=64)
    fga_user: str = Field(min_length=1, max_length=256)
    max_results: int = Field(gt=0, le=5_000)


class VisibleObjectEnumerationResult(BaseModel):
    """Immutable result emitted only after the upstream stream ends normally."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_type: str = Field(min_length=1, max_length=64)
    object_ids: tuple[str, ...] = ()
    max_results: int = Field(gt=0, le=5_000)
    status: VisibilityEnumerationStatus

    @model_validator(mode="after")
    def validate_complete_set(self) -> VisibleObjectEnumerationResult:
        if self.status is not VisibilityEnumerationStatus.NORMAL:
            raise ValueError("only normally completed enumeration results may be delivered")
        if len(self.object_ids) > self.max_results:
            raise ValueError("enumeration result exceeds max_results")
        if len(set(self.object_ids)) != len(self.object_ids):
            raise ValueError("enumeration result must already be deduplicated")
        if any(not object_id or len(object_id) > 64 for object_id in self.object_ids):
            raise ValueError("enumeration result contains an invalid resource ID")
        return self


class VisibleSourceProjectionDTO(BaseModel):
    """Canonical source contribution used to compile one flattened visible tuple."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: int = Field(gt=0)
    resource_type: str = Field(min_length=1, max_length=64)
    resource_id: str = Field(min_length=1, max_length=64)
    visibility_class: str = Field(min_length=1, max_length=64)
    projected_subject: str = Field(min_length=1, max_length=256)
    source_kind: str = Field(min_length=1, max_length=64)
    source_owner_key: str = Field(min_length=1, max_length=256)
    source_locator: str = Field(min_length=1, max_length=256)
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    contribution_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_key: str | None = Field(default=None, min_length=1, max_length=64)
    source_version: int = Field(ge=0)
    tuple_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: str = Field(min_length=1, max_length=64)
    operation_id: int | None = Field(default=None, gt=0)
    migration_item_id: int | None = Field(default=None, gt=0)


class PermissionCheckRequest(StrictRequestModel):
    resource_type: str = Field(min_length=1, max_length=64)
    resource_id: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=64)


class PermissionCheckResponse(BaseModel):
    allowed: bool
