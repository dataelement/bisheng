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
