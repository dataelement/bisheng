"""Multi-tenant configuration model."""

from pydantic import BaseModel, Field


class MultiTenantConf(BaseModel):
    """Multi-tenant configuration."""

    enabled: bool = Field(default=False, description='Whether to enable multi-tenancy')
    default_tenant_code: str = Field(default='default', description='Default tenant code')
    admin_scope_ttl_seconds: int = Field(
        default=14400,
        description=(
            'v2.5.1 F019 — admin tenant-scope Redis TTL (seconds). Sliding '
            'refresh on each management API hit. Default 4h.'
        ),
    )
