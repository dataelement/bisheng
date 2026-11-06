"""Strict session inputs. Endpoint validation strips raw Pydantic input/context."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class SecretInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class SecretSaveInput(SecretInput):
    value: SecretStr = Field(repr=False)
    expected_revision: int = Field(ge=0)


class SecretDeleteInput(SecretInput):
    expected_revision: int = Field(ge=0)
    confirm_online_impact: bool = False


class SecretRebuildInput(SecretInput):
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    expected_version_id: str = Field(min_length=1, max_length=128)
    expected_config_revision: int = Field(ge=0)
    expected_route_epoch: int = Field(ge=0)
    confirm_restart: Literal[True]
