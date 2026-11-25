"""Versioned knowledge selection on a workbench question (daily or task)."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PositiveId = Annotated[int, Field(strict=True, gt=0)]


class RecordedRoundScope(BaseModel):
    """Only an explicit map (possibly empty) is evidence of the original scope."""

    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    recorded: Literal[True]
    knowledge_space_ids: list[PositiveId] = Field(max_length=50)
    organization_knowledge_ids: list[PositiveId] = Field(max_length=50)
    knowledge_space_tag_filters: dict[Annotated[str, Field(pattern=r"^[1-9][0-9]*$")], PositiveId]
    personal_knowledge_enabled: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def tags_belong_to_selected_spaces(self):
        if not self.knowledge_space_tag_filters.keys() <= {str(i) for i in self.knowledge_space_ids}:
            raise ValueError("Fixed tags must belong to selected spaces")
        return self

    @classmethod
    def recover(cls, value):
        if not isinstance(value, dict) or value.get("recorded") is not True or type(value.get("version")) is not int:
            return None
        try:
            return cls.model_validate(value)
        except ValidationError:
            # Old or corrupt records cannot be interpreted as an untagged selection.
            return None


def question_scope(selection) -> dict:
    """Shared writer for the daily selection and its task-submit projection."""
    recorded = selection is not None and selection.tag_scope_recorded
    return {
        "version": 1,
        "recorded": recorded,
        "knowledge_space_ids": list(selection.knowledge_space_ids or []) if selection else [],
        "organization_knowledge_ids": list(selection.organization_knowledge_ids or []) if selection else [],
        "personal_knowledge_enabled": bool(selection and selection.personal_knowledge_enabled),
        "knowledge_space_tag_filters": (
            {str(k): v for k, v in selection.knowledge_space_tag_filters.items()} if recorded else None
        ),
    }
