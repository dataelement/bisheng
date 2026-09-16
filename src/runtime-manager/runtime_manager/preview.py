"""Approval-time preview instances (F055 AC-26 / AC-27 / AC-28 / AC-29).

An approver asks to try the version that is waiting to go live. What they get
is a **throwaway instance of the same image**, addressed by a preview session
id rather than by the application's id — and that separation is the whole
design:

* **It never touches the application's own instance.** The desired-state store
  is keyed by ``app_id``; a preview writes no record there at all. So a preview
  of version 7 while version 6 is serving cannot replace, stop, or race the
  running container, and the reconciler — which only ever looks at
  ``bisheng.managed=true`` — never sees it.
* **It therefore consumes no instance slot** (AC-26 「不占应用运行实例名额」).
  ``store.committed()`` sums the records, and a preview has none, so neither
  the capacity arithmetic nor ``capacity.instances`` counts it. Host capacity
  is still checked before starting one: the memory is real even when the quota
  is not charged.
* **Its database is a tmpfs, not the app's volume** (AC-29). The approver may
  write test data; it dies with the container and can never reach production.
  ``mode=1777`` for the same reason :mod:`runtime_manager.probe` needs it — the
  image runs as a non-root user and a default tmpfs is root-owned 0755, so the
  app cannot create ``/data/app.db`` and exits 1 on start-up.

Unlike :meth:`runtime_manager.probe.ProbeService.probe_image`, which removes
its container in a ``finally`` block, a preview **stays up** until the platform
reclaims it: approval reaching a terminal state, the approver pressing 「回收」,
or the deployment's timeout sweep. The container name is derived from the
session id, so a manager restart does not lose the ability to reclaim one —
there is no state file to consult.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from runtime_manager.admission import AdmissionService, Tier
from runtime_manager.config import (
    LABEL_APP_ID,
    LABEL_HEALTH_PATH,
    LABEL_MANAGED,
    LABEL_PORT,
    LABEL_PREVIEW_EXPIRES_AT,
    LABEL_PREVIEW_SESSION,
    LABEL_VERSION_ID,
    PREVIEW_MANAGED_VALUE,
    PREVIEW_NAME_PREFIX,
    Config,
)
from runtime_manager.docker_backend import DockerBackend, get_docker_backend
from runtime_manager.errors import CapacityExhaustedError, InvalidRequestError, NotFoundError, ProbeFailedError

logger = logging.getLogger(__name__)

MIB = 1024 * 1024
NANO = 1_000_000_000

#: A session id is a URL segment on ``/apps/preview/{session}`` and a container
#: name suffix, so it is validated here rather than trusted from the payload.
SESSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")

PHASE_RUNNING = "running"


@dataclass(frozen=True)
class PreviewOutcome:
    instance_id: str
    upstream: str
    phase: str = PHASE_RUNNING

    def to_response(self) -> dict[str, Any]:
        return {"instance_id": self.instance_id, "upstream": self.upstream, "phase": self.phase}


def preview_container_name(session_id: str) -> str:
    """Deterministic from the session id — reclaim needs no stored state."""
    return f"{PREVIEW_NAME_PREFIX}{session_id}"


def build_preview_payload(
    config: Config,
    *,
    session_id: str,
    app_id: str,
    version_id: str,
    image_ref: str,
    tier: Tier,
    port: int,
    health_path: str,
    env: dict[str, str],
    expires_at: int = 0,
) -> dict[str, Any]:
    """The Docker Engine create body for a preview — the cage, one notch tighter.

    Differences from :func:`runtime_manager.lifecycle.build_container_payload`,
    each load bearing:

    * ``Binds`` is **absent** and ``/data`` is a tmpfs — AC-29's temporary empty
      database. A preview that bind-mounted the app's volume would let a trial
      run write production data, which is the exact thing the AC forbids.
    * ``RestartPolicy`` is ``no``. A preview that resurrected itself after the
      platform reclaimed it would be an instance nobody can account for.
    * ``LABEL_MANAGED`` is ``preview``, not ``true``, so the reconciler's
      ``bisheng.managed=true`` filter cannot see it — neither to adopt it into
      the desired state nor to reclaim it as an orphan.
    * No ``Healthcheck``: nothing reconciles a preview, so a health verdict
      would have no reader; readiness is decided once, by the start probe.
    * It carries its own **deadline** as a label. Nothing else in this process
      remembers a preview, and the platform is not allowed a resident worker
      for the app factory (F054 AC-59) — so the container is the only place the
      expiry can live where it will still be read after either side restarts.
    """
    return {
        "Image": image_ref,
        "Env": [f"{key}={value}" for key, value in sorted(env.items())],
        "ExposedPorts": {f"{port}/tcp": {}},
        "Labels": {
            LABEL_MANAGED: PREVIEW_MANAGED_VALUE,
            LABEL_PREVIEW_SESSION: session_id,
            LABEL_APP_ID: app_id,
            LABEL_VERSION_ID: version_id,
            LABEL_PORT: str(port),
            LABEL_HEALTH_PATH: health_path,
            LABEL_PREVIEW_EXPIRES_AT: str(int(expires_at or 0)),
        },
        "HostConfig": {
            "NanoCpus": round(tier.cpu * NANO),
            "Memory": tier.mem_mb * MIB,
            "MemorySwap": tier.mem_mb * MIB,
            "ReadonlyRootfs": True,
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=64m", "/data": "rw,size=64m,mode=1777"},
            "SecurityOpt": ["no-new-privileges:true"],
            "PortBindings": {},
            "PublishAllPorts": False,
            "NetworkMode": config.network,
            "RestartPolicy": {"Name": "no"},
            "LogConfig": {
                "Type": "json-file",
                "Config": {"max-size": config.log_max_size, "max-file": config.log_max_file},
            },
        },
    }


class PreviewService:
    """Start, address and reclaim one approver's temporary instance."""

    def __init__(
        self,
        config: Config,
        docker: DockerBackend | None = None,
        admission: AdmissionService | None = None,
        prober: Any | None = None,
    ) -> None:
        self._config = config
        self._docker = docker or get_docker_backend()
        self._admission = admission or AdmissionService(config)
        self._prober = prober

    def _get_prober(self):
        if self._prober is None:
            from runtime_manager.probe import ProbeService

            self._prober = ProbeService(self._config, docker=self._docker)
        return self._prober

    # -- start -------------------------------------------------------------
    def start(
        self,
        *,
        session_id: str,
        app_id: str,
        version_id: str,
        image_ref: str,
        tier: Tier,
        port: int = 8080,
        health_path: str = "/",
        env: dict[str, str] | None = None,
        expires_at: int = 0,
        timeout: float | None = None,
    ) -> PreviewOutcome:
        """Bring one preview up and answer with its bridge address.

        Capacity is evaluated first and a refusal raises ``capacity_exhausted``
        — the same answer a deploy gets, so the platform's copy ("运行环境容量
        不足") does not need a second vocabulary for previews. A failed probe
        tears the container down before raising: a half-started preview holds
        memory nothing will ever reclaim, because no record of it exists.
        """
        self._require_session(session_id)
        if not image_ref:
            raise InvalidRequestError("a preview needs the image_ref of the version to try")

        verdict = self._admission.evaluate(tier)
        if not verdict.admitted:
            raise CapacityExhaustedError(
                verdict.message or verdict.reason,
                reason=verdict.reason,
                snapshot=verdict.snapshot,
            )

        name = preview_container_name(session_id)
        # Re-raising a preview onto a name that already exists is a legitimate
        # retry (the first attempt failed after create, the platform asks
        # again), so the stale body goes first rather than colliding.
        self._force_remove(name)
        payload = build_preview_payload(
            self._config,
            session_id=session_id,
            app_id=app_id,
            version_id=version_id,
            image_ref=image_ref,
            tier=tier,
            port=port,
            health_path=health_path,
            env=dict(env or {}),
            expires_at=expires_at,
        )

        container_id = self._docker.create_container(name, payload)
        self._docker.start_container(container_id)
        outcome = self._get_prober().wait_ready(
            container_id,
            port,
            health_path,
            timeout=timeout if timeout is not None else self._config.probe_timeout_seconds,
        )
        if not outcome.ready:
            self._force_remove(container_id)
            raise ProbeFailedError(
                outcome.reason or "the preview instance did not become ready in time",
                app_id=app_id,
                version_id=version_id,
            )

        address = self._address(container_id)
        if not address:
            self._force_remove(container_id)
            raise ProbeFailedError(
                "the preview instance has no address on the application network",
                app_id=app_id,
                version_id=version_id,
            )
        logger.info("preview %s up for app %s version %s at %s", session_id, app_id, version_id, address)
        return PreviewOutcome(instance_id=container_id, upstream=f"http://{address}:{port}")

    # -- route -------------------------------------------------------------
    def route(self, session_id: str) -> dict[str, Any]:
        """``{upstream, version_id, generation}``, or 404 once it is gone.

        ``generation`` is always 0: a preview is never switched in place — a
        new trial is a new session — so the app-proxy's cache-invalidation
        signal has nothing to count. The field is present because the proxy's
        route shape is one shape.
        """
        self._require_session(session_id)
        info = self._inspect(preview_container_name(session_id))
        if info is None or not bool((info.get("State") or {}).get("Running")):
            raise NotFoundError(f"no preview instance is running for session {session_id}")
        labels = (info.get("Config") or {}).get("Labels") or {}
        address = self._address_from(info)
        port = int(labels.get(LABEL_PORT) or 8080)
        if not address:
            raise NotFoundError(f"preview {session_id} has no address on the application network")
        return {
            "upstream": f"http://{address}:{port}",
            "version_id": labels.get(LABEL_VERSION_ID) or "",
            "generation": 0,
        }

    # -- stop --------------------------------------------------------------
    def stop(self, session_id: str) -> dict[str, Any]:
        """Reclaim one preview. Idempotent: reclaiming a gone preview is a success.

        That matters more here than elsewhere — three independent triggers
        (terminal approval, the approver's button, the timeout sweep) can all
        fire for the same session, and two of them arriving second must not
        look like a failure to the platform.
        """
        self._require_session(session_id)
        name = preview_container_name(session_id)
        existed = self._inspect(name) is not None
        self._force_remove(name)
        if existed:
            logger.info("preview %s reclaimed", session_id)
        return {"reclaimed": existed}

    # -- sweep -------------------------------------------------------------
    def reclaim_expired(self, *, now: float | None = None) -> list[str]:
        """Remove every preview whose deadline has passed; answer their session ids.

        Driven by the reconcile pass rather than by a timer of its own: that
        loop already runs every 15 s, already reads the daemon, and already
        survives a restart — three properties a second scheduler would have to
        re-earn. A preview with **no** deadline label (an older container, or
        one started before this field existed) is left alone: reclaiming on a
        missing value would kill a live trial for want of a label.
        """
        moment = time.time() if now is None else now
        reclaimed: list[str] = []
        try:
            rows = self._docker.list_containers(
                all_states=True, filters={"label": [f"{LABEL_MANAGED}={PREVIEW_MANAGED_VALUE}"]}
            )
        except Exception as exc:
            logger.warning("preview sweep skipped: cannot read the orchestration backend: %s", exc)
            return reclaimed

        for row in rows:
            names = row.get("Names") or []
            name = str(names[0]).lstrip("/") if names else str(row.get("Name") or "").lstrip("/")
            if not name:
                continue
            info = self._inspect(name)
            labels = ((info or {}).get("Config") or {}).get("Labels") or {}
            deadline = _as_epoch(labels.get(LABEL_PREVIEW_EXPIRES_AT))
            if deadline is None or deadline > moment:
                continue
            session_id = str(labels.get(LABEL_PREVIEW_SESSION) or "")
            logger.info("reclaiming expired preview %s (%s)", session_id or name, name)
            self._force_remove(name)
            reclaimed.append(session_id or name)
        return reclaimed

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _require_session(session_id: str) -> None:
        if not SESSION_PATTERN.match(session_id or ""):
            raise InvalidRequestError(f"illegal preview session id: {session_id!r}")

    def _inspect(self, ref: str) -> dict[str, Any] | None:
        try:
            return self._docker.inspect_container(ref)
        except Exception as exc:
            logger.debug("inspect preview %s: %s", ref, exc)
            return None

    def _address(self, ref: str) -> str:
        info = self._inspect(ref)
        return self._address_from(info) if info is not None else ""

    def _address_from(self, info: dict[str, Any]) -> str:
        networks = (info.get("NetworkSettings") or {}).get("Networks") or {}
        return (networks.get(self._config.network) or {}).get("IPAddress") or ""

    def _force_remove(self, ref: str) -> None:
        try:
            self._docker.stop_container(ref, timeout=self._config.stop_timeout_seconds)
        except Exception as exc:
            logger.debug("stop preview %s: %s", ref, exc)
        try:
            self._docker.remove_container(ref, force=True)
        except Exception as exc:
            logger.debug("remove preview %s: %s", ref, exc)


def _as_epoch(raw: Any) -> float | None:
    """Label value → epoch seconds, or ``None`` for "no deadline was recorded"."""
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None
