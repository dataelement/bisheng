"""App-factory runtime layer configuration (F054 design K12 / D1 / D5 / D11).

``app_runtime:`` is a **process-level** ``config.yaml`` key (restart to change),
*not* DB hot config: it describes the deployment shape, exactly like
``multi_tenant.enabled`` and F049's ``open_platform.enabled``. Putting it in
``initdb_config`` would give it a 100 s Redis cache and tenant-preference
semantics — wrong on both counts for "is the runtime layer installed on this
host".

Three-stage propagation: ``Settings.app_runtime`` → ``GET /api/v1/env``
(``app_runtime_enabled``, anonymously readable) → both SPAs. The env stage is
what lets platform and client tell "the layer is not installed" apart from "the
app does not exist" (AC-30 / AC-62); without it the entry path degrades to a
404.

Sibling, not sub-key, of ``open_platform`` (F049). The two switches are
independent and any combination must boot (AC-61) — do not merge them.

**Deployment order** (design pit 23): ``load_settings_from_yaml`` raises
``KeyError`` on an unknown top-level key, so a config.yaml carrying
``app_runtime:`` in front of code that knows it makes the backend refuse to
start. Ship the code first, add the key second, restart third.

Secrets (``manager_hmac_secret`` / ``proxy_hmac_secret`` / ``obo_secret``) come
from ``!env`` or the Fernet-encrypted YAML — never a literal (C6). An empty
secret is a **fail-closed** signal for the HMAC verifiers, not "auth off".
"""

from pydantic import BaseModel, Field


class AppRuntimeConf(BaseModel):
    """``app_runtime:`` — the app-factory runtime layer of this deployment."""

    enabled: bool = Field(
        default=False,
        description="Whether the app factory runtime layer (runtime-manager + app-proxy) is deployed here",
    )

    # --- runtime-manager RPC (design D1) ---------------------------------
    manager_base_url: str = Field(
        default="http://127.0.0.1:8091",
        description="runtime-manager base URL; loopback in the systemd shape, service name under compose",
    )
    manager_hmac_secret: str = Field(
        default="",
        description="Shared HMAC secret for backend → runtime-manager. Empty means fail-closed, not 'unsigned'",
    )

    # --- app-proxy ↔ backend internal authorization (design D6) ----------
    proxy_hmac_secret: str = Field(
        default="",
        description="Shared HMAC secret for app-proxy → backend internal authorize endpoint",
    )
    obo_secret: str = Field(
        default="",
        description=(
            "Signing key of the on-behalf-of token injected into apps. MUST differ from settings.jwt_secret — "
            "sharing them would let an OBO token be replayed as a platform session cookie (AC-34)"
        ),
    )
    obo_ttl_seconds: int = Field(default=900, ge=60, description="OBO token lifetime in seconds")
    entry_base_url: str = Field(
        default="",
        description="External base URL of the entry (used to render /apps/{slug} links, QR codes); empty = derive from request",
    )
    ws_max_lifetime_seconds: int = Field(
        default=28800,
        ge=60,
        description="Hard cap on one proxied WebSocket connection's authorized lifetime (deferred wave)",
    )

    # --- capacity admission & storage (design D10 / D11) -----------------
    data_root: str = Field(
        default="/opt/bisheng/app-data",
        description="Host directory holding per-app volumes; local disk only — SQLite WAL must not sit on network storage (K6)",
    )
    reserve_mb: int = Field(
        default=2048,
        ge=0,
        description="Memory held back from MemAvailable before admitting a start (gate ①)",
    )
    overcommit_ratio: float = Field(
        default=0.8,
        gt=0,
        le=1,
        description="Fraction of total memory / nproc that committed limits may reach (gate ②)",
    )
    build_reserve_mb: int = Field(
        default=2048,
        ge=0,
        description="Memory a build needs to pass admission; builds go through the same gate (K2)",
    )
    build_index_url: str = Field(
        default="",
        description="Package index injected as a build arg (PIP_INDEX_URL); empty = image default",
    )
