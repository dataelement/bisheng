from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _strip(value: str | None) -> str:
    return str(value or "").strip()


def _optional_catalog_id(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def validate_media_url(value: str) -> str:
    text = _strip(value)
    if not text or len(text) > 2048 or any(ord(char) < 32 for char in text):
        raise ValueError("media url is invalid")
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise ValueError("media url is invalid") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("media url must be an absolute http(s) url without credentials")
    return text


class CourseTag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(max_length=50)
    display_type: Literal["domain", "level", "gray"]

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = _strip(value)
        if not normalized:
            raise ValueError("tag label is required")
        return normalized


class CourseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=200)
    tags: list[CourseTag] = Field(default_factory=list)
    instructor: str = Field(default="", max_length=100)
    organization: str = Field(default="", max_length=200)
    description: str = ""
    enabled: bool = False
    show_on_home: bool = False
    sort_order: int = 0
    catalog_id: str | None = Field(default=None, min_length=32, max_length=32)
    course_type: Literal["local", "external"] = "local"
    external_url: str = Field(default="", max_length=2048)
    external_id: str | None = Field(default=None, max_length=128)
    cover_url: str = Field(default="", max_length=2048)
    source_updated_at: datetime | None = None

    @field_validator("catalog_id", mode="before")
    @classmethod
    def normalize_catalog_id(cls, value: object) -> object:
        return _optional_catalog_id(value)

    @field_validator("external_id", mode="before")
    @classmethod
    def normalize_external_id(cls, value: object) -> object:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = _strip(value)
        if not normalized:
            raise ValueError("course name is required")
        return normalized

    @field_validator("instructor", "organization", "description")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _strip(value)

    @model_validator(mode="after")
    def normalize_external_fields(self):
        if self.cover_url:
            self.cover_url = validate_media_url(self.cover_url)
        else:
            self.cover_url = ""
        if self.course_type == "local":
            self.external_url = ""
            self.external_id = None
            return self
        if self.external_url:
            self.external_url = validate_media_url(self.external_url)
        else:
            self.external_url = ""
        return self


class CourseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    tags: list[CourseTag] | None = None
    instructor: str | None = Field(default=None, max_length=100)
    organization: str | None = Field(default=None, max_length=200)
    description: str | None = None
    enabled: bool | None = None
    show_on_home: bool | None = None
    sort_order: int | None = None
    catalog_id: str | None = Field(default=None, min_length=32, max_length=32)
    course_type: Literal["local", "external"] | None = None
    external_url: str | None = Field(default=None, max_length=2048)
    external_id: str | None = Field(default=None, max_length=128)
    cover_url: str | None = Field(default=None, max_length=2048)
    source_updated_at: datetime | None = None

    @field_validator("catalog_id", mode="before")
    @classmethod
    def normalize_catalog_id(cls, value: object) -> object:
        return _optional_catalog_id(value)

    @field_validator("external_id", mode="before")
    @classmethod
    def normalize_external_id(cls, value: object) -> object:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("cover_url", mode="before")
    @classmethod
    def empty_cover_url_is_blank(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return ""
        return value

    @field_validator(
        "name",
        "tags",
        "instructor",
        "organization",
        "description",
        "enabled",
        "show_on_home",
        "sort_order",
        "course_type",
        "external_url",
        "cover_url",
        mode="before",
    )
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("course update fields cannot be null")
        return value

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _strip(value)
        if not normalized:
            raise ValueError("course name is required")
        return normalized

    @field_validator("instructor", "organization", "description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return None if value is None else _strip(value)

    @field_validator("external_url")
    @classmethod
    def normalize_external_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = _strip(value)
        return "" if not text else validate_media_url(text)

    @field_validator("cover_url")
    @classmethod
    def normalize_cover_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = _strip(value)
        return "" if not text else validate_media_url(text)


class UrlVideoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=200)
    source_url: str = Field(max_length=2048)
    duration_seconds: int = Field(gt=0)
    enabled: bool = False
    sort_order: int = 0

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = _strip(value)
        if not normalized:
            raise ValueError("video title is required")
        return normalized

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        return validate_media_url(value)


class VideoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    duration_seconds: int | None = Field(default=None, gt=0)
    enabled: bool | None = None
    sort_order: int | None = None

    @field_validator(
        "title",
        "duration_seconds",
        "enabled",
        "sort_order",
        mode="before",
    )
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("video update fields cannot be null")
        return value

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _strip(value)
        if not normalized:
            raise ValueError("video title is required")
        return normalized


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=32, max_length=32)
    sort_order: int


class OrderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[OrderItem]

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("order ids must be unique")
        return self


class CourseBatchDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("ids")
    @classmethod
    def normalize_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            text = _strip(item)
            if len(text) != 32:
                raise ValueError("course id is invalid")
            normalized.append(text)
        if len(normalized) != len(set(normalized)):
            raise ValueError("course ids must be unique")
        return normalized


class ProgressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    progress_seconds: float = Field(ge=0)
    completed: bool = False


class VideoRead(BaseModel):
    id: str
    title: str
    source_type: Literal["upload", "url"]
    play_url: str
    duration_seconds: int
    enabled: bool | None = None
    sort_order: int
    created_at: datetime
    updated_at: datetime | None
    source_url: str | None = None
    original_filename: str | None = None


class CourseRead(BaseModel):
    id: str
    name: str
    tags: list[CourseTag]
    instructor: str
    organization: str
    description: str
    total_duration_seconds: int
    video_count: int
    sort_order: int
    created_at: datetime
    updated_at: datetime | None
    enabled: bool | None = None
    show_on_home: bool | None = None
    catalog_id: str | None = None
    catalog_name: str | None = None
    catalog_name_path: str | None = None
    course_type: Literal["local", "external"] = "local"
    external_url: str | None = None
    external_id: str | None = None
    cover_url: str | None = None
    source_updated_at: datetime | None = None
    videos: list[VideoRead] | None = None


class CatalogCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=200)
    parent_id: str | None = Field(default=None, min_length=32, max_length=32)
    order_index: int = 0
    opened: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = _strip(value)
        if not normalized:
            raise ValueError("catalog name is required")
        if "/" in normalized or "->" in normalized:
            raise ValueError("catalog name cannot contain path separators")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return _strip(value)


class CatalogUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=200)
    parent_id: str | None = Field(default=None, min_length=32, max_length=32)
    order_index: int | None = None
    opened: bool | None = None

    @field_validator("name", "description", "order_index", "opened", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("catalog update fields cannot be null")
        return value

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _strip(value)
        if not normalized:
            raise ValueError("catalog name is required")
        if "/" in normalized or "->" in normalized:
            raise ValueError("catalog name cannot contain path separators")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return None if value is None else _strip(value)


class CatalogRead(BaseModel):
    id: str
    external_id: str | None = None
    name: str
    description: str
    parent_id: str | None = None
    routing_path: str
    catalog_id_path: str
    catalog_name_path: str
    order_index: int
    opened: bool
    deleted: bool
    course_count: int = 0
    created_at: datetime
    updated_at: datetime | None
    create_user: int
    update_user: int
    children: list[CatalogRead] | None = None


class CatalogImportIssue(BaseModel):
    row: int
    code: str
    message: str
    recoverable: bool = False


class CatalogImportPreview(BaseModel):
    total: int
    valid: int
    issues: list[CatalogImportIssue] = Field(default_factory=list)


class CatalogImportResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str] = Field(default_factory=list)


class CourseImportIssue(BaseModel):
    row: int
    code: str
    message: str
    recoverable: bool = False


class CourseImportPreview(BaseModel):
    total: int
    valid: int
    issues: list[CourseImportIssue] = Field(default_factory=list)


class CourseImportResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str] = Field(default_factory=list)


CatalogRead.model_rebuild()


class ProgressRead(BaseModel):
    video_id: str
    progress_seconds: int
    completed: bool
    completed_at: datetime | None = None
    updated_at: datetime | None = None
