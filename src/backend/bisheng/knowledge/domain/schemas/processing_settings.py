"""F118 processing defaults and immutable effective-rule wire contracts.

Keep these domain DTOs independent of the legacy API ``FileProcessBase``.
The compatibility adapter must capture raw explicit input before that API
model fills defaults; defaults are resolved by the processing use case.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

PositiveInteger = Annotated[int, Field(strict=True, gt=0)]
NonNegativeInteger = Annotated[int, Field(strict=True, ge=0)]
BinaryFlag = Literal[0, 1]
SplitMode = Literal["auto", "custom", "hierarchical"]
SeparatorRule = Literal["before", "after"]


class ProcessingSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DocumentProcessingRule(ProcessingSchema):
    """A fully resolved ordinary-document rule, without invented defaults."""

    split_mode: SplitMode
    separator: list[str] = Field(min_length=1)
    separator_rule: list[SeparatorRule] = Field(min_length=1)
    chunk_size: PositiveInteger
    chunk_overlap: NonNegativeInteger
    hierarchy_level: Annotated[int, Field(strict=True, ge=1, le=6)]
    append_title: bool
    max_chunk_size: PositiveInteger
    retain_images: BinaryFlag
    force_ocr: BinaryFlag
    enable_formula: BinaryFlag
    filter_page_header_footer: BinaryFlag

    @model_validator(mode="after")
    def check_related_parameters(self) -> Self:
        if self.chunk_overlap > self.chunk_size:
            raise ValueError("chunk_overlap must not exceed chunk_size")
        if len(self.separator) != len(self.separator_rule):
            raise ValueError("separator and separator_rule must have the same length")
        if any(not value for value in self.separator):
            raise ValueError("separator entries must not be empty")
        return self


class TableProcessingRule(ProcessingSchema):
    """Existing ExcelRule fields; document splitting options do not apply."""

    slice_length: PositiveInteger
    header_start_row: PositiveInteger
    header_end_row: PositiveInteger
    append_header: BinaryFlag

    @model_validator(mode="after")
    def check_header_range(self) -> Self:
        if self.header_start_row > self.header_end_row:
            raise ValueError("header_start_row must not exceed header_end_row")
        return self


class PartialDocumentRule(ProcessingSchema):
    """Sparse raw overrides; missing and null both mean no override."""

    split_mode: SplitMode | None = None
    separator: list[str] | None = Field(default=None, min_length=1)
    separator_rule: list[SeparatorRule] | None = Field(default=None, min_length=1)
    chunk_size: PositiveInteger | None = None
    chunk_overlap: NonNegativeInteger | None = None
    hierarchy_level: Annotated[int, Field(strict=True, ge=1, le=6)] | None = None
    append_title: bool | None = None
    max_chunk_size: PositiveInteger | None = None
    retain_images: BinaryFlag | None = None
    force_ocr: BinaryFlag | None = None
    enable_formula: BinaryFlag | None = None
    filter_page_header_footer: BinaryFlag | None = None

    @model_validator(mode="after")
    def check_supplied_parameters(self) -> Self:
        if self.chunk_size is not None and self.chunk_overlap is not None and self.chunk_overlap > self.chunk_size:
            raise ValueError("chunk_overlap must not exceed chunk_size")
        if self.separator is not None:
            if any(not value for value in self.separator):
                raise ValueError("separator entries must not be empty")
            if self.separator_rule is not None and len(self.separator) != len(self.separator_rule):
                raise ValueError("separator and separator_rule must have the same length")
        return self


class PartialTableRule(ProcessingSchema):
    slice_length: PositiveInteger | None = None
    header_start_row: PositiveInteger | None = None
    header_end_row: PositiveInteger | None = None
    append_header: BinaryFlag | None = None

    @model_validator(mode="after")
    def check_supplied_header_range(self) -> Self:
        if (
            self.header_start_row is not None
            and self.header_end_row is not None
            and self.header_start_row > self.header_end_row
        ):
            raise ValueError("header_start_row must not exceed header_end_row")
        return self


class ProcessingDefaults(ProcessingSchema):
    schema_version: Literal[1] = 1
    document: DocumentProcessingRule
    table: TableProcessingRule


class ProcessingOverrides(ProcessingSchema):
    document: PartialDocumentRule | None = None
    table: PartialTableRule | None = None


class ProcessingSettingsRead(ProcessingSchema):
    space_id: PositiveInteger
    config_version: NonNegativeInteger
    saved_defaults: ProcessingDefaults | None
    effective_defaults: ProcessingDefaults


class ProcessingSettingsWrite(ProcessingSchema):
    expected_config_version: NonNegativeInteger
    defaults: ProcessingDefaults


class EffectiveProcessingSnapshot(ProcessingSchema):
    """Resolved, validated settings actually used for one file/version.

    space_config_version is provenance, not the model/index obsolescence
    revision. File-kind capability constraints are enforced by its owner.
    """

    schema_version: Literal[1] = 1
    file_kind: str = Field(min_length=1, max_length=32)
    effective_rule: DocumentProcessingRule | TableProcessingRule
    space_config_version: NonNegativeInteger
    supplied_fields_by_layer: dict[Literal["system", "space", "batch", "file", "specialized"], list[str]] = Field(
        default_factory=dict
    )

    @model_validator(mode="before")
    @classmethod
    def select_rule_for_kind(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        rule = value.get("effective_rule")
        if isinstance(rule, dict):
            model = TableProcessingRule if value.get("file_kind") == "table" else DocumentProcessingRule
            value = {**value, "effective_rule": model.model_validate(rule)}
        return value

    @model_validator(mode="after")
    def check_rule_matches_kind(self) -> Self:
        if (self.file_kind == "table") != isinstance(self.effective_rule, TableProcessingRule):
            raise ValueError("effective_rule must match file_kind")
        return self
