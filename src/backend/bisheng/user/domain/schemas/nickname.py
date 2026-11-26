"""Public nickname payload and an authenticated audit actor."""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field


class NicknameUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Keep historical storage capacity; changed values use the domain policy.
    user_name: str = Field(max_length=128)


@dataclass(frozen=True)
class NicknameActor:
    user_id: int
    user_name: str
    tenant_id: int = 1
    ip_address: str | None = None
