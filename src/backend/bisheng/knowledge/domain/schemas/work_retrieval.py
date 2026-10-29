"""Bounded retrieval inputs shared by signed-in workspace clients."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class WorkRetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    space_ids: list[Annotated[int, Field(strict=True, gt=0)]] = Field(min_length=1, max_length=50)
