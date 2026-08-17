"""Desired-state store — what the manager *believes* should be running.

D1 makes the backend declare intent ("app A should run version V at tier T")
rather than issue commands, which means the manager, not the backend, owns the
memory of that intent. Two consequences the rest of the package leans on:

* **Restarting the manager changes nothing about running apps** (AC-22). The
  containers belong to dockerd; this file only tells the reconciler what it
  should be comparing against.
* **The route table's source of truth lives here, not in the platform DB.**
  ``app_instance.exec_ref`` on the platform side is an audit / triage reference;
  the address the app-proxy dials comes from ``generation`` here plus a live
  ``inspect`` (D5.1).

Persistence is a JSON file written atomically (tmp + ``os.replace``) under
``{data_root}/state``. Every managed container *also* carries the same facts as
labels, so a lost state file is recoverable: :meth:`InstanceRecord.from_container`
is that reverse mapping and ``reconciler.recover_from_labels`` is its caller.

The store is cached per state-file path, which is what lets each test get a
pristine store simply by having its own ``data_root`` — no global reset hook,
nothing to forget to call.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from runtime_manager.config import (
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
)

NANO = 1_000_000_000

# Phase vocabulary — deliberately form agnostic (INV-33): no "container" here.
PHASE_PENDING = "pending"
PHASE_BUILDING = "building"
PHASE_STARTING = "starting"
PHASE_RUNNING = "running"
PHASE_UNHEALTHY = "unhealthy"
PHASE_STOPPED = "stopped"
PHASE_FAILED = "failed"

ALL_PHASES = (
    PHASE_PENDING,
    PHASE_BUILDING,
    PHASE_STARTING,
    PHASE_RUNNING,
    PHASE_UNHEALTHY,
    PHASE_STOPPED,
    PHASE_FAILED,
)

#: Phases that hold host capacity. ``unhealthy`` counts — the process is alive
#: and its cgroup limits are still charged; excluding it would let a sick app
#: silently double-book the machine.
ALIVE_PHASES = frozenset({PHASE_STARTING, PHASE_RUNNING, PHASE_UNHEALTHY})

DESIRED_RUNNING = "running"
DESIRED_STOPPED = "stopped"


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _nanos_to_seconds(value: Any, default: int) -> int:
    """Docker expresses health-check durations in nanoseconds."""
    nanos = _as_int(value, 0)
    return nanos // NANO if nanos > 0 else default


def phase_for(running: bool, health: str) -> str:
    if not running:
        return PHASE_STOPPED
    if health == "unhealthy":
        return PHASE_UNHEALTHY
    if health == "starting":
        return PHASE_STARTING
    return PHASE_RUNNING


@dataclass
class InstanceRecord:
    """One app's desired instance. Single instance per app is a design fact (AC-24)."""

    app_id: str
    slug: str
    version_id: str
    version_no: int
    image_ref: str
    tier_cpu: float
    tier_mem_mb: int
    port: int
    health_path: str
    container_name: str
    env: dict[str, str] = field(default_factory=dict)
    container_id: str | None = None
    phase: str = PHASE_PENDING
    health: str = "unknown"
    desired: str = DESIRED_RUNNING
    generation: int = 0
    started_at: str | None = None
    last_probe_at: str | None = None
    restart_count: int = 0
    unhealthy_rounds: int = 0
    #: Old containers still serving in-flight requests during the grace window
    #: (AC-21). Kept in state so a manager restart mid-switch still retires them.
    retiring: list[str] = field(default_factory=list)
    #: Health-check parameters as deployed. Persisted rather than re-derived so a
    #: reconciler rebuild reproduces the instance the owner actually deployed —
    #: an app that asked for a 120 s ``start_period`` must not come back with the
    #: default 20 s and fail its own gate.
    health_interval: int = 10
    health_timeout: int = 3
    health_retries: int = 3
    start_period: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstanceRecord:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_container(cls, info: dict[str, Any]) -> InstanceRecord | None:
        """Rebuild a record from a container's own labels + config (AC-50).

        This is the disaster path: the state file is a cache, the labels the
        manager writes on every container are the durable copy. Everything the
        reconciler needs to *recreate* the instance is derivable here — image,
        tier, port, health path and parameters, environment, generation — which
        is exactly why those facts are labelled in the first place.

        Returns ``None`` for anything not ours (foreign containers, probe
        instances whose ``bisheng.managed`` is ``probe``): "not ours" must be a
        cheap, total answer, because the caller's next step is reclaiming.
        """
        config_section = info.get("Config") or {}
        labels = config_section.get("Labels") or info.get("Labels") or {}
        if labels.get(LABEL_MANAGED) != "true":
            return None
        app_id = labels.get(LABEL_APP_ID)
        if not app_id:
            return None

        state = info.get("State") or {}
        running = bool(state.get("Running"))
        health = ((state.get("Health") or {}).get("Status") or "").strip() or "unknown"

        env: dict[str, str] = {}
        for item in config_section.get("Env") or []:
            key, _, value = str(item).partition("=")
            if key:
                env[key] = value

        healthcheck = config_section.get("Healthcheck") or {}
        name = str(info.get("Name") or "").lstrip("/")

        return cls(
            app_id=app_id,
            slug=labels.get(LABEL_APP_SLUG, ""),
            version_id=labels.get(LABEL_VERSION_ID, ""),
            version_no=_as_int(labels.get(LABEL_VERSION_NO), 1),
            image_ref=config_section.get("Image") or info.get("Image") or "",
            tier_cpu=_as_float(labels.get(LABEL_TIER_CPU), 0.0),
            tier_mem_mb=_as_int(labels.get(LABEL_TIER_MEM_MB), 0),
            port=_as_int(labels.get(LABEL_PORT), 8080),
            health_path=labels.get(LABEL_HEALTH_PATH, "/"),
            container_name=name,
            env=env,
            container_id=info.get("Id"),
            phase=phase_for(running, health),
            health=health,
            # A managed container that is *not* running under ``unless-stopped``
            # was stopped on purpose: the daemon would have brought it back
            # otherwise. Inferring "stopped" here is what keeps AC-41 (停运)
            # surviving a state-file loss instead of silently resurrecting.
            desired=DESIRED_RUNNING if running else DESIRED_STOPPED,
            generation=_as_int(labels.get(LABEL_GENERATION), 1),
            started_at=state.get("StartedAt") or None,
            restart_count=_as_int(info.get("RestartCount"), 0),
            health_interval=_nanos_to_seconds(healthcheck.get("Interval"), 10),
            health_timeout=_nanos_to_seconds(healthcheck.get("Timeout"), 3),
            health_retries=_as_int(healthcheck.get("Retries"), 3),
            start_period=_nanos_to_seconds(healthcheck.get("StartPeriod"), 0),
        )


class DesiredStateStore:
    """Thread-safe, file-backed map of ``app_id`` → :class:`InstanceRecord`."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._records: dict[str, InstanceRecord] = {}
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A corrupt state file must not stop the manager from booting: the
            # containers are still running and T029's label-based recovery pass
            # can rebuild the map from the daemon.
            return
        for item in raw.get("instances", []):
            record = InstanceRecord.from_dict(item)
            self._records[record.app_id] = record

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "instances": [r.to_dict() for r in self._records.values()]}
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), prefix=".desired-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    # -- api ---------------------------------------------------------------
    def get(self, app_id: str) -> InstanceRecord | None:
        with self._lock:
            return self._records.get(app_id)

    def put(self, record: InstanceRecord) -> InstanceRecord:
        with self._lock:
            self._records[record.app_id] = record
            self._flush()
            return record

    def delete(self, app_id: str) -> None:
        with self._lock:
            if self._records.pop(app_id, None) is not None:
                self._flush()

    def list(self) -> list[InstanceRecord]:
        with self._lock:
            return list(self._records.values())

    def alive(self) -> list[InstanceRecord]:
        """Records currently charged against host capacity (see ALIVE_PHASES)."""
        with self._lock:
            return [r for r in self._records.values() if r.phase in ALIVE_PHASES]

    def committed(self) -> tuple[int, float]:
        """``(memory MiB, vCPU)`` promised to already-alive instances."""
        records = self.alive()
        return (
            sum(r.tier_mem_mb for r in records),
            sum(r.tier_cpu for r in records),
        )

    def mutate(self, app_id: str, **changes: Any) -> InstanceRecord | None:
        with self._lock:
            record = self._records.get(app_id)
            if record is None:
                return None
            for key, value in changes.items():
                setattr(record, key, value)
            self._flush()
            return record


_stores: dict[str, DesiredStateStore] = {}
_stores_lock = threading.Lock()


def get_store(config) -> DesiredStateStore:
    """Per-state-file singleton.

    Keyed by path rather than kept as one global so that a test (or a second
    deployment on the same host) gets its own store for free.
    """
    key = str(config.state_path)
    with _stores_lock:
        store = _stores.get(key)
        if store is None:
            store = DesiredStateStore(config.state_path)
            _stores[key] = store
        return store


def reset_stores() -> None:
    with _stores_lock:
        _stores.clear()
