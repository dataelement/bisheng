"""Display metadata stored with a workbench user question."""

import json
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class ComposerReference(BaseModel):
    """A resource label captured as it appeared when the user sent the question."""

    kind: Literal["skill", "tool", "space"]
    label: str
    offset: int = Field(ge=0, strict=True, description="Position in the question in UTF-16 code units")
    is_tag: Literal[True] | None = None

    @model_validator(mode="after")
    def validate_tag_kind(self) -> Self:
        if self.is_tag and self.kind != "space":
            raise ValueError("Tag references must use the space kind")
        return self


def serialize_user_question(
    question: str | None,
    files: list[dict] | None,
    composer_references: list[ComposerReference] | None,
) -> str:
    """Keep display references alongside the same plain query used by the runtime."""
    payload = {"query": question or "", "files": files or []}
    if composer_references:
        payload["composer_references"] = [reference.model_dump(exclude_none=True) for reference in composer_references]
    return json.dumps(payload, ensure_ascii=False)
