"""Open platform switch + open API auth tuning (F049 design D9 / K8).

Both are **process-level** ``config.yaml`` keys (restart to change), *not* DB
hot config: they describe the deployment shape, exactly like
``multi_tenant.enabled``. Three-stage propagation: ``Settings.open_platform``
→ ``GET /api/v1/env`` (``open_platform_enabled``) → front-end ``appConfig``.

Deployment order pitfall (design pit 22): ``load_settings_from_yaml`` rejects
unknown top-level keys, so ship the code first, then add ``open_platform:`` /
``open_api:`` to ``config.yaml``, then restart.
"""

from pydantic import BaseModel, Field, field_validator


class OpenPlatformConf(BaseModel):
    """``open_platform:`` — gates only the local-dev-toolkit scopes and the
    connect-info panel (AC-13 / AC-49); the service-account module is always on."""

    enabled: bool = Field(default=False, description="Whether the open platform (F051-F053 surfaces) is deployed")


class OpenApiConf(BaseModel):
    """``open_api:`` — tuning knobs of the credential validation path (design D2)."""

    service_account_idle_days: int = Field(
        default=90,
        ge=1,
        description="Days without a call after which a service account is flagged idle in the list (AC-42)",
    )
    credential_cache_ttl_seconds: int = Field(
        default=3,
        ge=0,
        description="Redis positive-cache TTL for validated credentials; hard-capped at 5 (INV-28 five-second bound)",
    )

    @field_validator("credential_cache_ttl_seconds")
    @classmethod
    def _cap_ttl(cls, value: int) -> int:
        # The revoke/disable/delete path invalidates actively; the TTL only
        # covers the multi-node "delete raced with a request" window, so it may
        # never exceed the 5-second contract. Clamp instead of failing startup.
        return min(value, 5)
