"""Multi-tenant configuration model."""

from pydantic import BaseModel, Field


class MultiTenantConf(BaseModel):
    """Multi-tenant configuration."""

    enabled: bool = Field(default=False, description='Whether to enable multi-tenancy')
    default_tenant_code: str = Field(default='default', description='Default tenant code')
