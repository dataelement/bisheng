from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SpaceLevel = Literal["personal", "team", "team_ks", "department", "public"]


class MigrationNodeRequest(BaseModel):
    node_type: Literal["file", "folder"]
    node_id: int = Field(gt=0)


class MigrationSourceSelectionRequest(BaseModel):
    space_id: int = Field(gt=0)
    nodes: list[MigrationNodeRequest] = Field(min_length=1)


class MigrationBatchCreateRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=64)
    source_selections: list[MigrationSourceSelectionRequest] = Field(min_length=1)
    target_space_id: int = Field(gt=0)
    target_folder_id: int | None = Field(default=None, gt=0)
    preserve_structure: bool = True
    conflict_strategy: Literal["skip", "overwrite"] = "skip"
    # Leaving a link behind is a publish, so the batch follows publish's level
    # ladder instead of the free placement a plain migration allows.
    preserve_link: bool = False

    @field_validator("request_id")
    @classmethod
    def normalize_request_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("request_id cannot be empty")
        return normalized


class MigrationSpaceResponse(BaseModel):
    id: int
    name: str
    level: str
    owner_valid: bool
    selectable: bool = True
    unavailable_reason: str | None = None


class MigrationChildResponse(BaseModel):
    id: int
    name: str
    node_type: Literal["file", "folder"]
    selectable: bool
    unavailable_reason: str | None = None
    has_children: bool = False
    status: int | None = None


class MigrationCursorPage(BaseModel):
    data: list[Any]
    page_size: int
    has_more: bool
    next_cursor: str | None = None


class MigrationBatchResponse(BaseModel):
    batch_no: str
    request_id: str
    operator_id: int
    operator_name: str
    source_selection: list[dict[str, Any]]
    source_spaces: list[dict[str, Any]]
    target_space_id: int
    target_space_name: str
    target_folder_id: int | None
    target_folder_name: str | None
    target_path: str
    conflict_strategy: str
    preserve_structure: bool
    status: str
    current_stage: str
    round_no: int
    scanned_count: int
    total_count: int
    executable_count: int
    completed_count: int
    succeeded_count: int
    skipped_count: int
    failed_count: int
    unprocessed_count: int
    overwrite_target_count: int
    last_error_code: str | None
    last_error_summary: str | None
    confirmed_by: int | None
    confirmed_at: datetime | None
    abandoned_by: int | None
    abandoned_at: datetime | None
    create_time: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class MigrationFileResponse(BaseModel):
    id: int
    source_file_id: int
    source_document_id: int | None
    source_version_id: int | None
    source_file_name: str
    source_space_id: int
    source_space_name: str
    source_path: str
    source_version_no: int | None
    is_primary: bool
    target_file_id: int | None
    target_space_id: int
    target_space_name: str
    target_path: str
    target_file_name: str
    status: str
    checkpoint: str
    reason_code: str | None
    summary: str | None


class MigrationUnitResponse(BaseModel):
    id: int
    unit_key: str
    unit_type: str
    source_document_id: int | None
    target_document_id: int | None
    source_space_id: int
    source_space_name: str
    source_path: str
    planned_target_path: str
    status: str
    checkpoint: str
    reason_code: str | None
    summary: str | None
    overwrite_unit_key: str | None
    overwrite_snapshot: dict[str, Any] | None
    folder_mapping: list[dict[str, Any]]
    attempt_count: int
    files: list[MigrationFileResponse] = Field(default_factory=list)


class MigrationAttemptResponse(BaseModel):
    id: int
    unit_id: int
    round_no: int
    attempt_no: int
    start_checkpoint: str
    end_checkpoint: str | None
    result: str
    reason_code: str | None
    error_summary: str | None
    started_at: datetime
    finished_at: datetime | None


class MigrationPageResponse(BaseModel):
    data: list[Any]
    total: int
    page: int
    page_size: int
