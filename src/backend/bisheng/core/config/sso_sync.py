"""SSO realtime sync configuration model (F014-sso-org-realtime-sync)."""

from pydantic import BaseModel, Field


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
