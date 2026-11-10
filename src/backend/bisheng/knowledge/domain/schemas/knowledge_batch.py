"""Ordinary batch wire inputs and detached facts; no deletion or processing jobs."""

from typing import Literal

from pydantic import Field, model_validator

from bisheng.knowledge.domain.schemas.processing_job import OperationInvalidItem, OperationItem
from bisheng.knowledge.domain.schemas.processing_settings import PositiveInteger, ProcessingSchema


class BatchSelection(ProcessingSchema):
    id: PositiveInteger
    type: Literal["file", "folder"]


class BatchCommand(ProcessingSchema):
    operation: Literal["download", "tag", "retry"]
    items: list[BatchSelection] = Field(min_length=1)
    tag_ids: list[PositiveInteger] = Field(default_factory=list)
    new_tag_names: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_parameters(self):
        if self.operation != "tag" and self.model_fields_set & {"tag_ids", "new_tag_names"}:
            raise ValueError("tag parameters require the tag operation")
        names = [name.strip() for name in self.new_tag_names]
        if any(not name or len(name) > 100 for name in names):
            raise ValueError("invalid tag name")
        object.__setattr__(self, "new_tag_names", list(dict.fromkeys(names)))
        object.__setattr__(self, "tag_ids", list(dict.fromkeys(self.tag_ids)))
        unique = {(item.type, item.id): item for item in self.items}
        object.__setattr__(self, "items", list(unique.values()))
        return self


class BatchInspection(ProcessingSchema):
    check_complete: bool = True
    can_execute: bool
    valid_items: list[OperationItem]
    invalid_items: list[OperationInvalidItem]
    requires_skip_confirmation: bool
    impact: dict
