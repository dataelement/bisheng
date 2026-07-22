from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import PageData
from bisheng.knowledge.domain.constants import normalize_business_domain_code


class FileSyncCategoryRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z0-9_]{1,16}$")
    subcategory_code: str = Field(pattern=r"^[A-Z0-9_-]{1,16}$")

    @field_validator("code", "subcategory_code", mode="before")
    @classmethod
    def normalize_code(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value


class FileSyncBusinessDomainRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["fixed", "dynamic"]
    code: str | None = None

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("business domain code must be a string")
        if not value.strip():
            return None
        normalized = normalize_business_domain_code(value)
        if normalized is None:
            raise ValueError("business domain code is invalid")
        return normalized


class FileSyncTargetSpaceRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["fixed", "dynamic"]
    knowledge_id: int | None = Field(default=None, strict=True, gt=0)


class DeveloperTokenFileSyncRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: FileSyncCategoryRule
    business_domain: FileSyncBusinessDomainRule
    target_space: FileSyncTargetSpaceRule
    dynamic_source: Literal["department_id", "responsible_person_id"] | None = None


class DeveloperTokenPrincipal(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    token_id: int
    tenant_id: int
    user: UserPayload
    raw_file_sync_rule: dict | None = None


class FileSyncOptionChild(BaseModel):
    code: str
    label: str


class FileSyncOptionCategory(BaseModel):
    code: str
    label: str
    children: list[FileSyncOptionChild]


class FileSyncOptionBusinessDomain(BaseModel):
    code: str
    name: str


class FileSyncOptionKnowledgeSpace(BaseModel):
    id: int
    name: str


class DeveloperTokenFileSyncOptions(BaseModel):
    tenant_id: int
    categories: list[FileSyncOptionCategory]
    business_domains: list[FileSyncOptionBusinessDomain]
    knowledge_spaces: PageData[FileSyncOptionKnowledgeSpace]


class DeveloperTokenGlobalConfig(BaseModel):
    ip_whitelist: str = ""
    rate_limit_per_minute: int | None = None


class DeveloperTokenListQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=200)
    keyword: str | None = None
    tenant_id: int | None = None
    user_id: int | None = None
    enabled: bool | None = None


class DeveloperTokenRouteRule(BaseModel):
    match_type: str = ""
    method: str | None = None
    path: str = ""


class DeveloperTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    user_id: int
    department_id: int | None = None
    dept_id: str | None = None
    enabled: bool = True
    override_ip_whitelist: bool = False
    ip_whitelist: str | None = ""
    override_rate_limit: bool = False
    rate_limit_per_minute: int | None = None
    route_whitelist: list[DeveloperTokenRouteRule] | None = None
    file_sync_rule: DeveloperTokenFileSyncRule | None = None


class DeveloperTokenUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    user_id: int | None = None
    department_id: int | None = None
    dept_id: str | None = None
    enabled: bool | None = None
    override_ip_whitelist: bool | None = None
    ip_whitelist: str | None = None
    override_rate_limit: bool | None = None
    rate_limit_per_minute: int | None = None
    route_whitelist: list[DeveloperTokenRouteRule] | None = None
    file_sync_rule: DeveloperTokenFileSyncRule | None = None


class DeveloperTokenRead(BaseModel):
    id: int
    tenant_id: int
    tenant_name: str | None = None
    user_id: int
    user_name: str | None = None
    name: str
    token_prefix: str
    enabled: bool
    override_ip_whitelist: bool
    override_rate_limit: bool
    rate_limit_per_minute: int | None = None
    route_rule_count: int = 0
    file_sync_rule: DeveloperTokenFileSyncRule | None = None
    last_used_time: datetime | None = None
    last_used_ip: str | None = None
    created_by: int | None = None
    updated_by: int | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None


class DeveloperTokenDetail(DeveloperTokenRead):
    ip_whitelist: str | None = None
    route_whitelist: list[DeveloperTokenRouteRule] = Field(default_factory=list)


class DeveloperTokenCreateResponse(BaseModel):
    token: DeveloperTokenRead
    plaintext_token: str


class DeveloperTokenSecretResponse(BaseModel):
    id: int
    token_prefix: str
    plaintext_token: str
