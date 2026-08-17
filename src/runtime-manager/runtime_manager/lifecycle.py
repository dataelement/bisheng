"""Instance lifecycle — deploy / stop / destroy (D4, D5.1, D10).

The deploy path is Dokku's CHECKS shape and the order is the design:

    admission → create the *new* instance beside the old one → readiness gate →
    switch the route (generation + 1) → retire the old one after a grace window

Two numbers in there are load bearing:

* **The grace window is 30 s and the app-proxy's route cache is 3 s.** The gap
  is the reason AC-21 does not show a 502 mid-switch: by the time the last
  proxy has forgotten the old upstream, the old container has been alive for an
  order of magnitude longer than the cache it was hiding in.
* **The readiness gate comes before the switch, not after.** A new version that
  never becomes ready must leave the previous one serving — which is why a
  failed probe here tears down what it just created and raises, instead of
  recording a broken current version.

Data lives outside the instance (AC-39): ``{data_root}/apps/{app_id}/db`` is
bind-mounted at ``/data`` and is untouched by stop, destroy, crash or rebuild.
Only ``destroy(purge_volume=True)`` — the owner's explicit delete — removes it
(AC-40). The bind is a *host* directory on purpose: the per-app SQLite runs in
WAL mode, which needs shared memory between processes and therefore must never
live on network storage (K6).
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from typing import Any, Protocol

from runtime_manager.admission import AdmissionService, Tier
from runtime_manager.api.schemas import DeployRequest
from runtime_manager.builder import DEFAULT_APP_GID, DEFAULT_APP_UID
from runtime_manager.config import (
    CONTAINER_NAME_PREFIX,
    LABEL_APP_ID,
    LABEL_APP_SLUG,
    LABEL_GENERATION,
    LABEL_HEALTH_PATH,
    LABEL_MANAGED,
    LABEL_PORT,
    LABEL_TIER_CPU,
    LABEL_TIER_MEM_MB,
    LABEL_VERSION_ID,
    LABEL_VERSION_NO,
    Config,
)
from runtime_manager.desired_state import (
    DESIRED_RUNNING,
    DESIRED_STOPPED,
    PHASE_RUNNING,
    PHASE_STOPPED,
    InstanceRecord,
    get_store,
)
from runtime_manager.docker_backend import DockerBackend, get_docker_backend
from runtime_manager.errors import CapacityExhaustedError, ProbeFailedError

logger = logging.getLogger(__name__)

MIB = 1024 * 1024
NANO = 1_000_000_000

#: Environment variable names the platform owns. An app cannot redefine these by
#: shipping them in its own env: the database URL and the base path are how the
#: cage is wired, not preferences.
RESERVED_ENV_PREFIXES = ("BISHENG_APP_", "BISHENG_PLATFORM_", "PORT")


class Prober(Protocol):
    def wait_ready(self, container: str, port: int, health_path: str, timeout: float | None = None): ...


class ThreadScheduler:
    """Delayed callback runner for the retirement grace window.

    A daemon thread rather than an event loop task: the retirement must not be
    cancelled by the request that triggered it finishing, and it must not keep
    the process alive at shutdown. If the manager dies mid-window the old
    container simply stays up until the reconciler notices it is not the current
    generation — degraded, not broken (AC-22).
    """

    def schedule(self, delay: float, fn, *args, **kwargs) -> None:
        timer = threading.Timer(delay, fn, args=args, kwargs=kwargs)
        timer.daemon = True
        timer.start()


def container_name(slug: str, version_id: str) -> str:
    """Name carries the version so old and new coexist during a switch."""
    return f"{CONTAINER_NAME_PREFIX}{slug}-{version_id[:8]}"


def start_period_seconds(tier: Tier) -> int:
    """Start-up slack by tier (D4: 20–60 s).

    Bigger tier ⇒ heavier app ⇒ slower first request, and the start period is
    what keeps a slow boot from being reported as a health failure. Bounded at
    60 s because past that it stops being "starting" and becomes "broken".
    """
    if tier.mem_mb <= 512:
        return 20
    if tier.mem_mb <= 1024:
        return 40
    return 60


def build_env(
    config: Config,
    *,
    app_id: str,
    slug: str,
    version_id: str,
    version_no: int,
    port: int,
    health_path: str,
    platform_api_base: str,
    base_path: str,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Environment contract of §4.2 ⑤ — same names ``bisheng dev`` injects.

    ``PORT`` and ``BISHENG_APP_PORT`` are both set to the manifest port and must
    stay equal; frameworks read one or the other and a disagreement produces an
    app listening where nothing dials.
    """
    env = dict(extra or {})
    env.update(
        {
            "BISHENG_APP_DB_URL": "sqlite:////data/app.db",
            "BISHENG_APP_DB_PATH": "/data/app.db",
            "BISHENG_APP_ID": app_id,
            "BISHENG_APP_SLUG": slug,
            "BISHENG_APP_VERSION": str(version_no),
            "BISHENG_APP_VERSION_ID": version_id,
            "BISHENG_PLATFORM_API_BASE": platform_api_base,
            "PORT": str(port),
            "BISHENG_APP_PORT": str(port),
            # Empty under `bisheng dev`, `/apps/{slug}` here — the name is the
            # contract, the value is environment specific (INV-32 / D5.2).
            "BISHENG_APP_BASE_PATH": base_path or f"/apps/{slug}",
            # Read by the template's HEALTHCHECK script so the probe path is
            # defined in exactly one place.
            "BISHENG_APP_HEALTH_PATH": health_path,
        }
    )
    return env


def build_container_payload(
    config: Config,
    *,
    app_id: str,
    slug: str,
    version_id: str,
    version_no: int,
    image_ref: str,
    tier: Tier,
    port: int,
    health_path: str,
    health_interval: int,
    health_timeout: int,
    health_retries: int,
    start_period: int,
    env: dict[str, str],
    generation: int,
) -> dict[str, Any]:
    """The Docker Engine ``POST /containers/create`` body — the cage, spelled out.

    Pure function on purpose: this is the artefact the security review reads and
    the unit tests assert against, so it must be derivable without a daemon.
    """
    data_dir = config.app_data_dir(app_id)
    return {
        "Image": image_ref,
        "Env": [f"{key}={value}" for key, value in sorted(env.items())],
        "ExposedPorts": {f"{port}/tcp": {}},
        "Labels": {
            LABEL_MANAGED: "true",
            LABEL_APP_ID: app_id,
            LABEL_APP_SLUG: slug,
            LABEL_VERSION_ID: version_id,
            LABEL_VERSION_NO: str(version_no),
            LABEL_TIER_CPU: str(tier.cpu),
            LABEL_TIER_MEM_MB: str(tier.mem_mb),
            LABEL_PORT: str(port),
            LABEL_HEALTH_PATH: health_path,
            LABEL_GENERATION: str(generation),
        },
        "Healthcheck": {
            "Test": ["CMD", "/usr/local/bin/bisheng-healthcheck"],
            "Interval": health_interval * NANO,
            "Timeout": health_timeout * NANO,
            "Retries": health_retries,
            "StartPeriod": start_period * NANO,
        },
        "HostConfig": {
            # AC-63 — fixed at creation, never updated in place (AC-64).
            "NanoCpus": round(tier.cpu * NANO),
            "Memory": tier.mem_mb * MIB,
            "MemorySwap": tier.mem_mb * MIB,
            # AC-17 — read-only root, one ephemeral scratch, one persistent path.
            "ReadonlyRootfs": True,
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=64m"},
            "Binds": [f"{data_dir}:/data:rw"],
            "SecurityOpt": ["no-new-privileges:true"],
            # AC-33 — never published; the bridge address is the only way in.
            "PortBindings": {},
            "PublishAllPorts": False,
            "NetworkMode": config.network,
            # AC-20 first failure class, delegated to the daemon's own backoff.
            "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
            # AC-55 retention window == this rotation window (D14-B).
            "LogConfig": {
                "Type": "json-file",
                "Config": {"max-size": config.log_max_size, "max-file": config.log_max_file},
            },
        },
    }


class LifecycleService:
    def __init__(
        self,
        config: Config,
        docker: DockerBackend | None = None,
        admission: AdmissionService | None = None,
        prober: Prober | None = None,
        scheduler: Any | None = None,
        store=None,
    ) -> None:
        self._config = config
        self._docker = docker or get_docker_backend()
        self._admission = admission or AdmissionService(config)
        self._prober = prober
        self._scheduler = scheduler or ThreadScheduler()
        self._store = store if store is not None else get_store(config)

    def _get_prober(self) -> Prober:
        if self._prober is None:
            from runtime_manager.probe import ProbeService

            self._prober = ProbeService(self._config, docker=self._docker)
        return self._prober

    # -- deploy ------------------------------------------------------------
    def deploy(self, request: DeployRequest) -> dict[str, Any]:
        config = self._config
        tier = Tier(cpu=request.tier.cpu, mem_mb=request.tier.mem)

        verdict = self._admission.evaluate(tier)
        if not verdict.admitted:
            raise CapacityExhaustedError(
                verdict.message or verdict.reason,
                reason=verdict.reason,
                snapshot=verdict.snapshot,
            )

        previous = self._store.get(request.app_id)
        generation = (previous.generation if previous else 0) + 1
        name = container_name(request.slug, request.version_id)
        health = request.health
        start_period = health.start_period or start_period_seconds(tier)

        data_dir = config.app_data_dir(request.app_id)
        data_dir.mkdir(parents=True, exist_ok=True)
        # The container runs as the non-root app user (uid/gid 10001, builder
        # DEFAULT_APP_UID/GID). This dir is bind-mounted at /data:rw and the
        # bind shadows the image's own ``chown app_user /data``, so without this
        # the app user cannot create /data/app.db — it exits 1 on start-up and
        # the deploy fails 16228, exactly as the probe did. Best-effort: a
        # daemon on a userns-remapped host may already map ownership.
        try:
            os.chown(data_dir, DEFAULT_APP_UID, DEFAULT_APP_GID)
        except (PermissionError, OSError) as exc:
            logger.warning("could not chown %s to the app user: %s", data_dir, exc)

        env = build_env(
            config,
            app_id=request.app_id,
            slug=request.slug,
            version_id=request.version_id,
            version_no=request.version_no,
            port=request.port,
            health_path=health.path,
            platform_api_base=request.platform_api_base,
            base_path=request.base_path,
            extra=request.env,
        )
        payload = build_container_payload(
            config,
            app_id=request.app_id,
            slug=request.slug,
            version_id=request.version_id,
            version_no=request.version_no,
            image_ref=request.image_ref,
            tier=tier,
            port=request.port,
            health_path=health.path,
            health_interval=health.interval,
            health_timeout=health.timeout,
            health_retries=health.retries,
            start_period=start_period,
            env=env,
            generation=generation,
        )

        self._remove_if_exists(name)
        container_id = self._docker.create_container(name, payload)
        self._docker.start_container(container_id)

        outcome = self._get_prober().wait_ready(
            container_id, request.port, health.path, timeout=config.probe_timeout_seconds
        )
        if not outcome.ready:
            # Tear down what we just made: leaving it would both hold capacity
            # and give the reconciler an instance it would keep resurrecting.
            self._force_remove(container_id)
            raise ProbeFailedError(
                outcome.reason or "the new instance did not become ready in time",
                app_id=request.app_id,
                version_id=request.version_id,
            )

        record = InstanceRecord(
            app_id=request.app_id,
            slug=request.slug,
            version_id=request.version_id,
            version_no=request.version_no,
            image_ref=request.image_ref,
            tier_cpu=tier.cpu,
            tier_mem_mb=tier.mem_mb,
            port=request.port,
            health_path=health.path,
            container_name=name,
            container_id=container_id,
            env=env,
            phase=PHASE_RUNNING,
            health="healthy",
            desired=DESIRED_RUNNING,
            generation=generation,
            retiring=[c for c in ((previous.container_name,) if previous else ()) if c and c != name],
        )
        self._store.put(record)

        for stale in record.retiring:
            logger.info(
                "app %s switched to generation %s; retiring %s in %ss",
                request.app_id,
                generation,
                stale,
                config.retire_grace_seconds,
            )
            self._scheduler.schedule(config.retire_grace_seconds, self._retire, request.app_id, stale)

        return {"instance_id": container_id, "phase": PHASE_RUNNING, "generation": generation}

    def _retire(self, app_id: str, name: str) -> None:
        """Stop and remove a superseded instance after the grace window."""
        try:
            self._force_remove(name)
        except Exception as exc:
            logger.warning("cannot retire %s: %s", name, exc)
        record = self._store.get(app_id)
        if record and name in record.retiring:
            self._store.mutate(app_id, retiring=[c for c in record.retiring if c != name])

    # -- stop / destroy ----------------------------------------------------
    def stop(self, app_id: str) -> dict[str, Any]:
        """AC-41 — reclaim the execution body, keep every byte of the data."""
        record = self._store.get(app_id)
        if record is None:
            return {"phase": PHASE_STOPPED}
        for name in [record.container_name, *record.retiring]:
            self._stop_if_exists(name)
        self._store.mutate(app_id, phase=PHASE_STOPPED, desired=DESIRED_STOPPED, health="unknown", retiring=[])
        return {"phase": PHASE_STOPPED}

    def destroy(self, app_id: str, purge_volume: bool = False) -> dict[str, Any]:
        """AC-40 — the only path that may remove data, and only when asked to."""
        record = self._store.get(app_id)
        if record is not None:
            for name in [record.container_name, *record.retiring]:
                self._force_remove(name)
            self._store.delete(app_id)
        if purge_volume:
            app_dir = self._config.apps_root / app_id
            shutil.rmtree(app_dir, ignore_errors=True)
        return {}

    # -- helpers -----------------------------------------------------------
    def _remove_if_exists(self, name: str) -> None:
        try:
            self._docker.inspect_container(name)
        except Exception:
            return
        self._force_remove(name)

    def _force_remove(self, ref: str) -> None:
        try:
            self._docker.stop_container(ref, timeout=self._config.stop_timeout_seconds)
        except Exception as exc:
            logger.debug("stop %s: %s", ref, exc)
        try:
            self._docker.remove_container(ref, force=True)
        except Exception as exc:
            logger.debug("remove %s: %s", ref, exc)

    def _stop_if_exists(self, ref: str) -> None:
        try:
            self._docker.stop_container(ref, timeout=self._config.stop_timeout_seconds)
        except Exception as exc:
            logger.debug("stop %s: %s", ref, exc)
