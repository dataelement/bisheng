"""One independently enforced monthly allowance per user/model pair."""

from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class DshModelQuotaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    model_id: int = Field(
        gt=0, le=9223372036854775807, description="BiSheng model ID; unique within this user's policy."
    )
    monthly_token_limit: int = Field(
        ge=0,
        le=9223372036854775807,
        description="Actual monthly token allowance for this model only. Zero denies new requests; admitted requests may finish.",
    )


def validate_model_configs(value: object) -> list[DshModelQuotaConfig]:
    configs = TypeAdapter(list[DshModelQuotaConfig]).validate_python(value)
    if len({item.model_id for item in configs}) != len(configs):
        raise ValueError("Each user/model pair must have exactly one configuration")
    if sum(item.monthly_token_limit for item in configs) > 9223372036854775807:
        raise ValueError("The informational allowance total exceeds int64")
    return sorted(configs, key=lambda item: item.model_id)


class DshModelQuotaPayload(TypedDict):
    model_id: int
    monthly_token_limit: int


def model_configs_payload(value: object) -> list[DshModelQuotaPayload]:
    """Serialize a validated configuration at the persistence/transport boundary."""
    return [
        {"model_id": item.model_id, "monthly_token_limit": item.monthly_token_limit}
        for item in validate_model_configs(value)
    ]


class DshModelPolicyState(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    model_id: int
    monthly_token_limit: int
    enabled: int
    version: int
    quota_epoch: int
    quota_sync_state: str
    pending_operation_id: str | None


class DshPolicySnapshot(BaseModel):
    """Transient aggregate for model listing and usage recovery, never a stored JSON policy."""

    tenant_id: int
    user_id: int
    rows: list[DshModelPolicyState]

    @property
    def model_configs(self) -> list[DshModelQuotaConfig]:
        return [
            DshModelQuotaConfig(model_id=r.model_id, monthly_token_limit=r.monthly_token_limit)
            for r in self.rows
            if r.enabled
        ]

    @property
    def allowed_model_ids(self) -> list[int]:
        return [r.model_id for r in self.rows if r.enabled]

    @property
    def monthly_token_limit(self) -> int:
        return sum(r.monthly_token_limit for r in self.rows if r.enabled)

    @property
    def version(self) -> int:
        return sum(r.version for r in self.rows)

    @property
    def quota_epoch(self) -> int:
        epochs = {r.quota_epoch for r in self.rows}
        if len(epochs) != 1:
            raise ValueError("Policy rows disagree on the recovered usage epoch")
        return next(iter(epochs))

    @property
    def quota_sync_state(self) -> str:
        return "READY" if all(r.quota_sync_state == "READY" for r in self.rows) else "PENDING"

    @property
    def pending_operation_id(self) -> str | None:
        return next((r.pending_operation_id for r in self.rows if r.pending_operation_id), None)

    def recovery_payload(self) -> dict:
        return {
            **self.model_dump(),
            "version": self.version,
            "quota_epoch": self.quota_epoch,
            "model_configs": model_configs_payload(self.model_configs),
            "pending_operation_id": self.pending_operation_id,
        }
