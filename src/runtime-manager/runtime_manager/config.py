"""Process configuration — environment variables only, no platform config.yaml.

The manager knows nothing about the platform database, OpenFGA or tenants
(design §4.3). Everything it needs arrives either in the intent payload or in
one of the ``RTM_*`` environment variables below, so a deployment can move the
process to another host without touching the platform.

Shared with the backend (design §4.2 ⑧ / K10): exactly one value, the HMAC
secret. ``RTM_HMAC_SECRET`` has to equal ``settings.app_runtime.manager_hmac_secret``
or every intent is answered 401, which the backend folds into 16121.

**Everything else here has one source and it is this file's environment.**
Capacity admission, the data root and the build's package index are decisions
only this process can make — it is the one that can see the host — so the
platform holds no copy of them. It used to: ``AppRuntimeConf`` declared
matching ``reserve_mb`` / ``overcommit_ratio`` / ``build_reserve_mb`` /
``data_root`` / ``build_index_url`` fields that nothing read, and the
deployment guide sent operators to edit them, where editing them changed
nothing. If you find yourself adding a backend-side twin for one of these,
that is the thing to avoid.

``RTM_HOST_DATA_ROOT`` exists because ``HostConfig.Binds`` is resolved by the
**dockerd that creates the container**, not by this process. In the systemd
shape the manager runs on the host and the two views of the data root are the
same path, so it may stay empty. Under docker-compose the manager is itself a
container: ``RTM_DATA_ROOT=/app-data`` is the path *inside* it, while the bind
handed to dockerd has to be the host side of that same volume — set them both
and they cannot drift. Getting this wrong is silent: dockerd happily creates a
brand-new empty directory at the container-internal path on the host, every app
starts, and its SQLite lives somewhere nobody ever looks.

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
#: Attachment bucket. A *separate* bucket from the platform's ``bisheng``
#: (pit 20): no nginx location, no anonymous policy, ever.
DEFAULT_STORAGE_BUCKET = "bisheng-apps"
DEFAULT_STORAGE_MAX_FILE_MB = 20

#: Container name prefix. Also the orphan-reclaim selector (T029) and the
#: "managed by us" marker that keeps the reconciler away from foreign
#: containers running on the same daemon (114 also runs onlyoffice etc.).
CONTAINER_NAME_PREFIX = "bisheng-app-"

#: Approval-time preview instances (F055 AC-26). A separate name space *and* a
#: separate ``bisheng.managed`` value: the reconciler filters on
#: ``bisheng.managed=true``, so a preview is invisible to it — it is neither
#: adopted into the desired state nor reclaimed as an orphan, which is what
#: makes "a preview consumes no instance slot" true rather than merely intended.
PREVIEW_NAME_PREFIX = "bisheng-preview-"
PREVIEW_MANAGED_VALUE = "preview"

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
#: Preview session this container belongs to — the only way back from a
#: container to its session after a manager restart (there is no state file).
LABEL_PREVIEW_SESSION = "bisheng.preview.session"
#: Unix epoch seconds after which the preview may be reclaimed. The deadline
#: rides on the container rather than in a platform timer because this process
#: is the one that has to be alive for the container to exist at all — and
#: because the platform image is not allowed a resident worker for the app
#: factory (F054 AC-59).
LABEL_PREVIEW_EXPIRES_AT = "bisheng.preview.expires_at"

#: Variables a deployment must set explicitly — the dataclass defaults below are
#: development conveniences, not deployment values. ``docker/verify-app-runtime-
#: compose.sh`` asserts the compose file provides every one of them, which is the
#: gate that would have caught the 3.0 compose file shipping ``APP_PROXY_*``
#: names nothing reads.
REQUIRED_ENV: tuple[str, ...] = (
    "RTM_HOST",  # default is loopback; inside a container that means "nobody can reach me"
    "RTM_PORT",
    "RTM_HMAC_SECRET",  # empty = fail closed, every intent answered 401
    "RTM_DATA_ROOT",
)

#: Additionally required when *this process itself* runs in a container, where
#: its filesystem view and the host dockerd's no longer coincide.
CONTAINERISED_REQUIRED_ENV: tuple[str, ...] = ("RTM_HOST_DATA_ROOT",)


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


def _env_path(name: str) -> Path | None:
    """Optional path variable — unset and empty both mean "not configured"."""
    raw = _env_str(name)
    return Path(raw) if raw else None


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
    #: Where *this process* reads and writes app data, build contexts and the
    #: desired-state file.
    data_root: Path = Path(DEFAULT_DATA_ROOT)
    #: The same directory as the **host** dockerd sees it. ``None`` means "the
    #: process and the daemon share one filesystem view" — true for the systemd
    #: shape and for the whole test suite. Only bind mount sources may use it;
    #: everything this process opens itself must keep using ``data_root``.
    host_data_root: Path | None = None

    # --- capacity admission (D11) ----------------------------------------
    reserve_mb: int = 2048
    overcommit_ratio: float = 0.8
    build_reserve_mb: int = 2048

    # --- build (D3) -------------------------------------------------------
    build_index_url: str = ""
    build_trusted_host: str = ""
    #: npm registry for the node20 template — the pip index's twin. Empty means
    #: the base image's default (the public registry).
    build_npm_registry: str = ""
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

    # --- attachment storage (D10, AC-45) ---------------------------------
    #: MinIO endpoint (``host:port``, no scheme). Empty = the attachment handle
    #: is not configured: it is still *injected* into every instance (the env
    #: contract must not depend on deployment state) but every call answers
    #: 503 ``storage_unavailable`` and the pre-flight names the fix.
    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_secure: bool = False
    #: Never the platform's public ``bisheng`` bucket: nginx forwards any key
    #: under ``/bisheng/`` to MinIO, so the only thing between an attachment
    #: and the internet there is the bucket policy (design pit 20).
    storage_bucket: str = DEFAULT_STORAGE_BUCKET
    #: Single-file cap, a deployment setting (AC-45). Injected as
    #: ``BISHENG_APP_STORAGE_MAX_FILE_MB`` so the SDK can refuse before sending.
    storage_max_file_mb: int = DEFAULT_STORAGE_MAX_FILE_MB
    #: Base URL at which *hosted app containers* reach this process — the value
    #: behind ``BISHENG_APP_STORAGE_ENDPOINT``. Empty = derived from
    #: ``host``/``port``, which is right for compose (``0.0.0.0`` is replaced
    #: by the service name there) and wrong for the systemd shape, where
    #: ``127.0.0.1`` is unreachable from the bridge; the pre-flight says so.
    app_facing_base_url: str = ""

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
        """Process-side view of the only writable persistent path of an instance."""
        return self.apps_root / app_id / "db"

    @property
    def host_apps_root(self) -> Path:
        """``apps_root`` as the host dockerd sees it (see ``host_data_root``)."""
        return (self.host_data_root or self.data_root) / "apps"

    def host_app_data_dir(self, app_id: str) -> Path:
        """Bind mount **source** for an instance — always a host path.

        The single caller is ``lifecycle.build_container_payload``. Anything
        that ``mkdir``s, ``chown``s or ``rmtree``s must use
        :meth:`app_data_dir` instead: those run in this process.
        """
        return self.host_apps_root / app_id / "db"

    @property
    def storage_configured(self) -> bool:
        return bool(self.minio_endpoint and self.minio_access_key and self.minio_secret_key)

    @property
    def storage_max_file_bytes(self) -> int:
        return max(self.storage_max_file_mb, 1) * 1024 * 1024

    @property
    def app_facing_base(self) -> str:
        """Where an app container dials this process (see ``app_facing_base_url``)."""
        if self.app_facing_base_url:
            return self.app_facing_base_url.rstrip("/")
        return f"http://{self.host}:{self.port}"

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
        host_data_root=_env_path("RTM_HOST_DATA_ROOT"),
        reserve_mb=_env_int("RTM_RESERVE_MB", 2048),
        overcommit_ratio=_env_float("RTM_OVERCOMMIT_RATIO", 0.8),
        build_reserve_mb=_env_int("RTM_BUILD_RESERVE_MB", 2048),
        build_index_url=_env_str("RTM_BUILD_INDEX_URL"),
        build_trusted_host=_env_str("RTM_BUILD_TRUSTED_HOST"),
        build_npm_registry=_env_str("RTM_BUILD_NPM_REGISTRY"),
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
        minio_endpoint=_env_str("RTM_MINIO_ENDPOINT"),
        minio_access_key=_env_str("RTM_MINIO_ACCESS_KEY"),
        minio_secret_key=_env_str("RTM_MINIO_SECRET_KEY"),
        minio_secure=_env_bool("RTM_MINIO_SECURE", False),
        storage_bucket=_env_str("RTM_STORAGE_BUCKET", DEFAULT_STORAGE_BUCKET) or DEFAULT_STORAGE_BUCKET,
        storage_max_file_mb=_env_int("RTM_STORAGE_MAX_FILE_MB", DEFAULT_STORAGE_MAX_FILE_MB),
        app_facing_base_url=_env_str("RTM_APP_FACING_BASE_URL"),
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
