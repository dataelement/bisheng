"""F118 processing command, result, and precheck DTOs; no execution logic."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from bisheng.knowledge.domain.schemas.processing_settings import (
    NonNegativeInteger,
    PositiveInteger,
    ProcessingOverrides,
    ProcessingSchema,
)


class ProcessingKind(StrEnum):
    EMBEDDING_REBUILD = "embedding_rebuild"
    FILE_REPROCESS = "file_reprocess"
    FILE_RESPLIT = "file_resplit"
    METADATA_SCHEMA_CHANGE = "metadata_schema_change"
    MOVE_INDEX = "move_index"
    SPACE_COPY = "space_copy"


class JobState(StrEnum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"
    OBSOLETE = "obsolete"


class ItemState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    OBSOLETE = "obsolete"


class ResourceVersionTarget(ProcessingSchema):
    file_id: PositiveInteger
    document_id: PositiveInteger
    version_id: PositiveInteger


class ProcessingTargetInput(ProcessingSchema):
    """Owner verifies the supplied IDs and resolves the true document ID."""

    file_id: PositiveInteger
    version_id: PositiveInteger
    document_id: PositiveInteger | None = None


class EmbeddingRebuildParameters(ProcessingSchema):
    embedding_model_id: PositiveInteger | None = None


class FileProcessingParameters(ProcessingSchema):
    overrides: ProcessingOverrides = Field(default_factory=ProcessingOverrides)


class MetadataSchemaChange(ProcessingSchema):
    operation: Literal["add", "rename", "delete"]
    field_name: str = Field(min_length=1, max_length=255, pattern=r"^[a-z][a-z0-9_]*$")
    field_type: Literal["string", "number", "time"] | None = None
    new_field_name: str | None = Field(default=None, max_length=255, pattern=r"^[a-z][a-z0-9_]*$")

    @model_validator(mode="after")
    def check_operation_fields(self) -> Self:
        if self.operation == "add" and (self.field_type is None or self.new_field_name is not None):
            raise ValueError("add requires field_type and no new_field_name")
        if self.operation == "rename" and (self.new_field_name is None or self.field_type is not None):
            raise ValueError("rename requires new_field_name and no field_type")
        if self.operation == "delete" and (self.field_type is not None or self.new_field_name is not None):
            raise ValueError("delete does not accept replacement fields")
        return self


class MetadataSchemaParameters(ProcessingSchema):
    expected_schema_revision: NonNegativeInteger
    changes: list[MetadataSchemaChange] = Field(min_length=1)


class ProcessingPrecheckRequest(ProcessingSchema):
    kind: Literal["embedding_rebuild", "file_reprocess", "file_resplit", "metadata_schema_change"]
    targets: list[ProcessingTargetInput] | None = None
    parameters: EmbeddingRebuildParameters | FileProcessingParameters | MetadataSchemaParameters

    @model_validator(mode="before")
    @classmethod
    def select_parameters(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        kind = value.get("kind")
        model = {
            "embedding_rebuild": EmbeddingRebuildParameters,
            "file_reprocess": FileProcessingParameters,
            "file_resplit": FileProcessingParameters,
            "metadata_schema_change": MetadataSchemaParameters,
        }.get(kind)
        if model is not None:
            value = {**value, "parameters": model.model_validate(value.get("parameters", {}))}
        return value

    @model_validator(mode="after")
    def check_scope(self) -> Self:
        if self.kind in {"file_reprocess", "file_resplit"}:
            if not self.targets:
                raise ValueError("file processing requires explicit version targets")
        elif self.targets is not None:
            raise ValueError("space-wide processing does not accept a file subset")
        if self.targets is not None:
            identities = {(target.file_id, target.version_id) for target in self.targets}
            if len(identities) != len(self.targets):
                raise ValueError("duplicate version targets are not allowed")
        return self


IdempotencyKey = Annotated[str, Field(min_length=1, max_length=64)]
ConfirmationId = Annotated[str, Field(min_length=1, max_length=36)]
PlanDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ProcessingCreateRequest(ProcessingSchema):
    idempotency_key: IdempotencyKey
    confirmation_id: ConfirmationId
    plan_digest: PlanDigest


class ProcessingRetryRequest(ProcessingSchema):
    idempotency_key: IdempotencyKey
    expected_job_revision: NonNegativeInteger


class JobAccepted(ProcessingSchema):
    job_id: str = Field(min_length=1, max_length=36)
    accepted: Literal[True] = True
    state: JobState
    reused: bool


class ProcessingJobRead(ProcessingSchema):
    id: str = Field(min_length=1, max_length=36)
    space_id: PositiveInteger
    kind: ProcessingKind
    state: JobState
    revision: NonNegativeInteger
    accepted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_count: NonNegativeInteger
    succeeded_count: NonNegativeInteger
    failed_count: NonNegativeInteger
    pending_count: NonNegativeInteger
    hidden_item_count: NonNegativeInteger = 0
    retryable: bool = False
    obsolete_reason: str | None = None
    error_code: int | None = None


class ProcessingItemRead(ProcessingSchema):
    id: str = Field(min_length=1, max_length=36)
    file_id: PositiveInteger | None = None
    document_id: PositiveInteger | None = None
    version_id: PositiveInteger | None = None
    step: str = Field(min_length=1, max_length=64)
    state: ItemState
    attempt: NonNegativeInteger
    error_code: int | None = None
    message: str | None = None
    retryable: bool = False


class OperationItem(ProcessingSchema):
    id: PositiveInteger
    type: Literal["file", "folder", "space", "model", "version"]
    name: str | None = None


class OperationInvalidItem(ProcessingSchema):
    id: PositiveInteger | None = None
    type: Literal["file", "folder", "space", "model", "version"] | None = None
    name: str | None = None
    reason: str = Field(min_length=1, max_length=64)
    error_code: int | None = None


class OperationPrecheck(ProcessingSchema):
    confirmation_id: ConfirmationId
    plan_digest: PlanDigest
    expires_at: datetime
    check_complete: bool
    can_execute: bool
    valid_items: list[OperationItem] = Field(default_factory=list)
    invalid_items: list[OperationInvalidItem] = Field(default_factory=list)
    impact: dict[str, Any] = Field(default_factory=dict)
    requires_skip_confirmation: bool = False

    @model_validator(mode="after")
    def check_executable_plan(self) -> Self:
        if self.can_execute and (not self.check_complete or not self.valid_items):
            raise ValueError("executable plans require a complete check and at least one valid item")
        return self
