from datetime import datetime

from pydantic import BaseModel, Field


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
    last_used_time: datetime | None = None
    last_used_ip: str | None = None
    created_by: int | None = None
    updated_by: int | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None


class DeveloperTokenDetail(DeveloperTokenRead):
    ip_whitelist: str | None = None


class DeveloperTokenCreateResponse(BaseModel):
    token: DeveloperTokenRead
    plaintext_token: str


class DeveloperTokenSecretResponse(BaseModel):
    id: int
    token_prefix: str
    plaintext_token: str
