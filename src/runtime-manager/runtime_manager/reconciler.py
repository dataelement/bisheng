"""Reconcile loop — desired state vs. what the daemon is actually running (D4).

This module exists because of one docker fact and one product promise.

**The fact (坑 17 / K3):** on a single docker daemon the restart policy binds to
container *termination* only. ``HEALTHCHECK`` results are reported and nothing
acts on them, so a process that stays alive while answering 500 forever is, to
dockerd, a healthy citizen. That failure class — "unhealthy but alive" — has no
built-in recovery, and covering it is the *entire* justification for a
hand-written reconciler. Everything docker already does well is left to docker:
process exits ride the daemon's own exponential backoff (100 ms → 1 min, reset
after 10 s of uptime) under ``restart: unless-stopped``.

**The promise (AC-20):** an app recovers within five minutes, unattended. The
budget is four named terms, not a hope:

    healthcheck verdict (interval 10s × retries 3)      ≤ 30 s
    reconcile perception (2 rounds × 15 s)              ≤ 30 s
    rebuild + readiness gate (image is already local)   ≤ 90 s
                                                        ------
                                                        ≤ 150 s

:func:`recovery_budget_seconds` computes it from the live config so that
changing ``reconcile_interval_seconds`` or ``probe_timeout_seconds`` moves a
number a test checks, instead of quietly eating the margin.

Two properties are asserted as loudly as the recovery itself:

* **A manager restart is a no-op for running apps (AC-22).** Containers belong
  to dockerd. This loop starts by *reading* the world, and the very first thing
  it does is recover records from container labels (AC-50) — because reclaiming
  orphans before recovering would turn a lost state file into a site-wide
  outage.
* **Reclaim is narrow.** Only containers this manager labelled
  ``bisheng.managed=true`` are ever candidates, and among those, the current
  instance and everything inside its retirement grace window are protected. 114
  runs onlyoffice, rabbitmq and a JVM or two on the same daemon; a reconciler
  that reasons in terms of "not in my desired state" instead of "mine, and not
  in my desired state" is a data-loss incident waiting for a deploy.

A pass also keeps serving instances in line with the **egress layer** (D12 /
AC-16). The proxy variables are fixed when a container is created, the layer is
a property of the deployment, and the two drift apart the moment an operator
switches it on: the L3 rules cover the whole subnet at once, and every instance
created before that has no proxy to go through. That is not a hypothetical —
it cut an application on 114 off the internet the evening the layer went live,
silently, until a user noticed the numbers had stopped moving. The fix is a
blue-green replacement at the next generation, one application per pass.

One pass does a further, unrelated thing: it reclaims **approval-time previews**
whose deadline has passed (F055 AC-28). They are deliberately outside
everything above — ``bisheng.managed=preview``, no desired-state record — so
the sweep reads their own label and touches nothing else. It rides this loop
rather than a scheduler of its own because this loop already runs every 15 s,
already reads the daemon and already survives a restart.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from runtime_manager.admission import Tier
from runtime_manager.config import LABEL_MANAGED, Config
from runtime_manager.desired_state import (
    DESIRED_STOPPED,
    PHASE_RUNNING,
    PHASE_STARTING,
    PHASE_STOPPED,
    PHASE_UNHEALTHY,
    InstanceRecord,
    get_store,
    phase_for,
)
from runtime_manager.docker_backend import DockerBackend, get_docker_backend
from runtime_manager.egress import (
    ENV_EGRESS_TOKEN,
    egress_drift,
    get_policy_store,
    realign_egress_env,
    register_principal,
    runtime_destinations,
)
from runtime_manager.lifecycle import (
    Prober,
    ThreadScheduler,
    build_container_payload,
    container_name,
    start_period_seconds,
)
from runtime_manager.observability import log_rebuild, log_reconcile

logger = logging.getLogger(__name__)

#: What docker itself needs before it will call an instance unhealthy:
#: ``interval`` (10 s) × ``retries`` (3). Not a knob — it mirrors the health
#: parameters :func:`runtime_manager.lifecycle.build_container_payload` writes.
HEALTHCHECK_DETECTION_BUDGET_SECONDS = 30

#: Consecutive unhealthy rounds before a rebuild. One round would restart apps
#: over a single slow GC pause; three would spend the AC-20 budget on waiting.
UNHEALTHY_ROUNDS_BEFORE_REBUILD = 2

#: AC-20 / NFR-6 — the promise the budget below has to fit inside.
RECOVERY_BUDGET_SECONDS = 300

#: Egress realignments started per pass. Each one is a blue-green switch whose
#: previous instance keeps running through the retirement grace window, so
#: realigning a whole host in one pass would briefly run every application
#: twice — on exactly the kind of host whose capacity gate already bites.
REALIGNMENTS_PER_PASS = 1

#: Back-off after a realigned instance fails its readiness gate. The attempt
#: holds this loop for up to a probe timeout, and the instance it would have
#: replaced is still serving, so retrying every 15 s would buy nothing and slow
#: recovery for every other application on the host.
REALIGN_RETRY_SECONDS = 600


def recovery_budget_seconds(config: Config) -> int:
    """Worst-case unattended recovery for the "alive but unhealthy" class."""
    return (
        HEALTHCHECK_DETECTION_BUDGET_SECONDS
        + config.reconcile_interval_seconds * UNHEALTHY_ROUNDS_BEFORE_REBUILD
        + config.probe_timeout_seconds
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class ReconcileReport:
    """What one pass did. Lists of ``app_id`` (or container name for reclaims).

    Returned rather than only logged because "did the reconciler act, and on
    what" is the assertion every recovery test needs, and because the operations
    log line is built from the same object (no second, drifting summary).
    """

    recovered: list[str] = field(default_factory=list)
    recreated: list[str] = field(default_factory=list)
    started: list[str] = field(default_factory=list)
    rebuilt: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)
    reclaimed: list[str] = field(default_factory=list)
    realigned: list[str] = field(default_factory=list)
    healthy: list[str] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)

    @property
    def acted(self) -> bool:
        return bool(
            self.recovered
            or self.recreated
            or self.started
            or self.rebuilt
            or self.stopped
            or self.reclaimed
            or self.realigned
        )

    def summary(self) -> str:
        return (
            f"recovered={len(self.recovered)} recreated={len(self.recreated)} "
            f"started={len(self.started)} rebuilt={len(self.rebuilt)} "
            f"stopped={len(self.stopped)} reclaimed={len(self.reclaimed)} "
            f"realigned={len(self.realigned)} "
            f"healthy={len(self.healthy)} failures={len(self.failures)}"
        )

    def action_counts(self) -> dict[str, int]:
        """The corrections this pass made, as the ``rtm.reconcile`` event carries
        them (§7). ``healthy`` is deliberately absent — it is the non-action."""
        return {
            "recovered": len(self.recovered),
            "recreated": len(self.recreated),
            "started": len(self.started),
            "rebuilt": len(self.rebuilt),
            "stopped": len(self.stopped),
            "reclaimed": len(self.reclaimed),
            "realigned": len(self.realigned),
            "failures": len(self.failures),
        }


class Reconciler:
    """One pass = read the world, then make the smallest correction per app."""

    def __init__(
        self,
        config: Config,
        docker: DockerBackend | None = None,
        store=None,
        prober: Prober | None = None,
        clock: Any | None = None,
        scheduler: Any | None = None,
    ) -> None:
        self._config = config
        self._docker = docker or get_docker_backend()
        self._store = store if store is not None else get_store(config)
        self._prober = prober
        self._clock = clock
        self._scheduler = scheduler or ThreadScheduler()
        #: app_id → monotonic time before which a failed realignment is not
        #: retried. In memory on purpose: a manager restart is a reasonable
        #: moment to try again.
        self._realign_retry_at: dict[str, float] = {}
        self._realigned_this_pass = 0

    # -- entry points ------------------------------------------------------
    def startup_align(self) -> ReconcileReport:
        """First pass after the process boots (AC-50).

        Order is load bearing: **recover from labels, then reconcile.** A fresh
        manager pointed at a host full of running apps (state file lost, restored
        from an old backup, moved to a new machine) must adopt them, not reap
        them.
        """
        report = ReconcileReport()
        report.recovered = self.recover_from_labels()
        return self.reconcile_once(report=report)

    def reconcile_once(self, report: ReconcileReport | None = None) -> ReconcileReport:
        report = report if report is not None else ReconcileReport()
        try:
            actual = self._managed_containers()
        except Exception as exc:
            # dockerd bouncing must not kill the loop: the apps are still up and
            # the next round is 15 s away (AC-22 — degraded, not broken).
            logger.warning("reconcile pass skipped: cannot read the orchestration backend: %s", exc)
            report.failures.append(("*", f"orchestration backend unreadable: {exc}"))
            # The pass that saw nothing is the one an operator comes looking for,
            # so it gets its event too — ``actual`` is unknown here, not zero,
            # and ``-1`` says so rather than claiming the host is empty.
            log_reconcile(
                desired=len(self._store.list()),
                actual=-1,
                actions=report.action_counts(),
                backend_error=str(exc),
            )
            return report

        # One read, then act on exactly what was read: recomputing the count at
        # the end would report a number the pass never worked from.
        records = self._store.list()
        self._realigned_this_pass = 0
        for record in records:
            try:
                self._reconcile_one(record, actual, report)
            except Exception as exc:
                logger.exception("reconcile of app %s failed", record.app_id)
                report.failures.append((record.app_id, str(exc)))

        self._reclaim_orphans(actual, report)
        # F055 AC-28's timeout leg. Previews are invisible to everything above
        # (they carry ``bisheng.managed=preview``), so this is a separate pass
        # over their own label — and it lives here rather than in a platform
        # beat task because the manager is the process that has to be alive for
        # the container to exist, and F054 AC-59 forbids a resident app-factory
        # worker in the platform image.
        report.reclaimed.extend(self._reclaim_expired_previews())
        log_reconcile(desired=len(records), actual=len(actual), actions=report.action_counts())
        if report.acted or report.failures:
            logger.info("reconcile pass: %s", report.summary())
        return report

    def recover_from_labels(self) -> list[str]:
        """Adopt running instances the store does not know about (AC-50)."""
        try:
            actual = self._managed_containers()
        except Exception as exc:
            logger.warning("label recovery skipped: %s", exc)
            return []

        candidates: dict[str, list[InstanceRecord]] = {}
        for name in actual:
            info = self._inspect(name)
            if info is None:
                continue
            record = InstanceRecord.from_container(info)
            if record is None:
                continue
            candidates.setdefault(record.app_id, []).append(record)

        recovered: list[str] = []
        for app_id, found in candidates.items():
            # Mid-switch crash: two containers, one app. The highest generation
            # is the current one by construction (it only increments after a
            # readiness gate passes); the rest fall through to orphan reclaim.
            best = max(found, key=lambda r: (r.generation, r.version_no))
            existing = self._store.get(app_id)
            if existing is None:
                self._store.put(best)
                recovered.append(app_id)
                logger.warning(
                    "adopted app %s from container labels (version %s, generation %s) — "
                    "the desired-state file did not know about it",
                    app_id,
                    best.version_id,
                    best.generation,
                )
            elif existing.container_name == best.container_name and existing.container_id != best.container_id:
                # Same instance, new container id (daemon-side recreate).
                self._store.mutate(app_id, container_id=best.container_id)
        return sorted(recovered)

    # -- per-app decisions -------------------------------------------------
    def _reconcile_one(
        self, record: InstanceRecord, actual: dict[str, dict[str, Any]], report: ReconcileReport
    ) -> None:
        summary = actual.get(record.container_name)

        if record.desired == DESIRED_STOPPED:
            # An operator stopped this app. ``unless-stopped`` tells the daemon
            # the same thing; the reconciler must not be the one that disagrees.
            if summary is not None and self._is_running(summary):
                self._stop(record.container_name)
                self._store.mutate(record.app_id, phase=PHASE_STOPPED, health="unknown")
                report.stopped.append(record.app_id)
            return

        if summary is None:
            self._recreate(record, report)
            return

        info = self._inspect(record.container_name)
        state = (info or {}).get("State") or {}
        running = bool(state.get("Running")) if info is not None else self._is_running(summary)
        health = ((state.get("Health") or {}).get("Status") or "").strip() or "unknown"

        if not running:
            # The process died. Docker's backoff owns the restart; we only nudge
            # the case where it has given up (or the daemon was down when it
            # exited). Recreating here would discard the backoff and hide a
            # crash loop behind a fresh container id every 15 seconds.
            self._docker.start_container(record.container_name)
            self._store.mutate(
                record.app_id,
                phase=PHASE_STARTING,
                health="starting",
                restart_count=record.restart_count + 1,
                unhealthy_rounds=0,
                started_at=_now(),
            )
            report.started.append(record.app_id)
            logger.info("app %s was not running; started %s", record.app_id, record.container_name)
            return

        if health == "unhealthy":
            rounds = record.unhealthy_rounds + 1
            if rounds >= UNHEALTHY_ROUNDS_BEFORE_REBUILD:
                self._rebuild(record, report)
            else:
                self._store.mutate(record.app_id, phase=PHASE_UNHEALTHY, health=health, unhealthy_rounds=rounds)
                logger.warning(
                    "app %s is alive but unhealthy (round %s/%s) — docker will not act on this, we will",
                    record.app_id,
                    rounds,
                    UNHEALTHY_ROUNDS_BEFORE_REBUILD,
                )
            return

        phase = phase_for(True, health)
        if phase == PHASE_STARTING and record.phase == PHASE_RUNNING:
            # ``starting`` is docker's "no verdict yet" (inside ``start_period``),
            # not "not serving". An instance our own readiness gate already
            # passed must not flap back to starting on every rebuild's grace
            # period — the product renders this phase.
            phase = PHASE_RUNNING
        self._store.mutate(
            record.app_id,
            phase=phase,
            health=health,
            unhealthy_rounds=0,
            container_id=(info or {}).get("Id") or record.container_id,
            restart_count=max(record.restart_count, 0),
        )
        report.healthy.append(record.app_id)
        if phase == PHASE_RUNNING:
            self._align_egress(record, report)

    def _recreate(self, record: InstanceRecord, report: ReconcileReport) -> None:
        """Desired state says running and the daemon has nothing at that name."""
        logger.warning(
            "app %s has no execution body (%s is gone); recreating at generation %s",
            record.app_id,
            record.container_name,
            record.generation,
        )
        self._ensure_absent(record.container_name)
        env = self._aligned_env(record)
        container_id = self._create_and_start(replace(record, env=env), generation=record.generation)
        report.recreated.append(record.app_id)
        self._settle(record, report, container_id=container_id, generation=record.generation, env=env)

    def _rebuild(self, record: InstanceRecord, report: ReconcileReport) -> None:
        """The unhealthy-but-alive fix: stop → rm → run. The volume never moves.

        ``generation`` increments because the new execution body gets a new
        address on the application network, and ``generation`` is precisely the
        app-proxy's signal that its cached upstream is stale (D5.1).
        """
        generation = record.generation + 1
        log_rebuild(
            app_id=record.app_id,
            container=record.container_name,
            generation=generation,
            reason="unhealthy",
            unhealthy_rounds=UNHEALTHY_ROUNDS_BEFORE_REBUILD,
        )
        self._ensure_absent(record.container_name)
        env = self._aligned_env(record)
        container_id = self._create_and_start(replace(record, env=env), generation=generation)
        report.rebuilt.append(record.app_id)
        self._settle(record, report, container_id=container_id, generation=generation, env=env)

    def _settle(
        self,
        record: InstanceRecord,
        report: ReconcileReport,
        *,
        container_id: str,
        generation: int,
        env: dict[str, str],
    ) -> None:
        outcome = self._probe(record, container_id)
        changes: dict[str, Any] = {
            "container_id": container_id,
            "generation": generation,
            # What the new instance was actually handed — a recovery that
            # realigned the proxy variables must not leave the record saying
            # otherwise, or the next pass would "realign" it again.
            "env": env,
            "restart_count": record.restart_count + 1,
            "unhealthy_rounds": 0,
            "started_at": _now(),
            "last_probe_at": _now(),
        }
        if outcome.ready:
            changes.update(phase=PHASE_RUNNING, health="healthy")
        else:
            # Unlike deploy (which tears down so a broken new version cannot
            # replace a working one), here the instance we just made *is* the
            # current version and the alternative is nothing at all. Leave it up,
            # report the reason, let the next rounds judge it on health.
            changes.update(phase=PHASE_UNHEALTHY, health="unhealthy")
            report.failures.append((record.app_id, outcome.reason or "did not become ready"))
            logger.error("app %s did not become ready after recovery: %s", record.app_id, outcome.reason)
        self._store.mutate(record.app_id, **changes)

    # -- egress (D12 / AC-16) ----------------------------------------------
    def _align_egress(self, record: InstanceRecord, report: ReconcileReport) -> None:
        """Keep a serving instance's policy entry and proxy variables current.

        Two halves with very different costs. The policy entry is a file the
        proxy re-reads, so a stale or missing one (``RTM_EGRESS_ALLOW`` edited,
        the policy file lost) is fixed in place. The variables live inside the
        container, so drift there means a new instance.
        """
        if self._store.get(record.app_id) is not record:
            # A deploy / destroy replaced the record during this pass; acting on
            # the copy read at the start would write yesterday's policy over it.
            return
        token = self._ensure_principal(record)
        if not egress_drift(self._config, principal=record.app_id, env=record.env):
            return
        if self._realigned_this_pass >= REALIGNMENTS_PER_PASS:
            return
        if self._monotonic() < self._realign_retry_at.get(record.app_id, float("-inf")):
            return
        self._realigned_this_pass += 1
        self._realign(record, token, report)

    def _ensure_principal(self, record: InstanceRecord) -> str:
        """Put the instance's egress policy on file when missing or stale; return its credential.

        Written only on a difference: every write bumps the file's mtime, and the
        proxy reloads on that — once per pass per application would be a reload
        storm for a file that almost never changes.
        """
        config = self._config
        if not config.egress_enabled:
            return ""
        destinations = runtime_destinations(
            config,
            platform_api_base=record.env.get("BISHENG_PLATFORM_API_BASE", ""),
            declared=record.egress_domains,
            injected_env=record.env,
        )
        token = record.env.get(ENV_EGRESS_TOKEN) or ""
        existing = get_policy_store(config).get(record.app_id)
        if existing is not None and existing.destinations == destinations:
            if token and existing.authenticates(token):
                return token
            if not token and existing.token:
                return existing.token
        # The container's own credential wins over whatever is on file: it is
        # the one the running instance presents.
        return register_principal(config, principal=record.app_id, destinations=destinations, token=token or None)

    def _aligned_env(self, record: InstanceRecord) -> dict[str, str]:
        """The environment a (re)created instance should get under the current layer."""
        token = self._ensure_principal(record)
        if not egress_drift(self._config, principal=record.app_id, env=record.env):
            return record.env
        return realign_egress_env(self._config, principal=record.app_id, env=record.env, token=token)

    def _realign(self, record: InstanceRecord, token: str, report: ReconcileReport) -> None:
        """Replace a healthy instance whose proxy variables are stale, blue-green.

        Same shape as a redeploy of the same version (AC-21): the replacement is
        created beside the serving instance at the next generation, the route
        switches only after it passes the readiness gate, and the old one is
        retired after the grace window. A failure leaves the old instance
        serving — cut off from the internet, but no worse than before.
        """
        generation = record.generation + 1
        name = container_name(record.slug, record.version_id, generation)
        if self._inspect(name) is not None:
            # Only a deploy of this same version puts something there, and it is
            # mid-probe: its instance gets current variables anyway, and removing
            # it would fail that deploy.
            return
        env = realign_egress_env(self._config, principal=record.app_id, env=record.env, token=token)
        logger.warning(
            "app %s: proxy variables do not match the egress layer; replacing %s with generation %s",
            record.app_id,
            record.container_name,
            generation,
        )
        container_id = self._create_and_start(replace(record, env=env, container_name=name), generation=generation)
        outcome = self._probe(record, container_id)
        if not outcome.ready:
            self._force_remove(container_id)
            self._realign_retry_at[record.app_id] = self._monotonic() + REALIGN_RETRY_SECONDS
            reason = outcome.reason or "did not become ready"
            report.failures.append((record.app_id, f"egress realignment: {reason}"))
            logger.error(
                "app %s: realigned instance did not become ready (%s); %s keeps serving, retry in %ss",
                record.app_id,
                reason,
                record.container_name,
                REALIGN_RETRY_SECONDS,
            )
            return
        if self._store.get(record.app_id) is not record:
            # Replaced while we probed — that deploy's instance is the current one.
            self._force_remove(container_id)
            return
        self._realign_retry_at.pop(record.app_id, None)
        previous = record.container_name
        self._store.mutate(
            record.app_id,
            container_name=name,
            container_id=container_id,
            env=env,
            generation=generation,
            phase=PHASE_RUNNING,
            health="healthy",
            unhealthy_rounds=0,
            started_at=_now(),
            last_probe_at=_now(),
            retiring=[*record.retiring, previous],
        )
        self._scheduler.schedule(self._config.retire_grace_seconds, self._retire, record.app_id, previous)
        report.realigned.append(record.app_id)

    def _retire(self, app_id: str, name: str) -> None:
        """Mirror of ``LifecycleService._retire`` for the instance a realignment replaced."""
        self._force_remove(name)
        record = self._store.get(app_id)
        if record is not None and name in record.retiring:
            self._store.mutate(app_id, retiring=[c for c in record.retiring if c != name])

    def _monotonic(self) -> float:
        return self._clock.monotonic() if self._clock is not None else time.monotonic()

    # -- orphans -----------------------------------------------------------
    def _reclaim_orphans(self, actual: dict[str, dict[str, Any]], report: ReconcileReport) -> None:
        protected: set[str] = set()
        for record in self._store.list():
            protected.add(record.container_name)
            protected.update(record.retiring)

        for name in sorted(actual):
            if name in protected:
                continue
            logger.warning("reclaiming orphaned instance %s (no app declares it)", name)
            self._force_remove(name)
            report.reclaimed.append(name)

    def _reclaim_expired_previews(self) -> list[str]:
        """Approval-time previews past the deadline stamped on their label."""
        from runtime_manager.preview import PreviewService

        try:
            return PreviewService(self._config, docker=self._docker).reclaim_expired()
        except Exception as exc:
            # Never fails the pass: the applications this loop exists for are
            # unaffected by a preview that would not go away.
            logger.warning("preview expiry sweep failed: %s", exc)
            return []

    # -- backend helpers ---------------------------------------------------
    def _managed_containers(self) -> dict[str, dict[str, Any]]:
        """Name → summary, for containers **this manager created** only.

        The label filter is the safety property: ``bisheng.managed=true`` is
        written by :func:`~runtime_manager.lifecycle.build_container_payload`
        and by nothing else. Probe instances carry ``bisheng.managed=probe`` and
        are therefore invisible here — they clean themselves up, and a reconciler
        racing that cleanup would fail pre-flights for no reason.
        """
        rows = self._docker.list_containers(all_states=True, filters={"label": [f"{LABEL_MANAGED}=true"]})
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            names = row.get("Names") or []
            name = str(names[0]).lstrip("/") if names else str(row.get("Name") or "").lstrip("/")
            if name:
                out[name] = row
        return out

    @staticmethod
    def _is_running(summary: dict[str, Any]) -> bool:
        return str(summary.get("State") or "").lower() == "running"

    def _inspect(self, ref: str) -> dict[str, Any] | None:
        try:
            return self._docker.inspect_container(ref)
        except Exception as exc:
            logger.debug("inspect %s: %s", ref, exc)
            return None

    def _create_and_start(self, record: InstanceRecord, *, generation: int) -> str:
        tier = Tier(cpu=record.tier_cpu, mem_mb=record.tier_mem_mb)
        self._config.app_data_dir(record.app_id).mkdir(parents=True, exist_ok=True)
        # The egress policy is the caller's job (``_aligned_env`` / ``_align_egress``):
        # it has to be on file *before* the variables that name it are chosen.
        # Registering here, after the fact, is how a recreated instance once got a
        # freshly minted credential on the policy file and none in its environment.
        payload = build_container_payload(
            self._config,
            app_id=record.app_id,
            slug=record.slug,
            version_id=record.version_id,
            version_no=record.version_no,
            image_ref=record.image_ref,
            tier=tier,
            port=record.port,
            health_path=record.health_path,
            health_interval=record.health_interval,
            health_timeout=record.health_timeout,
            health_retries=record.health_retries,
            start_period=record.start_period or start_period_seconds(tier),
            env=record.env,
            generation=generation,
            egress_domains=record.egress_domains,
        )
        container_id = self._docker.create_container(record.container_name, payload)
        self._docker.start_container(container_id)
        return container_id

    def _probe(self, record: InstanceRecord, container_id: str):
        return self._get_prober().wait_ready(
            container_id,
            record.port,
            record.health_path,
            timeout=self._config.probe_timeout_seconds,
        )

    def _get_prober(self) -> Prober:
        if self._prober is None:
            from runtime_manager.probe import ProbeService

            self._prober = ProbeService(self._config, docker=self._docker)
        return self._prober

    def _ensure_absent(self, name: str) -> None:
        try:
            self._docker.inspect_container(name)
        except Exception:
            return
        self._force_remove(name)

    def _stop(self, ref: str) -> None:
        try:
            self._docker.stop_container(ref, timeout=self._config.stop_timeout_seconds)
        except Exception as exc:
            logger.debug("stop %s: %s", ref, exc)

    def _force_remove(self, ref: str) -> None:
        self._stop(ref)
        try:
            # v=False in the backend: reclaiming an execution body never removes
            # an application's data (AC-40).
            self._docker.remove_container(ref, force=True)
        except Exception as exc:
            logger.debug("remove %s: %s", ref, exc)


class ReconcileLoop:
    """Background thread: align once at boot, then a pass every interval.

    A thread rather than an asyncio task so a slow readiness gate (up to 90 s)
    cannot stall the HTTP surface the backend and app-proxy depend on — the
    manager must keep answering ``/v1/apps/{id}/route`` while it is nursing a
    sick instance back.

    Nothing here holds the process open: the thread is a daemon and ``stop()``
    is idempotent, so a systemd restart is a clean exit rather than a 90 s wait.
    """

    def __init__(self, config: Config, reconciler: Reconciler | None = None) -> None:
        self._config = config
        self._reconciler = reconciler or Reconciler(config)
        self._stop_event = threading.Event()
        self._first_pass = threading.Event()
        self._thread: threading.Thread | None = None
        self.passes = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._first_pass.clear()
        self._thread = threading.Thread(target=self._run, name="rtm-reconciler", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout)

    def wait_for_first_pass(self, timeout: float = 5.0) -> bool:
        return self._first_pass.wait(timeout)

    def _run(self) -> None:
        try:
            report = self._reconciler.startup_align()
            logger.info("startup alignment: %s", report.summary())
        except Exception:
            logger.exception("startup alignment failed; the periodic loop continues")
        finally:
            self.passes += 1
            self._first_pass.set()

        while not self._stop_event.wait(self._config.reconcile_interval_seconds):
            started = time.monotonic()
            try:
                self._reconciler.reconcile_once()
            except Exception:
                logger.exception("reconcile pass failed; retrying next interval")
            self.passes += 1
            logger.debug("reconcile pass %s took %.2fs", self.passes, time.monotonic() - started)
