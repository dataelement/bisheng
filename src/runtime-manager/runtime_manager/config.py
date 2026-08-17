"""Process configuration — environment variables only, no platform config.yaml.

The manager knows nothing about the platform database, OpenFGA or tenants
(design §4.3). Everything it needs arrives either in the intent payload or in
one of the ``RTM_*`` environment variables below, so a deployment can move the
process to another host without touching the platform.

Naming contract with the backend (design §4.2 ⑧ / K10):

===========================  =========================================
env var                      backend-side counterpart
===========================  =========================================
``RTM_HMAC_SECRET``          ``settings.app_runtime.manager_hmac_secret``
``RTM_DATA_ROOT``            ``settings.app_runtime.data_root``
``RTM_RESERVE_MB``           ``settings.app_runtime.reserve_mb``
``RTM_OVERCOMMIT_RATIO``     ``settings.app_runtime.overcommit_ratio``
``RTM_BUILD_RESERVE_MB``     ``settings.app_runtime.build_reserve_mb``
``RTM_BUILD_INDEX_URL``      ``settings.app_runtime.build_index_url``
===========================  =========================================

``RTM_DOCKER_HOST`` is the D2-A → D2-B switch: empty means the local
``/var/run/docker.sock``; pointing it at ``tcp://127.0.0.1:2375`` moves the
whole process behind ``tecnativa/docker-socket-proxy`` with **zero code
change**. That is the entire reason the docker client is funnelled through
``runtime_manager.docker_backend``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8091
DEFAULT_NETWORK = "bisheng-apps"
DEFAULT_DATA_ROOT = "/opt/bisheng/app-data"
DEFAULT_IMAGE_PREFIX = "bisheng-app"

#: Container name prefix. Also the orphan-reclaim selector (T029) and the
#: "managed by us" marker that keeps the reconciler away from foreign
#: containers running on the same daemon (114 also runs onlyoffice etc.).
CONTAINER_NAME_PREFIX = "bisheng-app-"

#: Label namespace written on every managed container. Labels are the disaster
#: recovery source of truth for the desired-state store (AC-50).
LABEL_MANAGED = "bisheng.managed"
LABEL_APP_ID = "bisheng.app.id"
LABEL_APP_SLUG = "bisheng.app.slug"
LABEL_VERSION_ID = "bisheng.version.id"
LABEL_VERSION_NO = "bisheng.version.no"
LABEL_TIER_CPU = "bisheng.tier.cpu"
LABEL_TIER_MEM_MB = "bisheng.tier.mem_mb"
LABEL_PORT = "bisheng.port"
LABEL_HEALTH_PATH = "bisheng.health.path"
LABEL_GENERATION = "bisheng.generation"


def _env_str(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None else value.strip()


def _env_int(name: str, default: int) -> int:
    raw = _env_str(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env_str(name).lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


def _env_float(name: str, default: float) -> float:
    raw = _env_str(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    """Immutable process configuration.

    Frozen on purpose: tests swap the whole object via :func:`set_config`
    instead of mutating shared state, which keeps parallel test files from
    leaking capacity / path settings into each other.
    """

    # --- transport / auth -------------------------------------------------
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    hmac_secret: str = ""
    signature_header: str = "X-Signature"

    # --- orchestration backend -------------------------------------------
    docker_host: str = ""
    network: str = DEFAULT_NETWORK

    # --- storage ----------------------------------------------------------
    data_root: Path = Path(DEFAULT_DATA_ROOT)

    # --- capacity admission (D11) ----------------------------------------
    reserve_mb: int = 2048
    overcommit_ratio: float = 0.8
    build_reserve_mb: int = 2048

    # --- build (D3) -------------------------------------------------------
    build_index_url: str = ""
    build_trusted_host: str = ""
    image_prefix: str = DEFAULT_IMAGE_PREFIX
    image_retention: int = 2  # current + previous (AC-21 grace retirement)
    build_timeout_seconds: int = 1800

    # --- lifecycle / probe (D4) ------------------------------------------
    retire_grace_seconds: int = 30
    reconcile_interval_seconds: int = 15
    #: Whether the process runs the reconcile loop. Always on in production (it
    #: is the AC-20 self-healing mechanism); off in the unit suite, which drives
    #: ``reconcile_once()`` by hand so nothing races the assertions.
    reconcile_enabled: bool = True
    probe_timeout_seconds: int = 90
    probe_interval_seconds: float = 1.0
    stop_timeout_seconds: int = 10
    log_max_size: str = "10m"
    log_max_file: str = "3"

    @property
    def apps_root(self) -> Path:
        """Per-app host volumes: ``{data_root}/apps/{app_id}/db`` → ``/data``."""
        return self.data_root / "apps"

    @property
    def state_dir(self) -> Path:
        return self.data_root / "state"

    @property
    def state_path(self) -> Path:
        return self.state_dir / "desired-state.json"

    @property
    def build_root(self) -> Path:
        return self.data_root / "builds"

    def app_data_dir(self, app_id: str) -> Path:
        """Host side of the only writable persistent path of an instance."""
        return self.apps_root / app_id / "db"

    def with_overrides(self, **kwargs) -> Config:
        return replace(self, **kwargs)


def load_config() -> Config:
    """Build a :class:`Config` from the ``RTM_*`` environment variables."""
    return Config(
        host=_env_str("RTM_HOST", DEFAULT_HOST),
        port=_env_int("RTM_PORT", DEFAULT_PORT),
        hmac_secret=_env_str("RTM_HMAC_SECRET"),
        signature_header=_env_str("RTM_SIGNATURE_HEADER", "X-Signature") or "X-Signature",
        docker_host=_env_str("RTM_DOCKER_HOST"),
        network=_env_str("RTM_NETWORK", DEFAULT_NETWORK) or DEFAULT_NETWORK,
        data_root=Path(_env_str("RTM_DATA_ROOT", DEFAULT_DATA_ROOT) or DEFAULT_DATA_ROOT),
        reserve_mb=_env_int("RTM_RESERVE_MB", 2048),
        overcommit_ratio=_env_float("RTM_OVERCOMMIT_RATIO", 0.8),
        build_reserve_mb=_env_int("RTM_BUILD_RESERVE_MB", 2048),
        build_index_url=_env_str("RTM_BUILD_INDEX_URL"),
        build_trusted_host=_env_str("RTM_BUILD_TRUSTED_HOST"),
        image_prefix=_env_str("RTM_IMAGE_PREFIX", DEFAULT_IMAGE_PREFIX) or DEFAULT_IMAGE_PREFIX,
        image_retention=_env_int("RTM_IMAGE_RETENTION", 2),
        build_timeout_seconds=_env_int("RTM_BUILD_TIMEOUT_SECONDS", 1800),
        retire_grace_seconds=_env_int("RTM_RETIRE_GRACE_SECONDS", 30),
        reconcile_interval_seconds=_env_int("RTM_RECONCILE_INTERVAL_SECONDS", 15),
        reconcile_enabled=_env_bool("RTM_RECONCILE_ENABLED", True),
        probe_timeout_seconds=_env_int("RTM_PROBE_TIMEOUT_SECONDS", 90),
        probe_interval_seconds=_env_float("RTM_PROBE_INTERVAL_SECONDS", 1.0),
        stop_timeout_seconds=_env_int("RTM_STOP_TIMEOUT_SECONDS", 10),
        log_max_size=_env_str("RTM_LOG_MAX_SIZE", "10m") or "10m",
        log_max_file=_env_str("RTM_LOG_MAX_FILE", "3") or "3",
    )


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def set_config(config: Config | None) -> None:
    """Test / bootstrap seam. Passing ``None`` re-reads the environment."""
    global _config
    _config = config
