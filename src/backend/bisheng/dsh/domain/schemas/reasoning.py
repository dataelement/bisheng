"""Administrator-owned effort declarations, independent of reasoning text output."""

import json
from typing import Annotated

from pydantic import Field, model_validator

from bisheng.dsh.domain.schemas.contracts import DshContract

EffortId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]


class ReasoningEffort(DshContract):
    id: EffortId
    name: str = Field(min_length=1, max_length=256)


class ReasoningDeclaration(DshContract):
    efforts: list[ReasoningEffort] = Field(min_length=1, max_length=32)
    defaultEffort: EffortId | None = None

    @model_validator(mode="after")
    def unique_default(self):
        ids = [effort.id for effort in self.efforts]
        if len(set(ids)) != len(ids) or (self.defaultEffort is not None and self.defaultEffort not in ids):
            raise ValueError("Invalid reasoning effort declaration")
        return self


def model_parameters(config: dict) -> dict:
    """Use the existing advanced-parameters editor; direct model fields win."""
    custom = config.get("user_kwargs") or {}
    if isinstance(custom, str):
        custom = json.loads(custom)
    if not isinstance(custom, dict):
        raise ValueError("Invalid model parameters")
    result = {**custom, **{key: value for key, value in config.items() if key != "user_kwargs"}}
    if "use_responses_api" in result and type(result["use_responses_api"]) is not bool:
        raise ValueError("Invalid Responses capability declaration")
    return result


def reasoning_declaration(config: dict) -> ReasoningDeclaration | None:
    params = model_parameters(config)
    if "reasoning_efforts" not in params and "reasoning_effort" not in params:
        return None
    return ReasoningDeclaration.model_validate(
        {"efforts": params.get("reasoning_efforts"), "defaultEffort": params.get("reasoning_effort")}
    )
