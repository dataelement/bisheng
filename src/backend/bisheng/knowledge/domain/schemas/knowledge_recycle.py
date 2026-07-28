"""Knowledge recycle-bin domain schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class RecycleConfigResponse(BaseModel):
    retention_days: int = 7
    allowed_presets: list[int] = Field(default_factory=lambda: [3, 7])
    allow_custom_days: bool = True
    min_days: int = 1
    max_days: int = 365


class RecycleConfigUpdateRequest(BaseModel):
    retention_days: int = Field(..., ge=1, le=365)


class RecycleItemResponse(BaseModel):
    id: int
    file_id: int
    file_type: int
    name: str
    space_level: str | None = None
    space_level_label: str | None = None
    file_category: str | None = None
    file_category_code: str | None = None
    business_domain_code: str | None = None
    business_domain_name: str | None = None
    tags: list[dict[str, Any]] = Field(default_factory=list)
    file_encoding: str | None = None
    file_size: int | None = None
    deleted_by: int
    deleted_by_name: str | None = None
    deleted_at: datetime
    expire_at: datetime
    original_path: str
    original_knowledge_id: int
    original_knowledge_name: str | None = None
    can_restore_original: bool = False
    children_count: int = 0


class RecycleRestorePreviewRequest(BaseModel):
    item_ids: list[int]
    mode: Literal["original", "custom"] = "original"
    target_knowledge_id: int | None = None
    target_folder_id: int | None = None
    merge_folder: bool | None = None
    overwrite_files: bool | None = None


class RecycleRestoreRequest(RecycleRestorePreviewRequest):
    scope: Literal["entry", "files"] = "entry"
    file_ids: list[int] | None = None


class RecycleConflict(BaseModel):
    code: str
    message: str
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    item_ids: list[int] = Field(default_factory=list)


class RecycleRestorePreviewResponse(BaseModel):
    ok: bool
    blockers: list[RecycleConflict] = Field(default_factory=list)
    warnings: list[RecycleConflict] = Field(default_factory=list)
    need_confirm_merge: bool = False
    need_confirm_overwrite: bool = False


class RecyclePurgeRequest(BaseModel):
    item_ids: list[int] | None = None
    all: bool = False
