"""门户全文高级检索的严格查询与游标契约。"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import Field, StrictInt, StrictStr, field_validator, model_validator

from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import StrictSchema


class KnowledgeFulltextSearchField(str, Enum):
    ALL = "all"
    FILE_NAME = "file_name"
    SUMMARY = "summary"
    TAGS = "tags"
    CONTENT = "content"


class KnowledgeFulltextSearchSort(str, Enum):
    RELEVANCE = "relevance"
    UPDATED_AT_DESC = "updated_at_desc"
    UPDATED_AT_ASC = "updated_at_asc"
    PREVIEW_COUNT_DESC = "preview_count_desc"
    PREVIEW_COUNT_ASC = "preview_count_asc"
    DOWNLOAD_COUNT_DESC = "download_count_desc"
    DOWNLOAD_COUNT_ASC = "download_count_asc"


class KnowledgeFulltextConditionRelation(str, Enum):
    AND = "and"
    OR = "or"
    NOT = "not"


class KnowledgeFulltextConditionMatchMode(str, Enum):
    EXACT = "exact"
    FUZZY = "fuzzy"


class KnowledgeFulltextTextCondition(StrictSchema):
    relation: KnowledgeFulltextConditionRelation | None = None
    field: Literal["all", "file_name", "summary", "tags", "content"]
    match_mode: KnowledgeFulltextConditionMatchMode
    value: str = Field(min_length=1, max_length=200)

    @field_validator("value", mode="before")
    @classmethod
    def normalize_value(cls, value: Any) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("condition value must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_fuzzy_value(self):
        if self.match_mode == KnowledgeFulltextConditionMatchMode.FUZZY:
            if any(char.isspace() for char in self.value):
                raise ValueError("fuzzy condition value must not contain whitespace")
            if len(self.value) > constants.KNOWLEDGE_FULLTEXT_NGRAM_MAX:
                raise ValueError(
                    f"fuzzy condition value must contain at most "
                    f"{constants.KNOWLEDGE_FULLTEXT_NGRAM_MAX} characters"
                )
        return self


class KnowledgeFulltextSelectCondition(StrictSchema):
    relation: KnowledgeFulltextConditionRelation | None = None
    field: Literal[
        "knowledge_level",
        "knowledge_id",
        "business_domain_code",
        "file_ext",
        "original_uploader_id",
        "original_knowledge_id",
    ]
    match_mode: Literal[KnowledgeFulltextConditionMatchMode.EXACT] = (
        KnowledgeFulltextConditionMatchMode.EXACT
    )
    value: StrictStr | StrictInt

    @model_validator(mode="after")
    def normalize_value(self):
        if self.field in {"knowledge_id", "original_uploader_id", "original_knowledge_id"}:
            if isinstance(self.value, bool) or not isinstance(self.value, int) or self.value <= 0:
                raise ValueError(f"{self.field} condition value must be a positive integer")
            return self
        if not isinstance(self.value, str):
            raise ValueError(f"{self.field} condition value must be a string")
        normalized = self.value.strip()
        if not normalized:
            raise ValueError(f"{self.field} condition value must not be empty")
        if self.field in {"business_domain_code"}:
            normalized = normalized.upper()
        if self.field == "file_ext":
            normalized = normalized.lower().lstrip(".")
        self.value = normalized
        return self


class KnowledgeFulltextDocumentCategoryValue(StrictSchema):
    document_type: str | None = Field(default=None, max_length=64)
    file_subcategory_code: str | None = Field(default=None, max_length=64)

    @field_validator("document_type", "file_subcategory_code", mode="before")
    @classmethod
    def normalize_code(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None

    @model_validator(mode="after")
    def require_a_code(self):
        if self.document_type is None and self.file_subcategory_code is None:
            raise ValueError("document_category condition requires at least one code")
        return self


class KnowledgeFulltextDocumentCategoryCondition(StrictSchema):
    relation: KnowledgeFulltextConditionRelation | None = None
    field: Literal["document_category"]
    match_mode: Literal[KnowledgeFulltextConditionMatchMode.EXACT] = (
        KnowledgeFulltextConditionMatchMode.EXACT
    )
    value: KnowledgeFulltextDocumentCategoryValue


class KnowledgeFulltextCountRange(StrictSchema):
    min: int | None = Field(default=None, ge=0)
    max: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.min is None and self.max is None:
            raise ValueError("count range requires min or max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("count range min must not be greater than max")
        return self


class KnowledgeFulltextCountCondition(StrictSchema):
    relation: KnowledgeFulltextConditionRelation | None = None
    field: Literal["preview_count", "download_count"]
    match_mode: Literal[KnowledgeFulltextConditionMatchMode.EXACT] = (
        KnowledgeFulltextConditionMatchMode.EXACT
    )
    range: KnowledgeFulltextCountRange


class KnowledgeFulltextDateRange(StrictSchema):
    from_date: date | None = Field(default=None, alias="from")
    to: date | None = None

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.from_date is None and self.to is None:
            raise ValueError("date range requires from or to")
        if self.from_date is not None and self.to is not None and self.from_date > self.to:
            raise ValueError("date range from must not be later than to")
        return self


class KnowledgeFulltextDateCondition(StrictSchema):
    relation: KnowledgeFulltextConditionRelation | None = None
    field: Literal["updated_at"]
    match_mode: Literal[KnowledgeFulltextConditionMatchMode.EXACT] = (
        KnowledgeFulltextConditionMatchMode.EXACT
    )
    range: KnowledgeFulltextDateRange


KnowledgeFulltextCondition = Annotated[
    KnowledgeFulltextTextCondition
    | KnowledgeFulltextSelectCondition
    | KnowledgeFulltextDocumentCategoryCondition
    | KnowledgeFulltextCountCondition
    | KnowledgeFulltextDateCondition,
    Field(discriminator="field"),
]


class KnowledgeFulltextAdvancedSearchQuery(StrictSchema):
    space_ids: list[int] = Field(min_length=1)
    version: Literal[1] = 1
    conditions: list[KnowledgeFulltextCondition] | None = Field(
        default=None,
        max_length=constants.KNOWLEDGE_FULLTEXT_SEARCH_MAX_CONDITIONS,
    )
    space_level: str | None = None
    business_domain_code: str | None = None
    document_type: str | None = None
    file_subcategory_code: str | None = None
    file_ext: str | None = None
    tag: str | None = None
    all_keywords: str | None = Field(default=None, max_length=200)
    exact_phrase: str | None = Field(default=None, max_length=200)
    any_keywords: str | None = Field(default=None, max_length=200)
    exclude_keywords: str | None = Field(default=None, max_length=200)
    search_field: KnowledgeFulltextSearchField = KnowledgeFulltextSearchField.ALL
    original_uploader_id: int | None = Field(default=None, gt=0)
    original_knowledge_id: int | None = Field(default=None, gt=0)
    preview_count_min: int | None = Field(default=None, ge=0)
    preview_count_max: int | None = Field(default=None, ge=0)
    download_count_min: int | None = Field(default=None, ge=0)
    download_count_max: int | None = Field(default=None, ge=0)
    updated_from: date | None = None
    updated_to: date | None = None
    sort: KnowledgeFulltextSearchSort = KnowledgeFulltextSearchSort.RELEVANCE

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_sort(cls, values: Any) -> Any:
        if isinstance(values, dict) and values.get("sort") == "updated_at":
            return {**values, "sort": KnowledgeFulltextSearchSort.UPDATED_AT_DESC.value}
        return values

    @field_validator(
        "space_level",
        "business_domain_code",
        "document_type",
        "file_subcategory_code",
        "file_ext",
        "tag",
        "all_keywords",
        "exact_phrase",
        "any_keywords",
        "exclude_keywords",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = " ".join(str(value).split())
        return normalized or None

    @field_validator("space_ids")
    @classmethod
    def normalize_space_ids(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("space_ids must contain positive integers")
        return sorted(set(values))

    @field_validator("file_ext")
    @classmethod
    def normalize_file_ext(cls, value: str | None) -> str | None:
        return value.lower().lstrip(".") if value else None

    @field_validator("business_domain_code", "document_type", "file_subcategory_code")
    @classmethod
    def normalize_codes(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @model_validator(mode="after")
    def validate_ranges(self):
        ranges = (
            ("preview_count", self.preview_count_min, self.preview_count_max),
            ("download_count", self.download_count_min, self.download_count_max),
        )
        for name, lower, upper in ranges:
            if lower is not None and upper is not None and lower > upper:
                raise ValueError(f"{name}_min must not be greater than {name}_max")
        if self.updated_from is not None and self.updated_to is not None:
            if self.updated_from > self.updated_to:
                raise ValueError("updated_from must not be later than updated_to")
        if self.conditions:
            self.conditions[0].relation = None
            for condition in self.conditions[1:]:
                if condition.relation is None:
                    raise ValueError("conditions after the first require relation")
        return self

    @property
    def has_keywords(self) -> bool:
        if self.conditions is not None:
            return any(
                isinstance(condition, KnowledgeFulltextTextCondition)
                for condition in self.conditions
            )
        return any(
            (
                self.all_keywords,
                self.exact_phrase,
                self.any_keywords,
                self.exclude_keywords,
            )
        )


class KnowledgeFulltextSearchHit(StrictSchema):
    file_id: int = Field(gt=0)
    score: float | None = None
    sort_values: list[Any] = Field(min_length=2)


class KnowledgeFulltextSearchBatch(StrictSchema):
    pit_id: str = Field(min_length=1)
    hits: list[KnowledgeFulltextSearchHit] = Field(default_factory=list)
    exhausted: bool = False


class KnowledgeFulltextSearchSession(StrictSchema):
    pit_id: str = Field(min_length=1)
    search_after: list[Any] | None = None
    context_signature: str = Field(min_length=64, max_length=64)
    expected_sort_values: int = Field(ge=2)


class KnowledgeFulltextUploaderCandidate(StrictSchema):
    user_id: int = Field(gt=0)
    user_name: str = Field(min_length=1, max_length=255)


class KnowledgeFulltextUploaderSupport(StrictSchema):
    user_id: int = Field(gt=0)
    file_ids: list[int] = Field(default_factory=list)
