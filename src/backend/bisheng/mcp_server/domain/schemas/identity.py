from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from bisheng.common.dependencies.user_deps import UserPayload


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class McpIdentityRequest(StrictRequest):
    """工具身份由认证 Token 提供, 请求只接收业务参数。"""


@dataclass(frozen=True)
class McpExecutionIdentity:
    user: UserPayload
    tenant_id: int
    token_id: int
    token_user_id: int
    token_tenant_id: int
