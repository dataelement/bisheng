"""Shared execution bounds; destinations and credentials are never inputs."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

TOOL_CODE_PATTERN = r"[A-Za-z0-9_-]{1,125}"
ToolCode = Annotated[str, Field(pattern=f"^{TOOL_CODE_PATTERN}$")]


class ToolLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    timeout_seconds: int = Field(default=30, ge=1, le=60)
    max_input_bytes: int = Field(default=65536, ge=1, le=65536)
    max_output_bytes: int = Field(default=1048576, ge=1, le=1048576)
    max_concurrency: int = Field(default=4, ge=1, le=16)


class ToolInvocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    arguments: dict
