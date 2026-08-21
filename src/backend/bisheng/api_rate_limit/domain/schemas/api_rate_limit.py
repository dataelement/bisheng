from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_LIMIT_VALUE = 10_000_000
MAX_ROUTE_RULES = 200
MAX_PATH_LENGTH = 500
MAX_MESSAGE_LENGTH = 500
DEFAULT_RATE_LIMIT_MESSAGE = "请求过于频繁，请稍后重试"  # noqa: RUF001

PositiveLimit = Annotated[int, Field(strict=True, gt=0, le=MAX_LIMIT_VALUE)]


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    OPTIONS = "OPTIONS"
    HEAD = "HEAD"


class RateLimitMatchType(str, Enum):
    METHOD_PATH = "METHOD_PATH"
    PATH = "PATH"
    PREFIX = "PREFIX"


class RateLimitDimension(str, Enum):
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"


class RateLimitLimits(BaseModel):
    second: PositiveLimit | None = None
    minute: PositiveLimit | None = None
    hour: PositiveLimit | None = None
    day: PositiveLimit | None = None

    @field_validator("second", "minute", "hour", "day", mode="before")
    @classmethod
    def normalize_disabled_limit(cls, value):
        if value in (None, "", 0, "0"):
            return None
        return value

    def active_items(self) -> list[tuple[RateLimitDimension, int]]:
        values = self.model_dump()
        return [
            (dimension, int(values[dimension.value]))
            for dimension in (
                RateLimitDimension.DAY,
                RateLimitDimension.HOUR,
                RateLimitDimension.MINUTE,
                RateLimitDimension.SECOND,
            )
            if values[dimension.value] is not None
        ]

    def is_disabled(self) -> bool:
        return not self.active_items()


class RateLimitPolicy(BaseModel):
    limits: RateLimitLimits = Field(default_factory=RateLimitLimits)
    message: str = Field(default="", max_length=MAX_MESSAGE_LENGTH)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        return value.strip()


class ApiRateLimitRouteRule(RateLimitPolicy):
    id: UUID = Field(default_factory=uuid4)
    match_type: RateLimitMatchType
    method: HttpMethod | None = None
    path: str = Field(min_length=1, max_length=MAX_PATH_LENGTH)

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, value):
        return value.upper() if isinstance(value, str) else value

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("/"):
            raise ValueError("path must start with /")
        if any(char.isspace() for char in normalized) or "?" in normalized or "#" in normalized:
            raise ValueError("path must not contain whitespace, query, or fragment")
        return normalized

    @model_validator(mode="after")
    def validate_method_for_match_type(self):
        if self.match_type == RateLimitMatchType.METHOD_PATH and self.method is None:
            raise ValueError("METHOD_PATH requires method")
        if self.match_type != RateLimitMatchType.METHOD_PATH and self.method is not None:
            raise ValueError("PATH and PREFIX must not include method")
        return self


class ApiRateLimitConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: int = 1
    revision: int = Field(default=0, ge=0)
    global_rule: RateLimitPolicy = Field(default_factory=RateLimitPolicy, alias="global")
    routes: list[ApiRateLimitRouteRule] = Field(default_factory=list, max_length=MAX_ROUTE_RULES)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by: int | None = None

    @model_validator(mode="after")
    def validate_unique_rules(self):
        identities: set[tuple[str, str | None, str]] = set()
        for rule in self.routes:
            identity = (
                rule.match_type.value,
                rule.method.value if rule.method is not None else None,
                rule.path,
            )
            if identity in identities:
                raise ValueError("duplicate route rule")
            identities.add(identity)
        return self


class ApiRateLimitConfigUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    expected_revision: int = Field(ge=0)
    global_rule: RateLimitPolicy = Field(default_factory=RateLimitPolicy, alias="global")
    routes: list[ApiRateLimitRouteRule] = Field(default_factory=list, max_length=MAX_ROUTE_RULES)

    @model_validator(mode="after")
    def validate_as_config(self):
        ApiRateLimitConfig(
            revision=self.expected_revision,
            global_rule=self.global_rule,
            routes=self.routes,
        )
        return self

    def next_config(self, *, user_id: int) -> ApiRateLimitConfig:
        return ApiRateLimitConfig(
            revision=self.expected_revision + 1,
            global_rule=self.global_rule,
            routes=self.routes,
            updated_at=datetime.now(timezone.utc),
            updated_by=user_id,
        )


class ApiRateLimitRouteCatalogItem(BaseModel):
    method: HttpMethod
    path: str
    tags: list[str] = Field(default_factory=list)
    primary_tag: str
    name: str = ""
    summary: str = ""


class ApiRateLimitRouteCatalog(BaseModel):
    items: list[ApiRateLimitRouteCatalogItem] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_pages: int = Field(ge=0)
    categories: list[str] = Field(default_factory=list)
