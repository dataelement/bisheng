"""SSO realtime sync configuration model (F014-sso-org-realtime-sync)."""

from pydantic import BaseModel, Field


class WeComSSOConf(BaseModel):
    """Self-hosted WeCom SSO (F120), used only when the commercial gateway is absent.

    Credentials are NOT configured here: they are read from the single enabled
    WeCom org-sync configuration (INV-45), so login and directory sync can never
    drift apart.
    """

    state_ttl_seconds: int = Field(
        default=300,
        description=(
            "Lifetime of the one-time OAuth state kept in Redis "
            "(key: wecom_sso:state:{state}). The user must finish the WeCom "
            "authorization within this window."
        ),
    )

    allowed_return_origins: list[str] = Field(
        default_factory=list,
        description=(
            "Extra origins allowed as the post-login return target, e.g. "
            "['https://app.example.com']. The request's own origin is always "
            "accepted; anything else is refused so the callback cannot be used "
            "as an open redirect."
        ),
    )

    request_timeout_seconds: int = Field(
        default=10,
        description="Timeout for each call to the WeCom API (gettoken / getuserinfo / user/get).",
    )


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

    initial_password: str = Field(
        default="",
        description=(
            "Password given to synced users (``source`` = wecom/sso) that have none; "
            "empty disables the feature. Only empty passwords are filled — a password "
            "the user or an admin already set is never overwritten. While an account "
            "still holds this value, login fails with 10601 (password expired) and the "
            "frontend sends the user to the change-password page, so the shared initial "
            "password cannot be kept. Rotating it does not lock users who already changed."
        ),
    )

    wecom: WeComSSOConf = Field(
        default_factory=WeComSSOConf,
        description=(
            "Self-hosted WeCom SSO (F120). Only consulted when the commercial "
            "gateway is absent (``system_login_method.bisheng_pro`` is false); "
            "credentials come from the org-sync config, not from here."
        ),
    )
