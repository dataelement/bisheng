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

import json
import os

from loguru import logger
from pydantic import BaseModel, Field, model_validator

#: Keys that used to live here and never did anything. Kept as a list so an
#: existing ``config.yaml`` carrying them gets told where the real setting is,
#: instead of pydantic silently ignoring the line and the operator concluding
#: the value simply had no effect.
_RETIRED_KEYS: dict[str, str] = {
    "reserve_mb": "RTM_RESERVE_MB",
    "overcommit_ratio": "RTM_OVERCOMMIT_RATIO",
    "build_reserve_mb": "RTM_BUILD_RESERVE_MB",
    "data_root": "RTM_DATA_ROOT",
    "build_index_url": "RTM_BUILD_INDEX_URL",
}


class AppRuntimeConf(BaseModel):
    """``app_runtime:`` — the app-factory runtime layer of this deployment."""

    @model_validator(mode="before")
    @classmethod
    def _warn_about_retired_keys(cls, data):
        """Say so when a config file still sets something only the manager reads.

        A warning rather than an error: these keys were inert, so refusing to
        boot over one would turn a stale comment into an outage. What it must
        not do is stay quiet — that is the state that had operators tuning
        capacity in a file the capacity gate never opens.
        """
        if isinstance(data, dict):
            for key in [one for one in _RETIRED_KEYS if one in data]:
                logger.warning(
                    "app_runtime.{} in config.yaml is ignored — capacity, storage and build source "
                    "belong to runtime-manager; set {} in its environment instead",
                    key,
                    _RETIRED_KEYS[key],
                )
        return data

    enabled: bool = Field(
        default=False,
        description="Whether the app factory runtime layer (runtime-manager + app-proxy) is deployed here",
    )

    # Runtime v2 identities have disjoint action sets; empty keys fail closed.
    runtime_service_keys: dict[str, dict] = Field(
        default_factory=lambda: json.loads(os.environ.get("BISHENG_RUNTIME_SERVICE_KEYS", "{}")), repr=False
    )
    runtime_audit_source_timezone: str = Field(
        default_factory=lambda: os.environ.get("BISHENG_RUNTIME_AUDIT_SOURCE_TIMEZONE") or os.environ.get("TZ") or "UTC"
    )
    runtime_host_isolation_nodes: dict[str, dict] = Field(
        default_factory=lambda: json.loads(os.environ.get("BISHENG_RUNTIME_HOST_ISOLATION_NODES") or "{}")
    )
    runtime_protocol_version: int = Field(
        default_factory=lambda: int(os.environ.get("BISHENG_RUNTIME_PROTOCOL_VERSION", "2")),
        ge=2,
        le=2,
        validate_default=True,
    )
    runtime_payload_key: str = Field(
        default_factory=lambda: os.environ.get("BISHENG_RUNTIME_PAYLOAD_KEY", ""), repr=False
    )
    runtime_control_key_id: str = Field(default_factory=lambda: os.environ.get("BISHENG_RUNTIME_CONTROL_KEY_ID", ""))
    runtime_control_secret: str = Field(
        default_factory=lambda: os.environ.get("BISHENG_RUNTIME_CONTROL_SECRET", ""), repr=False
    )
    runtime_default_node_id: str = Field(default_factory=lambda: os.environ.get("BISHENG_RUNTIME_NODE_ID", ""))
    runtime_platform_base_url: str = Field(
        default_factory=lambda: os.environ.get("BISHENG_RUNTIME_PLATFORM_BASE_URL", "")
    )
    runtime_offline: bool = Field(
        default_factory=lambda: os.environ.get("BISHENG_RUNTIME_OFFLINE", "true").lower() not in {"0", "false", "no"}
    )
    artifact_max_mb: int = Field(default=2048, ge=1)
    snapshot_max_mb: int = Field(default=10240, ge=1)
    storage_max_file_mb: int = Field(default=20, ge=1)
    runtime_task_timeout_seconds: int = Field(
        default_factory=lambda: int(os.environ.get("BISHENG_RUNTIME_TASK_TIMEOUT_SECONDS", "1800")), ge=1
    )
    runtime_diagnostic_days: int = Field(default=7, ge=1)
    runtime_node_max_age_seconds: int = Field(default=15, ge=1)

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
    # AC-38 access records: repeat entries by the same visitor into the same
    # app inside this window are one record. 30 minutes is F056 design D7's
    # value (spec 决议-2: aligned with a session, so a refresh is not a visit);
    # the first F054 draft said 300 s — that number is superseded, not a typo.
    access_log_merge_window_seconds: int = Field(
        default=1800,
        ge=1,
        description="Merge window of hosted-app access records in seconds (Redis app_access:{app_id}:{user_id} TTL)",
    )

    # --- capacity admission, storage and build source ---------------------
    # Deliberately absent. ``reserve_mb`` / ``overcommit_ratio`` /
    # ``build_reserve_mb`` / ``data_root`` / ``build_index_url`` used to be
    # declared here, mirroring the runtime-manager's own settings — and nothing
    # in this process ever read one of them. Capacity admission, the app data
    # directory and the build's package index all belong to that process, which
    # takes them from ``RTM_*`` environment variables and never asks the
    # platform. A second copy here could only ever be a copy that drifts, and
    # it did worse than drift: the deployment guide taught operators to change
    # these values in ``config.yaml``, where changing them does nothing at all.
    # See ``runtime_manager/config.py`` for the variables that are real.

    # --- publish pipeline (F055 design D2 / D11) -------------------------
    # These three are the package gates. They are deployment configuration
    # rather than backend constants for one concrete reason: F053 AC-32 makes
    # the CLI refuse an oversized package *before* uploading, "according to the
    # limits of this deployment" — it reads them from
    # ``GET /api/v2/apps/deploy-limits``. Leave them as constants and the CLI
    # can only hardcode 50 MiB, i.e. exactly the two-sources-of-one-contract
    # drift this switch exists to avoid.
    max_package_mb: int = Field(
        default=50,
        ge=1,
        description="Upload size ceiling of an application package in MB (16201)",
    )
    max_unpacked_mb: int = Field(
        default=200,
        ge=1,
        description="Total unpacked size ceiling in MB — the tar-bomb gate (16201)",
    )
    max_package_entries: int = Field(
        default=20000,
        ge=1,
        description="Entry-count ceiling of an application package — the many-tiny-files gate (16201)",
    )
    default_tiers: dict | None = Field(
        default=None,
        description=(
            "Factory resource-tier specs, overriding app_runtime/domain/constants.py DEFAULT_TIERS at seed time "
            "(AC-44). Shape: {code: {name, cpu_millicores, memory_mb, description?, sort_order?}}. "
            "Seeding is idempotent by code, so this only affects a deployment that has not been seeded yet — "
            "a machine short on memory (114) must set it before the first boot that seeds tiers"
        ),
    )
    preview_ttl_days: int = Field(
        default=7,
        ge=1,
        description="Lifetime of a reviewer's temporary preview instance in days (deferred wave)",
    )
