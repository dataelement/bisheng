"""Read side of the manager: status, logs, runtime status (AC-23 / AC-55, D14).

Three questions the platform asks and never answers itself:

* **"How is this app doing?"** — ``GET /v1/apps/{app_id}/status``. Desired state
  plus one live inspect, projected onto the form-agnostic ``phase`` vocabulary.
  The platform's ``app_instance`` row is an audit / triage copy; this is the
  answer that is true right now.
* **"What did it print?"** — ``GET /v1/apps/{app_id}/logs``. Straight from the
  daemon's ``json-file`` driver (D14-B): zero collectors, zero platform storage,
  and the retention window is literally the rotation window (10 MB × 3 per app).
  The product line is "最近的运行日志", never "所有日志" — there is no archive to
  promise.
* **"Can this host run apps at all?"** — ``GET /v1/runtime/status``. Capacity,
  the runtimes this deployment can actually build, and a pre-flight that names
  the operational mistakes which otherwise surface as an opaque failure on
  someone's first publish (missing ``bisheng-apps`` network, base image never
  pulled on an air-gapped box).

**Redaction is deliberately narrow.** The manager replaces values *the platform
injected into the instance* — nothing else. Running a general secret detector
over application output would be a promise we cannot keep and would mangle
legitimate output; leaked keys are F055's publish-time scan (D14). Both halves
of that boundary are pinned by tests.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from runtime_manager.admission import AdmissionService
from runtime_manager.auth import verify_hmac
from runtime_manager.builder import BASE_IMAGES, discover_runtimes
from runtime_manager.config import Config, get_config
from runtime_manager.desired_state import (
    PHASE_RUNNING,
    PHASE_STARTING,
    InstanceRecord,
    get_store,
    phase_for,
)
from runtime_manager.docker_backend import DockerBackend, get_docker_backend
from runtime_manager.errors import BackendUnavailableError, InvalidRequestError, NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["readonly"], dependencies=[Depends(verify_hmac)])

DEFAULT_TAIL = 500
MAX_TAIL = 5000

#: Environment names whose *values* are redacted out of log lines. Matching on
#: the name (not the value) is what keeps this a literal, explainable rule
#: instead of a heuristic that eats real output.
SENSITIVE_ENV_NAME = re.compile(
    r"(SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|SIGNATURE|API_?KEY|PRIVATE_?KEY)", re.IGNORECASE
)

#: Short values are not worth redacting and are dangerous to redact: replacing a
#: 3-character value would riddle every line with ``***``.
MIN_REDACTABLE_LENGTH = 6

REDACTED = "***"

_RELATIVE_SINCE = re.compile(r"^(\d+)\s*([smhd])$", re.IGNORECASE)
_RELATIVE_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _record_or_404(config: Config, app_id: str) -> InstanceRecord:
    record = get_store(config).get(app_id)
    if record is None:
        # Deliberately the same answer as "the app was destroyed": the manager
        # has no notion of application existence, only of declared instances.
        raise NotFoundError(f"no instance is declared for app {app_id}")
    return record


def _live_state(docker: DockerBackend, record: InstanceRecord) -> dict[str, Any] | None:
    """One inspect, or ``None`` if the execution body is simply gone.

    A backend that is *down* is a different answer from an instance that is
    *missing*, and conflating them would have the detail page report "已删除"
    every time dockerd restarts — hence the ping before giving up.
    """
    ref = record.container_id or record.container_name
    try:
        return docker.inspect_container(ref)
    except Exception as exc:
        if not _backend_reachable(docker):
            raise BackendUnavailableError(f"the orchestration backend is not reachable: {exc}")
        logger.debug("inspect %s: %s", ref, exc)
        return None


def _backend_reachable(docker: DockerBackend) -> bool:
    try:
        return bool(docker.ping())
    except Exception:
        return False


def _parse_since(raw: str | None) -> int | None:
    """``None`` | epoch seconds | ``30m`` / ``2h`` / ``7d`` → epoch seconds."""
    if raw is None or raw == "":
        return None
    text = str(raw).strip()
    if text.isdigit():
        return int(text)
    match = _RELATIVE_SINCE.match(text)
    if match:
        amount, unit = int(match.group(1)), match.group(2).lower()
        return int(time.time()) - amount * _RELATIVE_UNITS[unit]
    raise InvalidRequestError(f"cannot read 'since'={raw!r}: use epoch seconds or a relative window like 30m / 2h / 7d")


def _redactions(record: InstanceRecord) -> list[str]:
    values = [
        value
        for name, value in (record.env or {}).items()
        if value and len(value) >= MIN_REDACTABLE_LENGTH and SENSITIVE_ENV_NAME.search(name)
    ]
    # Longest first: a shorter secret that is a substring of a longer one must
    # not chop the longer one into a half-redacted line.
    return sorted(set(values), key=len, reverse=True)


def _project_phase(record: InstanceRecord, info: dict[str, Any] | None) -> tuple[str, str]:
    if info is None:
        return record.phase, record.health
    state = info.get("State") or {}
    running = bool(state.get("Running"))
    health = ((state.get("Health") or {}).get("Status") or "").strip() or "unknown"
    phase = phase_for(running, health)
    if phase == PHASE_STARTING and record.phase == PHASE_RUNNING:
        # docker's ``starting`` means "inside start_period, no verdict yet", not
        # "not serving" — and our own readiness gate already said yes.
        phase = PHASE_RUNNING
    return phase, health


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@router.get("/apps/{app_id}/status")
async def app_status(app_id: str) -> dict:
    """AC-23 — instance state, health, current version, restarts. Form agnostic."""
    config = get_config()
    docker = get_docker_backend()
    record = _record_or_404(config, app_id)
    info = _live_state(docker, record)
    phase, health = _project_phase(record, info)

    started_at = ((info or {}).get("State") or {}).get("StartedAt") or record.started_at
    # Recoveries the daemon did (process exits) plus recoveries we did
    # (rebuilds). Reporting only the daemon's number would reset to zero on
    # every rebuild and make a chronically sick app look untouched.
    daemon_restarts = int((info or {}).get("RestartCount") or 0)

    return {
        "instance_id": record.container_id or record.container_name,
        "phase": phase,
        "health": health,
        "current_version_id": record.version_id,
        "started_at": started_at,
        "restart_count": record.restart_count + daemon_restarts,
        "last_probe_at": record.last_probe_at,
    }


@router.get("/apps/{app_id}/logs")
async def app_logs(
    app_id: str,
    tail: int = Query(DEFAULT_TAIL, ge=1, le=MAX_TAIL),
    since: str | None = Query(None),
    keyword: str | None = Query(None),
) -> dict:
    """AC-23 / AC-55 — the app's own output, filtered, with our secrets removed.

    ``tail`` and ``since`` are pushed to the daemon (they narrow the rotation
    window it reads); ``keyword`` is applied here, because no log driver can do
    it. Keeping that split explicit matters: it is why ``tail=200`` with a
    keyword may return fewer than 200 lines rather than searching further back.
    """
    config = get_config()
    docker = get_docker_backend()
    record = _record_or_404(config, app_id)
    since_epoch = _parse_since(since)

    ref = record.container_id or record.container_name
    try:
        raw = docker.container_logs(ref, tail=tail, since=since_epoch)
    except Exception as exc:
        if not _backend_reachable(docker):
            raise BackendUnavailableError(f"the orchestration backend is not reachable: {exc}")
        raise NotFoundError(f"no readable output for app {app_id}: {exc}")

    lines = [line for line in (raw or "").splitlines() if line.strip()]
    if keyword:
        needle = keyword.lower()
        lines = [line for line in lines if needle in line.lower()]
    for secret in _redactions(record):
        lines = [line.replace(secret, REDACTED) for line in lines]
    return {"lines": lines}


@router.get("/runtime/status")
async def runtime_status() -> dict:
    """AC-23 — capacity, buildable runtimes, and deployment pre-flight.

    Never 500s and never raises on a dead backend: "the orchestration backend is
    down" is the single most useful thing this endpoint can say, and it can only
    say it by answering.
    """
    config = get_config()
    docker = get_docker_backend()
    store = get_store(config)

    available = _backend_reachable(docker)
    runtimes = discover_runtimes()
    capacity = AdmissionService(config, store=store).capacity_snapshot()
    capacity["instances"] = len(store.alive())

    return {
        "backend_available": available,
        "supported_runtimes": runtimes,
        "capacity": capacity,
        "preflight": _preflight(config, docker, runtimes, available),
    }


def _preflight(config: Config, docker: DockerBackend, runtimes: list[str], available: bool) -> list[dict[str, Any]]:
    """Deployment self-checks, phrased as the fix rather than the symptom.

    Each of these has a failure mode that reaches the user as something else
    entirely: no network → every deploy dies with a daemon error; no base image
    on an air-gapped host → the first build hangs then fails on a pull; an
    unwritable data root → apps start and lose their data.
    """
    checks: list[dict[str, Any]] = [
        {
            "name": "orchestration_backend",
            "ok": available,
            "detail": "reachable" if available else "not reachable — check the daemon / socket proxy",
        }
    ]

    if available:
        try:
            networks = docker.list_networks(name=config.network)
            found = bool(networks)
            detail = (
                f"{config.network} exists"
                if found
                else f"{config.network} is missing — run: docker network create {config.network}"
            )
        except Exception as exc:
            found, detail = False, f"cannot list networks: {exc}"
    else:
        found, detail = False, "not checked — the orchestration backend is unreachable"
    checks.append({"name": "application_network", "ok": found, "detail": detail})

    writable, detail = _data_root_writable(config)
    checks.append({"name": "data_root_writable", "ok": writable, "detail": detail})

    checks.append(
        {
            "name": "runtime_templates",
            "ok": bool(runtimes),
            "detail": ", ".join(runtimes) if runtimes else "no runtime template is installed",
        }
    )

    missing: list[str] = []
    if available:
        for runtime in runtimes:
            base = BASE_IMAGES.get(runtime)
            if not base:
                continue
            try:
                if not docker.list_images(name=base):
                    missing.append(base)
            except Exception as exc:
                missing.append(f"{base} (unreadable: {exc})")
        images_detail = (
            "all base images are present locally"
            if not missing
            else "pull these before publishing on an air-gapped host: " + ", ".join(missing)
        )
        images_ok = not missing
    else:
        images_ok, images_detail = False, "not checked — the orchestration backend is unreachable"
    checks.append({"name": "base_images", "ok": images_ok, "detail": images_detail})

    return checks


def _data_root_writable(config: Config) -> tuple[bool, str]:
    probe = config.state_dir / ".write-probe"
    try:
        config.state_dir.mkdir(parents=True, exist_ok=True)
        config.apps_root.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, f"{config.data_root} is writable"
    except OSError as exc:
        return False, f"{config.data_root} is not writable: {exc}"
