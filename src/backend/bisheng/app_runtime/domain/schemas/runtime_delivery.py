"""Validated environment catalog and execution inputs; no engine-specific controls."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DIGEST = r"^sha256:[0-9a-f]{64}$"


class PlatformEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime_image: str = Field(min_length=1, max_length=512)
    runtime_digest: str = Field(pattern=DIGEST)
    runtime_image_id: str = Field(pattern=DIGEST)
    preparer_image: str = Field(min_length=1, max_length=512)
    preparer_digest: str = Field(pattern=DIGEST)
    preparer_image_id: str = Field(pattern=DIGEST)
    abi: str = Field(min_length=1, max_length=128)
    toolchain: dict[str, str]
    uid: int = Field(default=10001, ge=1)
    gid: int = Field(default=10001, ge=1)

    @model_validator(mode="after")
    def matching_digests(self):
        if (
            self.runtime_image.rsplit("@", 1)[-1] != self.runtime_digest
            or self.preparer_image.rsplit("@", 1)[-1] != self.preparer_digest
        ):
            raise ValueError("image reference digest mismatch")
        return self

    @field_validator("runtime_image", "preparer_image")
    @classmethod
    def immutable_image(cls, value):
        import re

        if not re.fullmatch(r"[A-Za-z0-9._/:-]+@sha256:[0-9a-f]{64}", value):
            raise ValueError("image must have an immutable digest reference")
        return value


class RuntimeProfileDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    revision: int = Field(ge=1)
    language: Literal["python3.11", "node20", "static"]
    contract_version: Literal[1] = 1
    official: bool = False
    platforms: dict[str, PlatformEnvironment]

    @model_validator(mode="after")
    def supported_platforms(self):
        supported = {"linux/amd64", "linux/arm64"}
        if not self.platforms or not self.platforms.keys() <= supported:
            raise ValueError("unsupported or missing target platform")
        if self.official and self.platforms.keys() != supported:
            raise ValueError("official delivery requires amd64 and arm64")
        return self


class OperationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)
    app_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,36}$")
    version_id: str = ""
    deployment_id: str = ""
    kind: Literal["prepare", "probe", "preview", "deploy", "stop", "destroy", "migrate", "restore"]
    node_id: str = Field(min_length=1, max_length=64)
    generation: int = Field(ge=1)
    owner_epoch: int = Field(ge=1)
    payload: dict = Field(default_factory=dict)


class RestoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str
    expected_current_generation: int = Field(ge=1)
    acknowledge_data_loss: bool
    idempotency_key: str = Field(min_length=1, max_length=128)


class UploadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str
    kind: Literal["source", "dependencies", "compiled", "offline", "snapshot"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    platform: str = ""
    metadata: dict = Field(default_factory=dict)


class ExecutionFactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence: int = Field(ge=1)
    node_id: str
    generation: int = Field(ge=1)
    owner_epoch: int = Field(ge=1)
    phase: Literal[
        "resolving",
        "preparing",
        "verifying",
        "ready",
        "maintenance",
        "snapshot_confirmed",
        "migrating",
        "starting",
        "serving",
        "retiring",
        "completed",
        "failed",
        "cancelled",
        "timed_out",
        "cleanup_pending",
    ]
    exec_ref: str = ""
    detail: dict = Field(default_factory=dict)


class StageAuthorizationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str = Field(min_length=1, max_length=64)
    generation: int = Field(ge=1)
    owner_epoch: int = Field(ge=1)
    phase: Literal["prepare", "probe", "preview", "maintenance", "data_write", "starting"]
    controller: dict = Field(default_factory=dict)
