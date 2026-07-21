from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _strip(value: str | None) -> str:
    return str(value or "").strip()


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

    @field_validator(
        "name",
        "tags",
        "instructor",
        "organization",
        "description",
        "enabled",
        "show_on_home",
        "sort_order",
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
    videos: list[VideoRead] | None = None


class ProgressRead(BaseModel):
    video_id: str
    progress_seconds: int
    completed: bool
    completed_at: datetime | None = None
    updated_at: datetime | None = None
