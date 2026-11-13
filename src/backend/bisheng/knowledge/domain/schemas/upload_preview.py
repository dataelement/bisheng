"""Owned temporary uploads; none of these fields grant resource permissions."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bisheng.knowledge.domain.schemas.processing_settings import ProcessingOverrides


def integer_flags(value):
    if isinstance(value, dict):
        for group, fields in (
            ("document", ("retain_images", "force_ocr", "enable_formula", "filter_page_header_footer")),
            ("table", ("append_header",)),
        ):
            for name in fields:
                if (
                    isinstance(value.get(group), dict)
                    and value[group].get(name) is not None
                    and type(value[group][name]) is not int
                ):
                    raise ValueError("processing flags must be integer 0 or 1")
    return value


class UploadPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overrides: ProcessingOverrides

    _integer_flags = field_validator("overrides", mode="before")(integer_flags)


class UploadChunkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    bbox: str = ""
    expected_revision: int = Field(ge=0)


class UploadContextItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upload_id: str = Field(min_length=1, max_length=64)
    file_path: str = Field(min_length=1, max_length=4096)
    overrides: ProcessingOverrides

    _integer_flags = field_validator("overrides", mode="before")(integer_flags)
    preview_id: str | None = Field(default=None, max_length=64)
    expected_revision: int | None = Field(default=None, ge=0)


class UploadContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["previewed", "direct"]
    items: list[UploadContextItem] = Field(min_length=1, max_length=1000)


@dataclass
class PreparedUpload:
    """Produced after receipt validation; consumed by the original upload use case."""

    overrides: ProcessingOverrides
    cache_key: str
    rows: list[dict] = field(default_factory=list)
