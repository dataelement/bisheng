"""昆联内部协议 DTO。秘密字段不可通过 repr 或序列化输出。"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class KunlianContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class KunlianLoginHandoff(KunlianContract):
    connection_id: str = Field(min_length=1, max_length=64)
    handoff_id: str = Field(min_length=1, max_length=64)
    expected_nonce: str = Field(min_length=1, max_length=256, exclude=True, repr=False)
    browser_binding_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    id_token: SecretStr = Field(min_length=1, exclude=True, repr=False)
    access_token: SecretStr = Field(min_length=1, exclude=True, repr=False)
    expires_in: int = Field(gt=0, le=28800)


class KunlianIdentity(KunlianContract):
    connection_id: str = Field(min_length=1, max_length=64)
    issuer: str = Field(min_length=1, max_length=2048)
    subject: str = Field(min_length=1, max_length=128)
    external_tenant_id: str = Field(min_length=1, max_length=64)
    member_id: str = Field(min_length=1, max_length=64)


class KunlianTenantMapping(KunlianContract):
    connection_id: str
    external_tenant_id: str
    local_tenant_id: int = Field(gt=0)
    revision: int = Field(ge=1)


class KunlianActionContext(KunlianContract):
    transport: Literal["HTTP", "WEBSOCKET"]
    action: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)


class KunlianSyncRequest(KunlianContract):
    connection_id: str = Field(min_length=1, max_length=64)
    trigger: Literal["LOGIN_MISSING", "MANUAL", "BEAT", "RECOVERY"]


class KunlianRuntimeStatus(KunlianContract):
    connection_id: str
    directory_status: Literal["UNINITIALIZED", "FETCHING", "PUBLISHED", "FAILED"]
    projection_status: Literal["PENDING", "SUCCEEDED", "FAILED", "UNMAPPED"]
    active_batch_id: str | None = None
    ready: bool = False
    reasons: tuple[str, ...] = ()


class KunlianLogoutAction(KunlianContract):
    kind: Literal["kunlian_logout"] = "kunlian_logout"
    method: Literal["POST"] = "POST"
    url: Literal["/api/kunlian/logout"] = "/api/kunlian/logout"
    ticket: SecretStr = Field(min_length=1, exclude=True, repr=False)


class KunlianWorkflowCause(KunlianContract):
    kind: Literal["kunlian_causal"] = "kunlian_causal"
    user_id: int = Field(gt=0, strict=True)
    tenant_id: int = Field(gt=0, strict=True)
    binding_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    session_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_id: str = Field(min_length=1, max_length=128)


@dataclass(frozen=True)
class VerifiedKunlianIdentity:
    """仅由服务端验证器构造。不作为浏览器请求体解析。"""

    identity: KunlianIdentity
    client_id: str
    sid: str
    workspace_id: str
    auth_time: int
    expires_at: int
