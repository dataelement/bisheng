"""Business inputs never expose database ownership fields."""

from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TemplateType(IntEnum):
    ASSISTANT = 5
    WORKFLOW = 10


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    description: str | None = Field(default=None, max_length=200)
    flow_type: Literal[5, 10] = 10
    flow_id: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name must not be blank")
        return value


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=30)
    description: str | None = Field(default=None, max_length=200)
    order_num: int | None = None
    guide_word: str | None = None

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Name must not be blank")
        return value

    @field_validator("order_num", mode="before")
    @classmethod
    def normalize_order(cls, value):
        return int(float(value)) if value is not None else None
