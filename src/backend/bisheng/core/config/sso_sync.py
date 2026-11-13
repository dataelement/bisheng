"""SSO realtime sync configuration model (F014-sso-org-realtime-sync)."""

from ipaddress import ip_network
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from bisheng.core.config.kunlian_scope import allows_scope_claims, resolve_scope_pairs


class KunlianConf(BaseModel):
    """只声明受控配置。未就绪不允许开启昆联登录。"""

    directory_enabled: bool = False
    login_enabled: bool = False
    connection_id: str = ""
    policy_revision: int = Field(default=1, ge=1, strict=True)
    issuer: str = ""
    client_id: str = ""
    allowed_tenant_id: str = ""
    auto_onboarding_enabled: bool = Field(default=False, strict=True)
    login_scope_mode: Literal["fixed", "tenant_workspace_map", "directory_active_tenants"] = "fixed"
    tenant_workspace_allowlist: dict[str, list[str]] = Field(default_factory=dict)
    public_origin: str = ""
    redirect_uri: str = ""
    logout_redirect_uri: str = ""
    endpoint_allowlist: list[str] = Field(default_factory=list)
    approved_test_origins: list[str] = Field(default_factory=list)
    client_secret_reference: str = Field(default="", repr=False)
    sync_key_reference: str = Field(default="", repr=False)
    internal_key_id: str = ""
    internal_secret_reference: str = Field(default="", repr=False)
    trusted_gateway_networks: list[str] = Field(default_factory=list)
    csrf_secret_reference: str = Field(default="", repr=False)
    encryption_secret_reference: str = Field(default="", repr=False)
    max_directory_age_seconds: int | None = Field(default=None, gt=0)
    allowed_workspace_ids: list[str] = Field(default_factory=list)
    state_semantics_revision: str = ""
    session_max_seconds: int = Field(default=28800, gt=0, le=28800)
    introspection_timeout_seconds: float = Field(default=2, gt=0)
    http_pool_limit: int = Field(default=20, gt=0)
    sync_timeout_seconds: int = Field(default=900, gt=0)
    get_retry_budget: int = Field(default=3, ge=0, le=10)
    transaction_ttl_seconds: int = Field(default=300, gt=0)
    page_size: int = Field(default=20, ge=1, le=100)
    sync_interval_seconds: int = Field(default=300, gt=0)

    def allows_scope(self, tenant_id, workspace_id) -> bool:
        return allows_scope_claims(
            self.login_scope_mode,
            self.allowed_tenant_id,
            self.allowed_workspace_ids,
            self.tenant_workspace_allowlist,
            tenant_id,
            workspace_id,
        )

    def readiness_reasons(self, *, multi_tenant_enabled: bool) -> tuple[str, ...]:
        """只评估配置前置条件。完整目录和投影就绪由应用服务检查。"""
        reasons = []
        if not self.login_enabled:
            reasons.append("LOGIN_DISABLED")
        if not self.directory_enabled:
            reasons.append("DIRECTORY_DISABLED")
        if not multi_tenant_enabled:
            reasons.append("MULTI_TENANT_REQUIRED")
        if self.max_directory_age_seconds is None:
            reasons.append("DIRECTORY_MAX_AGE_MISSING")
        try:
            resolve_scope_pairs(
                self.login_scope_mode,
                self.allowed_tenant_id,
                self.allowed_workspace_ids,
                self.tenant_workspace_allowlist,
            )
        except ValueError:
            reasons.append("SCOPE_POLICY_INVALID")
        if self.login_scope_mode == "fixed" and (
            not self.allowed_workspace_ids or any(not value.strip() for value in self.allowed_workspace_ids)
        ):
            reasons.append("WORKSPACE_POLICY_MISSING")
        if not self.state_semantics_revision.strip():
            reasons.append("STATE_SEMANTICS_MISSING")
        required = (
            "connection_id",
            "issuer",
            "client_id",
            "public_origin",
            "redirect_uri",
            "logout_redirect_uri",
            "client_secret_reference",
            "sync_key_reference",
            "internal_key_id",
            "internal_secret_reference",
            "csrf_secret_reference",
            "encryption_secret_reference",
        )
        if any(not getattr(self, name).strip() for name in required) or (
            self.login_scope_mode == "fixed" and not self.allowed_tenant_id.strip()
        ):
            reasons.append("REGISTRATION_INCOMPLETE")
        if not self.endpoint_allowlist:
            reasons.append("ENDPOINT_ALLOWLIST_MISSING")
        if not self.trusted_gateway_networks:
            reasons.append("GATEWAY_SOURCE_POLICY_MISSING")
        else:
            try:
                for network in self.trusted_gateway_networks:
                    ip_network(network, strict=True)
            except ValueError:
                reasons.append("GATEWAY_SOURCE_POLICY_INVALID")
        try:
            origin = urlsplit(self.public_origin)
            urls = [
                urlsplit(value)
                for value in (
                    self.issuer,
                    self.public_origin,
                    self.redirect_uri,
                    self.logout_redirect_uri,
                    *self.endpoint_allowlist,
                )
            ]
            if any(
                (
                    url.scheme != "https"
                    and not (url.scheme == "http" and f"http://{url.netloc}" in self.approved_test_origins)
                )
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.fragment
                or url.query
                for url in urls
            ):
                reasons.append("HTTPS_REGISTRATION_REQUIRED")
            if (
                origin.path
                or self.public_origin != self.public_origin.lower()
                or origin.port == (443 if origin.scheme == "https" else 80)
            ):
                reasons.append("PUBLIC_ORIGIN_INVALID")
            if any((url.scheme, url.netloc) != (origin.scheme, origin.netloc) for url in urls[2:4]):
                reasons.append("CALLBACK_ORIGIN_MISMATCH")
        except ValueError:
            reasons.append("REGISTRATION_URL_INVALID")
        return tuple(reasons)


class SSOSyncConf(BaseModel):
    """Controls HMAC-authenticated Gateway callbacks that sync SSO login events
    and bulk department changes into bisheng.

    See `features/v2.5.1/014-sso-org-realtime-sync/spec.md` for the protocol.
    """

    gateway_hmac_secret: str = Field(
        default="",
        description=(
            "Shared secret for HMAC-SHA256 signing between the Gateway and "
            "bisheng, set in config.yaml and matched to the gateway. An empty "
            "value blocks all traffic on the SSO sync endpoints (fail-closed). "
            "Settings is a plain BaseModel, so there is no environment "
            "override: only config.yaml (or an !env tag inside it) is read."
        ),
    )

    signature_header: str = Field(
        default="X-Signature",
        description=(
            "HTTP header name carrying the hex-lowercase HMAC-SHA256 digest. "
            'Signing string: METHOD + "\\n" + PATH + "\\n" + raw_body.'
        ),
    )

    user_lock_ttl_seconds: int = Field(
        default=30,
        description=("Redis SETNX TTL for per-user concurrent login dedup (key: user:sso_lock:{external_user_id})."),
    )

    orphan_config_id: int = Field(
        default=9999,
        description=(
            "Fixed OrgSyncConfig id reserved for SSO realtime logs. Seeded by "
            "the F014 migration. Stable across environments so `org_sync_log` "
            "rows from Gateway-push flows can always be joined back to this "
            "synthetic config row."
        ),
    )

    kunlian: KunlianConf = Field(default_factory=KunlianConf)
