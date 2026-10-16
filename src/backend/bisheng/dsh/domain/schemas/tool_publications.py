"""Strict publication configuration; destinations and credentials are never inputs."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

ToolCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class ToolLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    timeout_seconds: int = Field(default=30, ge=1, le=60)
    max_input_bytes: int = Field(default=65536, ge=1, le=65536)
    max_output_bytes: int = Field(default=1048576, ge=1, le=1048576)
    max_concurrency: int = Field(default=4, ge=1, le=16)


class ToolPublicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    tool_id: int = Field(gt=0)
    enabled: bool
    limits: ToolLimits = Field(default_factory=ToolLimits)


class ToolPublication(ToolPublicationInput):
    tool_code: ToolCode
    revision: int = Field(ge=1)


class ToolInvocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    arguments: dict
