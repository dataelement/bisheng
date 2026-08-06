from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.developer_token.domain.file_sync_folder_path import normalize_file_sync_folder_path
from bisheng.knowledge.domain.constants import normalize_business_domain_code

FileSyncDynamicSource = Literal["department_id", "responsible_person_id"]
FileSyncFolderMode = Literal["none", "fixed", "dynamic"]
FileSyncFolderDynamicSource = Literal["department_name", "caller_main_department_name"]


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
    dynamic_source: FileSyncDynamicSource | None = None

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
    folder_id: int | None = Field(default=None, strict=True, gt=0)
    dynamic_source: FileSyncDynamicSource | None = None
    folder_mode: FileSyncFolderMode = "none"
    folder_path: str | None = None
    parent_folder_path: str | None = None
    folder_dynamic_source: FileSyncFolderDynamicSource | None = None

    @field_validator("folder_path", "parent_folder_path", mode="before")
    @classmethod
    def normalize_folder_path(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return normalize_file_sync_folder_path(value)

    @model_validator(mode="after")
    def infer_legacy_folder_mode(self):
        if self.folder_mode == "none":
            if self.folder_path:
                self.folder_mode = "fixed"
            elif self.folder_id is not None:
                self.folder_mode = "fixed"
        return self


class DeveloperTokenFileSyncRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: FileSyncCategoryRule
    business_domain: FileSyncBusinessDomainRule
    target_space: FileSyncTargetSpaceRule
    # Deprecated: migrated into per-dimension dynamic_source on read; never persisted on save.
    dynamic_source: FileSyncDynamicSource | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_dynamic_source(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        legacy = data.get("dynamic_source")
        if legacy is None:
            return data
        payload = dict(data)
        business_domain = dict(payload.get("business_domain") or {})
        target_space = dict(payload.get("target_space") or {})
        if business_domain.get("mode") == "dynamic" and business_domain.get("dynamic_source") is None:
            business_domain["dynamic_source"] = legacy
        if target_space.get("mode") == "dynamic" and target_space.get("dynamic_source") is None:
            target_space["dynamic_source"] = legacy
        payload["business_domain"] = business_domain
        payload["target_space"] = target_space
        payload["dynamic_source"] = None
        return payload


class DeveloperTokenPrincipal(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    token_id: int
    token_name: str = ""
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
    space_ids: list[int] = Field(default_factory=list)


class FileSyncTargetSpaceOption(BaseModel):
    id: int
    name: str
    selectable: bool
    has_children: bool
    business_domain_codes: list[str] = Field(default_factory=list)


class FileSyncTargetSpaceGroup(BaseModel):
    space_type: Literal["public", "department"]
    spaces: list[FileSyncTargetSpaceOption]


class FileSyncTargetSpaceGroupsPage(BaseModel):
    data: list[FileSyncTargetSpaceGroup]
    has_more: bool
    next_cursor: str | None
    page_size: int


class FileSyncTargetFolderOption(BaseModel):
    id: int
    name: str
    selectable: bool
    navigation_only: bool
    has_children: bool


class DeveloperTokenFileSyncTargetChildren(BaseModel):
    data: list[FileSyncTargetFolderOption]
    has_more: bool
    next_cursor: str | None
    page_size: int


class FileSyncTargetPathItem(BaseModel):
    id: int
    name: str


class FileSyncTargetDisplay(BaseModel):
    knowledge_id: int
    knowledge_name: str | None = None
    target_type: Literal["root", "folder"]
    folder_id: int | None = None
    folder_path: list[FileSyncTargetPathItem] = Field(default_factory=list)
    stale: bool = False


class DeveloperTokenFileSyncOptions(BaseModel):
    tenant_id: int
    user_id: int
    categories: list[FileSyncOptionCategory]
    business_domains: list[FileSyncOptionBusinessDomain]
    target_space_groups: FileSyncTargetSpaceGroupsPage


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
    file_sync_target_display: FileSyncTargetDisplay | None = None
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
