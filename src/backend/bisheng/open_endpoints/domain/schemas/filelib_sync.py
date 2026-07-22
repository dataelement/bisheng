from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FilelibSyncParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    external_file_id: str = Field(min_length=1, max_length=255)
    file_name: str = Field(min_length=1, max_length=200)
    department: str | None = None
    department_id: int | None = Field(default=None, gt=0)
    responsible_person: str | None = None
    responsible_person_id: int | None = Field(default=None, gt=0)

    @field_validator("external_file_id", "file_name", mode="before")
    @classmethod
    def normalize_required_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("department", "responsible_person", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("department_id", "responsible_person_id", mode="before")
    @classmethod
    def normalize_optional_id(cls, value: Any) -> int | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise ValueError("id must be an integer")
        return int(value)


class FilelibSyncResponseData(BaseModel):
    external_file_id: str
    file_id: int
    file_encoding: str
    knowledge_id: int
    knowledge_name: str
    status: int
