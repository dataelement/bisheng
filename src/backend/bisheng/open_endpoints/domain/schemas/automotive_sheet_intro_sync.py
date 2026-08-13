from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from bisheng.open_endpoints.domain.models.filelib_scheduled_sync_run_log import (
    AUTOMOTIVE_SHEET_INTRO_JOB_CODE,
)

DEFAULT_AUTOMOTIVE_SHEET_FILE_NAME = "汽车板介绍.pdf"
DEFAULT_AUTOMOTIVE_SHEET_EXTERNAL_FILE_ID = "automotive_sheet_intro"
DEFAULT_AUTOMOTIVE_SHEET_API_METHOD = "GET"
DEFAULT_AUTOMOTIVE_SHEET_API_TIMEOUT_SECONDS = 120

AutomotiveSheetIntroSyncTriggerType = Literal["manual", "scheduled"]
AutomotiveSheetIntroSyncRunStatus = Literal["running", "success", "failed", "skipped"]
AutomotiveSheetIntroSyncApiMethod = Literal["GET", "POST"]

_PDF_FILE_NAME_PATTERN = re.compile(r"^[^/\\]+\.pdf$", re.IGNORECASE)

LEGACY_AUTOMOTIVE_SHEET_INTRO_SYNC_CONFIG_KEYS = (
    "category",
    "business_domain",
    "target_space",
)


class AutomotiveSheetIntroSyncConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    api_url: str | None = None
    api_method: AutomotiveSheetIntroSyncApiMethod = DEFAULT_AUTOMOTIVE_SHEET_API_METHOD
    api_timeout_seconds: int = Field(
        default=DEFAULT_AUTOMOTIVE_SHEET_API_TIMEOUT_SECONDS,
        ge=10,
        le=600,
    )
    api_ssl_verify: bool = Field(
        default=True,
        description="Verify upstream TLS certificate when api_url uses https",
    )
    developer_token_id: int | None = Field(default=None, gt=0)
    file_name: str = DEFAULT_AUTOMOTIVE_SHEET_FILE_NAME
    external_file_id: str = DEFAULT_AUTOMOTIVE_SHEET_EXTERNAL_FILE_ID

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        basename = os.path.basename(value.strip())
        if not basename or basename != value.strip():
            raise ValueError("file_name must be a basename without path separators")
        if len(basename) > 200:
            raise ValueError("file_name must be at most 200 characters")
        if not _PDF_FILE_NAME_PATTERN.match(basename):
            raise ValueError("file_name must end with .pdf")
        return basename

    @field_validator("external_file_id")
    @classmethod
    def validate_external_file_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 255:
            raise ValueError("external_file_id must be 1-255 characters")
        return normalized

    @field_validator("api_url")
    @classmethod
    def normalize_api_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > 2048:
            raise ValueError("api_url must be at most 2048 characters")
        HttpUrl(normalized)
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("api_url must use http or https")
        return normalized

    @model_validator(mode="after")
    def validate_enabled_requirements(self):
        if not self.enabled:
            return self
        missing: list[str] = []
        if not self.api_url:
            missing.append("api_url")
        if self.developer_token_id is None:
            missing.append("developer_token_id")
        if missing:
            raise ValueError(f"enabled config requires: {', '.join(missing)}")
        return self


def strip_legacy_automotive_sheet_intro_sync_config_keys(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(payload)
    for key in LEGACY_AUTOMOTIVE_SHEET_INTRO_SYNC_CONFIG_KEYS:
        cleaned.pop(key, None)
    return cleaned


class AutomotiveSheetIntroSyncRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_code: str
    trigger_type: AutomotiveSheetIntroSyncTriggerType
    status: AutomotiveSheetIntroSyncRunStatus
    file_id: int | None = None
    knowledge_id: int | None = None
    file_name: str | None = None
    error_message: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    duration_ms: int | None = None


class AutomotiveSheetIntroSyncTestResponse(BaseModel):
    run_id: int | None = None
    status: AutomotiveSheetIntroSyncRunStatus | None = None
    error_message: str | None = None
    skip_reason: str | None = None
    file_id: int | None = None
    scope: Literal["tenant"] = "tenant"
    tenant_id: int
    message: str


def default_automotive_sheet_intro_sync_config() -> AutomotiveSheetIntroSyncConfig:
    return AutomotiveSheetIntroSyncConfig()


AUTOMOTIVE_SHEET_INTRO_SYNC_TEST_TASK_NAME = (
    "bisheng.open_endpoints.worker.filelib_sync_worker.run_automotive_sheet_intro_sync"
)

__all__ = [
    "AUTOMOTIVE_SHEET_INTRO_JOB_CODE",
    "AUTOMOTIVE_SHEET_INTRO_SYNC_TEST_TASK_NAME",
    "AutomotiveSheetIntroSyncApiMethod",
    "AutomotiveSheetIntroSyncConfig",
    "AutomotiveSheetIntroSyncRunRead",
    "AutomotiveSheetIntroSyncRunStatus",
    "AutomotiveSheetIntroSyncTestResponse",
    "AutomotiveSheetIntroSyncTriggerType",
    "DEFAULT_AUTOMOTIVE_SHEET_API_METHOD",
    "DEFAULT_AUTOMOTIVE_SHEET_API_TIMEOUT_SECONDS",
    "DEFAULT_AUTOMOTIVE_SHEET_EXTERNAL_FILE_ID",
    "DEFAULT_AUTOMOTIVE_SHEET_FILE_NAME",
    "LEGACY_AUTOMOTIVE_SHEET_INTRO_SYNC_CONFIG_KEYS",
    "default_automotive_sheet_intro_sync_config",
    "strip_legacy_automotive_sheet_intro_sync_config_keys",
]
