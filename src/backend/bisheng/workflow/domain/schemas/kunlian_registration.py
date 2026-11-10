"""F121 本地登记合同。"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class RegistrationScope:
    tenant_id: int
    connection_id: str
    generation: int
    consumer: str = "local"


class RegistrationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class Dependency(RegistrationContract):
    resource_type: Literal["agent", "knowledge"]
    resource_id: str = Field(min_length=1, max_length=256)
    resource_version_id: str | None = Field(default=None, max_length=256)


class Descriptor(RegistrationContract):
    workflow_id: str
    workflow_version_id: str
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    dependencies: list[Dependency]
    descriptor_version: Literal[1] = 1


class RegistrationReceipt(RegistrationContract):
    workflow_id: str = Field(min_length=1, max_length=32)
    workflow_version_id: str = Field(min_length=1, max_length=32)
    sequence: int = Field(gt=0)
    status: Literal["REGISTERED", "REMOVED", "FAILED"]
    reason: Literal["DIRECTORY_WRITE_FAILED", "RETRY_REQUIRED"] | None = None
