from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from bisheng.common.dependencies.user_deps import UserPayload

ExternalAccount = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=255)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class McpIdentityRequest(StrictRequest):
    external_id: ExternalAccount


@dataclass(frozen=True)
class McpExecutionIdentity:
    user: UserPayload
    tenant_id: int
    token_id: int
    token_user_id: int
    token_tenant_id: int
