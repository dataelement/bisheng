from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FilelibSyncParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    external_file_id: str = Field(min_length=1, max_length=255)
    file_name: str = Field(min_length=1, max_length=200)
    department: str | None = None
    department_id: str | None = Field(default=None, min_length=1, max_length=128)
    responsible_person: str | None = Field(
        default=None,
        description="Responsible person external_id in user table",
    )
    responsible_person_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Responsible person external_id in user table",
    )
    tags: list[str] = Field(default_factory=list, description="Tag names applied to the synced file")

    @field_validator("external_file_id", "file_name", mode="before")
    @classmethod
    def normalize_required_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator(
        "department",
        "responsible_person",
        "responsible_person_id",
        "department_id",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("tags must be a list of strings")
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                raise ValueError("tags must be a list of strings")
            name = item.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            normalized.append(name)
        return normalized


class FilelibSyncResponseData(BaseModel):
    external_file_id: str
    file_id: int
    file_encoding: str
    knowledge_id: int
    knowledge_name: str
    status: int
    version_link_pending: bool = False
    replaced_file_id: int | None = None
    tags: list[str] = Field(default_factory=list)
