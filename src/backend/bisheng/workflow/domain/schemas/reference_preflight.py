"""Read-only editor preflight input; no execution or persistence fields."""

from typing import Any

from pydantic import BaseModel, Field


class WorkflowReferencePreflight(BaseModel):
    workflow_id: str = Field(min_length=1, max_length=64)
    data: dict[str, Any]
