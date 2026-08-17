"""Capacity admission — the hard gate in front of every start and every build.

D11. Two gates, conjunction, and rejection is a legitimate outcome:

* **Gate ① — what the machine has right now.** ``MemAvailable - reserve_mb``.
  Catches the case the quota arithmetic cannot see: the platform's own JVMs,
  uvicorn, three celery workers and four linsight workers are resident and the
  32 GiB box has 0.9 GiB left (K2). ``reserve_mb`` is headroom for exactly that
  churn, not a fudge factor.
* **Gate ② — what has been promised.** ``Σ limits of alive instances + this
  request ≤ total × overcommit_ratio``, and the same shape for CPU against
  ``nproc``. Catches the opposite blind spot: ten freshly started apps are each
  using 40 MiB and all pass Gate ① — until they warm up.

Builds go through the same door with ``purpose="build"`` and are sized by
``build_reserve_mb``, because ``pip install`` on a wheel-less package is exactly
the kind of memory spike that takes the host down while nothing is "running"
yet. A rejected build reports ``stage="build_admission"`` so AC-15's failure
stage and AC-19's capacity verdict are one event, not two vocabularies.

The verdict carries a snapshot of the numbers it was made from — that is what
lets the product tell an owner *why* their app is "待上线（资源不足）"
(AC-65) instead of showing an opaque failure, and it is the same payload the
super-admin runtime-status view reuses (AC-23).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from runtime_manager.config import Config
from runtime_manager.desired_state import get_store

logger = logging.getLogger(__name__)

PURPOSE_RUN = "run"
PURPOSE_BUILD = "build"
VALID_PURPOSES = (PURPOSE_RUN, PURPOSE_BUILD)

#: AC-15 failure stage reported when a *build* is refused for capacity.
STAGE_BUILD_ADMISSION = "build_admission"

REASON_MEM_AVAILABLE = "insufficient_available_memory"
REASON_MEM_QUOTA = "memory_quota_exhausted"
REASON_CPU_QUOTA = "cpu_quota_exhausted"
REASON_HOST_UNREADABLE = "host_capacity_unreadable"


@dataclass(frozen=True)
class Tier:
    """Resource tier as resolved by the platform (``DEFAULT_TIERS`` / F055 table).

    ``mem`` is MiB and ``cpu`` is vCPU — the same units the platform's
    ``DEFAULT_TIERS`` uses (0.5 vCPU / 512 MiB, 1 / 1024, 2 / 2048), so the
    numbers that appear in the product UI are the numbers that appear here and
    in ``docker inspect`` (AC-63).
    """

    cpu: float
    mem_mb: int


@dataclass(frozen=True)
class HostSnapshot:
    mem_total_mb: int
    mem_available_mb: int
    cpu_count: float


class HostProbe(Protocol):
    def snapshot(self) -> HostSnapshot: ...


class HostProbeUnavailable(RuntimeError):
    """The host's capacity cannot be read (no ``/proc/meminfo``)."""


class LinuxHostProbe:
    """``/proc/meminfo`` + ``os.cpu_count()``.

    ``MemAvailable`` — not ``MemFree`` — is the kernel's own estimate of what a
    new workload can actually get without swapping, i.e. the number a human
    reads off ``free -m``. Reading ``MemFree`` here would reject on a healthy
    box that is merely using its page cache.
    """

    MEMINFO = Path("/proc/meminfo")

    def snapshot(self) -> HostSnapshot:
        try:
            text = self.MEMINFO.read_text(encoding="utf-8")
        except OSError as exc:
            raise HostProbeUnavailable(f"cannot read {self.MEMINFO}: {exc}")
        values: dict[str, int] = {}
        for line in text.splitlines():
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts and parts[0].isdigit():
                values[key.strip()] = int(parts[0])  # kB
        if "MemTotal" not in values:
            raise HostProbeUnavailable("MemTotal missing from /proc/meminfo")
        available_kb = values.get("MemAvailable", values.get("MemFree", 0))
        return HostSnapshot(
            mem_total_mb=values["MemTotal"] // 1024,
            mem_available_mb=available_kb // 1024,
            cpu_count=float(os.cpu_count() or 1),
        )


@dataclass(frozen=True)
class AdmissionResult:
    admitted: bool
    reason: str
    snapshot: dict[str, Any]
    required_mb: int
    required_cpu: float
    stage: str | None = None
    message: str = ""

    def to_response(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "reason": self.reason,
            "message": self.message,
            "stage": self.stage,
            "required_mb": self.required_mb,
            "required_cpu": self.required_cpu,
            "snapshot": self.snapshot,
        }


class AdmissionService:
    def __init__(
        self,
        config: Config,
        host_probe: HostProbe | None = None,
        store=None,
    ) -> None:
        self._config = config
        self._probe = host_probe or LinuxHostProbe()
        self._store = store if store is not None else get_store(config)

    def capacity_snapshot(self) -> dict[str, Any]:
        """The same numbers a verdict is made from, with no verdict attached.

        AC-23's runtime-status view and AC-65's "why is my app 待上线（资源不
        足）" have to agree to the megabyte; they agree by reading one function.
        ``readable=False`` (rather than an exception) is the honest answer on a
        host whose ``/proc/meminfo`` cannot be read — the super-admin needs to
        see *that*, not a 500.
        """
        committed_mb, committed_cpu = self._store.committed()
        try:
            host = self._probe.snapshot()
        except HostProbeUnavailable as exc:
            logger.error("capacity snapshot could not read host state: %s", exc)
            snapshot = self._snapshot(None, committed_mb, committed_cpu)
            snapshot.update(readable=False, reason=str(exc))
            return snapshot
        snapshot = self._snapshot(host, committed_mb, committed_cpu)
        snapshot.update(readable=True, reason="")
        return snapshot

    def _snapshot(self, host: HostSnapshot | None, committed_mb: int, committed_cpu: float) -> dict[str, Any]:
        return {
            "mem_available_mb": host.mem_available_mb if host else 0,
            "committed_mb": committed_mb,
            "total_mb": host.mem_total_mb if host else 0,
            "cpu": host.cpu_count if host else 0,
            "committed_cpu": committed_cpu,
            "reserve_mb": self._config.reserve_mb,
            "overcommit_ratio": self._config.overcommit_ratio,
        }

    def evaluate(self, tier: Tier | None, purpose: str = PURPOSE_RUN) -> AdmissionResult:
        if purpose not in VALID_PURPOSES:
            raise ValueError(f"unknown admission purpose: {purpose}")

        config = self._config
        stage = STAGE_BUILD_ADMISSION if purpose == PURPOSE_BUILD else None

        if purpose == PURPOSE_BUILD:
            # A build is a transient, memory-shaped workload whose footprint has
            # nothing to do with the tier the app will eventually run at; CPU is
            # not limited during build (D3 limits --memory only), so it is not
            # charged against the CPU quota either.
            required_mb = config.build_reserve_mb
            required_cpu = 0.0
        else:
            if tier is None:
                raise ValueError("a run admission requires a tier")
            required_mb = tier.mem_mb
            required_cpu = tier.cpu

        try:
            host = self._probe.snapshot()
        except HostProbeUnavailable as exc:
            logger.error("capacity admission could not read host state: %s", exc)
            return AdmissionResult(
                admitted=False,
                reason=REASON_HOST_UNREADABLE,
                message=str(exc),
                stage=stage,
                required_mb=required_mb,
                required_cpu=required_cpu,
                snapshot={
                    "mem_available_mb": 0,
                    "committed_mb": 0,
                    "total_mb": 0,
                    "cpu": 0,
                    "committed_cpu": 0.0,
                },
            )

        committed_mb, committed_cpu = self._store.committed()
        snapshot = {
            "mem_available_mb": host.mem_available_mb,
            "committed_mb": committed_mb,
            "total_mb": host.mem_total_mb,
            "cpu": host.cpu_count,
            "committed_cpu": committed_cpu,
            "reserve_mb": config.reserve_mb,
            "overcommit_ratio": config.overcommit_ratio,
        }

        def reject(reason: str, message: str) -> AdmissionResult:
            logger.info("capacity admission rejected (%s): %s | %s", reason, message, snapshot)
            return AdmissionResult(
                admitted=False,
                reason=reason,
                message=message,
                stage=stage,
                required_mb=required_mb,
                required_cpu=required_cpu,
                snapshot=snapshot,
            )

        # Gate ① — real, right now.
        headroom_mb = host.mem_available_mb - config.reserve_mb
        if headroom_mb < required_mb:
            return reject(
                REASON_MEM_AVAILABLE,
                f"available memory {host.mem_available_mb} MiB minus reserve "
                f"{config.reserve_mb} MiB leaves {headroom_mb} MiB, need {required_mb} MiB",
            )

        # Gate ② — promised.
        mem_ceiling = host.mem_total_mb * config.overcommit_ratio
        if committed_mb + required_mb > mem_ceiling:
            return reject(
                REASON_MEM_QUOTA,
                f"committed {committed_mb} MiB + {required_mb} MiB exceeds the "
                f"{config.overcommit_ratio:g} ceiling of {mem_ceiling:.0f} MiB",
            )

        cpu_ceiling = host.cpu_count * config.overcommit_ratio
        if required_cpu and committed_cpu + required_cpu > cpu_ceiling:
            return reject(
                REASON_CPU_QUOTA,
                f"committed {committed_cpu:g} vCPU + {required_cpu:g} vCPU exceeds the "
                f"{config.overcommit_ratio:g} ceiling of {cpu_ceiling:g} vCPU",
            )

        return AdmissionResult(
            admitted=True,
            reason="",
            message="",
            stage=None,
            required_mb=required_mb,
            required_cpu=required_cpu,
            snapshot=snapshot,
        )
