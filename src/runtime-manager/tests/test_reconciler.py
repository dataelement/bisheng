"""Reconciler — the loop that exists because docker leaves one hole open.

坑 17 / K3 is the whole justification for this file: on a single docker daemon
the ``HEALTHCHECK`` result and the restart policy are **not wired together**. A
container whose process stays alive but answers 500 forever is, as far as
dockerd is concerned, working as intended. So the division of labour is:

* **process exited** → docker's own ``unless-stopped`` backoff. The reconciler
  does *not* re-implement it (D4 备选 A rejected: it would also mean nobody
  restarts anything while the manager is down, which breaks AC-22).
* **alive but unhealthy** → nobody but us. Two consecutive rounds, then rebuild.
* **nothing at all where something should be** → recreate.
* **something where nothing should be** → reclaim.

The reverse tests carry as much weight as the positive ones. A reconciler that
reclaims aggressively is a reconciler that deletes a customer's onlyoffice
container the first time somebody runs it on 114, so "does not touch" is
asserted explicitly for foreign containers, probe containers, other apps'
containers, and containers inside their retirement grace window.

Timing is asserted with :class:`~tests.fakes.FakeClock`, never ``sleep``: the
"5 minutes" in AC-20 is a budget made of four named terms, and a test that
waits for real seconds would verify none of them.

Real ``docker kill`` / real ``HEALTHCHECK`` flipping to unhealthy is marked
``@pytest.mark.docker`` (CI docker stage + 114, T075 步 6 / T095).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from runtime_manager.admission import AdmissionService
from runtime_manager.api.schemas import DeployRequest, TierIn
from runtime_manager.config import (
    LABEL_APP_ID,
    LABEL_GENERATION,
    LABEL_MANAGED,
)
from runtime_manager.desired_state import (
    ALL_PHASES,
    DESIRED_STOPPED,
    PHASE_RUNNING,
    PHASE_UNHEALTHY,
    get_store,
    reset_stores,
)
from runtime_manager.lifecycle import LifecycleService, container_name
from runtime_manager.reconciler import (
    HEALTHCHECK_DETECTION_BUDGET_SECONDS,
    RECOVERY_BUDGET_SECONDS,
    UNHEALTHY_ROUNDS_BEFORE_REBUILD,
    ReconcileLoop,
    Reconciler,
    recovery_budget_seconds,
)
from tests.fakes import (
    FakeClock,
    FakeDockerError,
    FakeHostProbe,
    ImmediateScheduler,
    RecordingScheduler,
)


@dataclass(frozen=True)
class _Outcome:
    ready: bool
    reason: str = ""


class FakeProber:
    """Readiness gate double that *spends time* on the injected clock.

    Spending the clock is the point: the rebuild leg of the AC-20 budget is
    "重建拉起并探活 ≤ 90s", and a prober that returned instantly would let the
    budget test pass no matter how slow the real gate is.
    """

    def __init__(self, ready: bool = True, reason: str = "", clock=None, elapsed: float = 0.0) -> None:
        self.ready = ready
        self.reason = reason
        self.clock = clock
        self.elapsed = elapsed
        self.calls: list[tuple] = []

    def wait_ready(self, container, port, health_path, timeout=None):
        self.calls.append((container, port, health_path))
        if self.clock is not None and self.elapsed:
            self.clock.advance(self.elapsed)
        return _Outcome(ready=self.ready, reason=self.reason)


def _request(**overrides) -> DeployRequest:
    payload = {
        "app_id": "app-1",
        "slug": "sales-report",
        "version_id": "ver-0123456789abcdef",
        "version_no": 3,
        "image_ref": "bisheng-app/sales-report:3-ver-0123",
        "tier": TierIn(cpu=0.5, mem=512),
        "port": 8080,
        "env": {},
        "platform_api_base": "https://bisheng.example.com/api",
    }
    payload.update(overrides)
    return DeployRequest(**payload)


def _deploy(config, fake_docker, request: DeployRequest | None = None, scheduler=None) -> str:
    """Put one app into the desired state the honest way (through deploy)."""
    request = request or _request()
    service = LifecycleService(
        config,
        docker=fake_docker,
        admission=AdmissionService(config, host_probe=FakeHostProbe()),
        prober=FakeProber(),
        scheduler=scheduler or ImmediateScheduler(),
    )
    service.deploy(request)
    return container_name(request.slug, request.version_id)


def _reconciler(config, fake_docker, *, store=None, prober=None, clock=None) -> Reconciler:
    return Reconciler(
        config,
        docker=fake_docker,
        store=store if store is not None else get_store(config),
        prober=prober or FakeProber(),
        clock=clock or FakeClock(),
    )


def _foreign(fake_docker, name: str) -> str:
    """A container this platform did not create — 114 runs several."""
    return fake_docker.create_container(name, {"Image": "onlyoffice/documentserver", "Labels": {}})


# ---------------------------------------------------------------------------
# 1. missing / exited — and the line between us and the daemon
# ---------------------------------------------------------------------------


def test_missing_container_recreated(rtm_config, fake_docker):
    """Desired state says running, the daemon has nothing → create it again."""
    name = _deploy(rtm_config, fake_docker)
    fake_docker.containers.clear()

    report = _reconciler(rtm_config, fake_docker).reconcile_once()

    assert report.recreated == ["app-1"]
    created = fake_docker.last_call("create_container")
    assert created["name"] == name
    assert fake_docker.get(name).running is True
    record = get_store(rtm_config).get("app-1")
    assert record.phase == PHASE_RUNNING
    assert record.container_id == fake_docker.get(name).id
    # The rebuilt instance keeps the app's data: same host bind, untouched.
    assert created["payload"]["HostConfig"]["Binds"] == [f"{rtm_config.app_data_dir('app-1')}:/data:rw"]


def test_exited_container_is_started_not_rebuilt(rtm_config, fake_docker):
    """A dead *process* is docker's job (D4): we nudge, we do not recreate.

    Recreating here would throw away the daemon's exponential backoff and, worse,
    hide a crash-looping app behind a fresh container id every 15 seconds.
    """
    name = _deploy(rtm_config, fake_docker)
    fake_docker.get(name).running = False
    fake_docker.get(name).exit_code = 1
    creates_before = fake_docker.call_count("create_container")

    report = _reconciler(rtm_config, fake_docker).reconcile_once()

    assert report.started == ["app-1"]
    assert report.recreated == []
    assert fake_docker.call_count("create_container") == creates_before
    assert fake_docker.get(name).running is True


# ---------------------------------------------------------------------------
# 2. unhealthy-but-alive — the hole docker leaves open (坑 17 / AC-20)
# ---------------------------------------------------------------------------


def test_unhealthy_two_rounds_rebuilds(rtm_config, fake_docker):
    """AC-20 second failure class: stop → rm → run, and the volume never moves."""
    name = _deploy(rtm_config, fake_docker)
    old_id = fake_docker.get(name).id
    fake_docker.set_health(name, "unhealthy")
    reconciler = _reconciler(rtm_config, fake_docker)

    first = reconciler.reconcile_once()
    assert first.rebuilt == []
    assert fake_docker.call_count("remove_container") == 0
    assert get_store(rtm_config).get("app-1").phase == PHASE_UNHEALTHY
    assert get_store(rtm_config).get("app-1").unhealthy_rounds == 1

    # The daemon keeps reporting unhealthy — nothing in docker will act on it.
    fake_docker.set_health(name, "unhealthy")
    second = reconciler.reconcile_once()

    assert second.rebuilt == ["app-1"]
    assert fake_docker.call_count("remove_container") == 1
    record = get_store(rtm_config).get("app-1")
    assert record.phase == PHASE_RUNNING
    assert record.unhealthy_rounds == 0
    assert record.container_id != old_id
    # Same name, same bind: the rebuild is a new execution body over the old data.
    payload = fake_docker.last_call("create_container")
    assert payload["name"] == name
    assert payload["payload"]["HostConfig"]["Binds"] == [f"{rtm_config.app_data_dir('app-1')}:/data:rw"]


def test_unhealthy_that_recovers_is_not_rebuilt(rtm_config, fake_docker):
    """One bad round is a blip. Rebuilding on it would restart apps for a hiccup."""
    name = _deploy(rtm_config, fake_docker)
    reconciler = _reconciler(rtm_config, fake_docker)

    fake_docker.set_health(name, "unhealthy")
    reconciler.reconcile_once()
    fake_docker.set_health(name, "healthy")
    report = reconciler.reconcile_once()

    assert report.rebuilt == []
    assert fake_docker.call_count("remove_container") == 0
    assert get_store(rtm_config).get("app-1").unhealthy_rounds == 0
    assert get_store(rtm_config).get("app-1").phase == PHASE_RUNNING


def test_rebuild_threshold_is_two_rounds(rtm_config):
    """The constant is part of the AC-20 budget, not a tunable someone can drift."""
    assert UNHEALTHY_ROUNDS_BEFORE_REBUILD == 2


def test_recovery_budget_within_5min(rtm_config, fake_docker):
    """AC-20 — the five minutes, decomposed and measured on an injected clock.

    healthcheck verdict (interval 10s × retries 3) + reconcile perception
    (2 × 15s rounds) + rebuild and readiness gate (≤ 90s) — all four terms are
    named, and their sum is asserted twice: analytically against the config, and
    empirically by driving the loop until the instance is actually back.
    """
    name = _deploy(rtm_config, fake_docker)
    old_id = fake_docker.get(name).id
    clock = FakeClock()
    prober = FakeProber(clock=clock, elapsed=45.0)
    reconciler = _reconciler(rtm_config, fake_docker, prober=prober, clock=clock)

    # t0 = the moment the app wedges. Docker needs interval × retries to notice.
    clock.advance(HEALTHCHECK_DETECTION_BUDGET_SECONDS)
    fake_docker.set_health(name, "unhealthy")

    for _ in range(10):
        fake_docker.set_health(name, "unhealthy")
        report = reconciler.reconcile_once()
        if report.rebuilt:
            break
        clock.advance(rtm_config.reconcile_interval_seconds)
    else:  # pragma: no cover - would mean the reconciler never converges
        pytest.fail("the reconciler never rebuilt the wedged instance")

    assert fake_docker.get(name).id != old_id
    assert fake_docker.get(name).running is True
    assert clock.now <= RECOVERY_BUDGET_SECONDS
    assert recovery_budget_seconds(rtm_config) <= RECOVERY_BUDGET_SECONDS


# ---------------------------------------------------------------------------
# 3. orphans — and everything we must not touch
# ---------------------------------------------------------------------------


def test_orphan_container_reclaimed(rtm_config, fake_docker):
    """A managed container nobody declared is capacity nobody is accounting for."""
    _deploy(rtm_config, fake_docker)
    orphan = "bisheng-app-ghost-deadbeef"
    fake_docker.create_container(
        orphan,
        {
            "Image": "bisheng-app/ghost:1",
            "Labels": {LABEL_MANAGED: "true", LABEL_APP_ID: "app-ghost", LABEL_GENERATION: "1"},
        },
    )
    fake_docker.start_container(orphan)

    report = _reconciler(rtm_config, fake_docker).reconcile_once()

    assert report.reclaimed == [orphan]
    with pytest.raises(FakeDockerError):
        fake_docker.get(orphan)


def test_foreign_and_probe_containers_are_never_touched(rtm_config, fake_docker):
    """不误杀 ①: no label of ours, or a probe's label → not ours to reclaim.

    114 runs onlyoffice, rabbitmq and friends on the same daemon. A reclaim rule
    written as "anything not in my desired state" instead of "anything *I*
    created that is not in my desired state" takes them all down.
    """
    _deploy(rtm_config, fake_docker)
    _foreign(fake_docker, "onlyoffice-documentserver")
    fake_docker.create_container(
        "bisheng-probe-abc123",
        {"Image": "bisheng-app/x:1", "Labels": {LABEL_MANAGED: "probe"}},
    )

    report = _reconciler(rtm_config, fake_docker).reconcile_once()

    assert report.reclaimed == []
    assert fake_docker.get("onlyoffice-documentserver") is not None
    assert fake_docker.get("bisheng-probe-abc123") is not None
    assert fake_docker.call_count("remove_container") == 0


def test_other_apps_container_is_not_reclaimed(rtm_config, fake_docker):
    """不误杀 ②: two declared apps, and a round that leaves both alone."""
    name_a = _deploy(rtm_config, fake_docker, _request())
    name_b = _deploy(
        rtm_config,
        fake_docker,
        _request(app_id="app-2", slug="hr-portal", version_id="ver-fedcba9876543210"),
    )

    report = _reconciler(rtm_config, fake_docker).reconcile_once()

    assert report.reclaimed == []
    assert fake_docker.get(name_a).running is True
    assert fake_docker.get(name_b).running is True


def test_retiring_container_within_grace_is_not_reclaimed(rtm_config, fake_docker):
    """不误杀 ③: the previous version is still serving in-flight requests (AC-21).

    Reclaiming it here would turn the 30 s grace window — the entire reason a
    version switch does not 502 — into a race the reconciler wins.
    """
    scheduler = RecordingScheduler()
    old_name = _deploy(rtm_config, fake_docker, _request(), scheduler=scheduler)
    _deploy(rtm_config, fake_docker, _request(version_id="ver-99998888aaaabbbb"), scheduler=scheduler)
    assert get_store(rtm_config).get("app-1").retiring == [old_name]

    report = _reconciler(rtm_config, fake_docker).reconcile_once()

    assert report.reclaimed == []
    assert fake_docker.get(old_name) is not None


def test_stopped_app_is_not_resurrected(rtm_config, fake_docker):
    """A stopped app stays stopped: the reconciler must not fight an operator.

    ``unless-stopped`` says the same thing to the daemon; saying it in two places
    is deliberate, because the reconciler is the half that reads desired state.
    """
    name = _deploy(rtm_config, fake_docker)
    LifecycleService(
        rtm_config, docker=fake_docker, admission=AdmissionService(rtm_config, host_probe=FakeHostProbe())
    ).stop("app-1")
    creates_before = fake_docker.call_count("create_container")

    report = _reconciler(rtm_config, fake_docker).reconcile_once()

    assert report.recreated == []
    assert report.started == []
    assert report.reclaimed == []
    assert fake_docker.call_count("create_container") == creates_before
    assert fake_docker.get(name).running is False
    assert get_store(rtm_config).get("app-1").desired == DESIRED_STOPPED


# ---------------------------------------------------------------------------
# 4. control plane down / restarted (AC-22, AC-50)
# ---------------------------------------------------------------------------


def test_manager_restart_does_not_touch_running_containers(rtm_config, fake_docker):
    """AC-22 — containers belong to dockerd; a manager restart is a no-op for them."""
    name = _deploy(rtm_config, fake_docker)
    fake_docker.set_health(name, "healthy")

    # "Restart": drop every in-process cache and re-read the state file.
    reset_stores()
    store = get_store(rtm_config)
    report = _reconciler(rtm_config, fake_docker, store=store).startup_align()

    assert fake_docker.call_count("stop_container") == 0
    assert fake_docker.call_count("remove_container") == 0
    assert fake_docker.get(name).running is True
    assert report.reclaimed == []
    assert store.get("app-1").version_id == "ver-0123456789abcdef"


def test_startup_full_reconcile_from_labels(rtm_config, fake_docker):
    """AC-50 — the state file is a cache; the labels on the containers are the truth.

    Losing ``{data_root}/state/desired-state.json`` (disk wipe, bad restore, a
    fresh manager pointed at a running host) must not orphan every application:
    the containers carry everything needed to rebuild the record, so recovery
    runs *before* orphan reclaim and the apps keep serving.
    """
    name = _deploy(rtm_config, fake_docker)
    generation = get_store(rtm_config).get("app-1").generation

    rtm_config.state_path.unlink()
    reset_stores()
    store = get_store(rtm_config)
    assert store.list() == []

    report = _reconciler(rtm_config, fake_docker, store=store).startup_align()

    assert report.recovered == ["app-1"]
    assert report.reclaimed == []
    recovered = store.get("app-1")
    assert recovered.version_id == "ver-0123456789abcdef"
    assert recovered.version_no == 3
    assert recovered.slug == "sales-report"
    assert recovered.tier_cpu == 0.5
    assert recovered.tier_mem_mb == 512
    assert recovered.port == 8080
    assert recovered.generation == generation
    assert recovered.container_name == name
    assert recovered.container_id == fake_docker.get(name).id
    assert recovered.env["BISHENG_APP_ID"] == "app-1"
    assert recovered.phase in ALL_PHASES
    assert fake_docker.get(name).running is True
    # Recovered capacity is charged again — otherwise the next admission would
    # happily double-book the host it just re-adopted.
    assert store.committed() == (512, 0.5)


def test_label_recovery_keeps_newest_generation_and_reclaims_the_older(rtm_config, fake_docker):
    """A crash mid-switch leaves two containers; exactly one of them is current."""
    scheduler = RecordingScheduler()
    old_name = _deploy(rtm_config, fake_docker, _request(), scheduler=scheduler)
    new_name = _deploy(rtm_config, fake_docker, _request(version_id="ver-99998888aaaabbbb"), scheduler=scheduler)

    rtm_config.state_path.unlink()
    reset_stores()
    store = get_store(rtm_config)

    report = _reconciler(rtm_config, fake_docker, store=store).startup_align()

    assert store.get("app-1").container_name == new_name
    assert store.get("app-1").generation == 2
    assert report.reclaimed == [old_name]
    assert fake_docker.get(new_name).running is True


def test_one_app_oom_does_not_affect_others(rtm_config, fake_docker):
    """AC-47 — the blast radius of one app hitting its memory limit is that app."""
    name_a = _deploy(rtm_config, fake_docker, _request())
    name_b = _deploy(
        rtm_config,
        fake_docker,
        _request(app_id="app-2", slug="hr-portal", version_id="ver-fedcba9876543210"),
    )
    store = get_store(rtm_config)
    b_before = store.get("app-2")
    b_id, b_generation = b_before.container_id, b_before.generation

    # The kernel OOM killer took app-1's process; the container is exited (137).
    fake_docker.get(name_a).running = False
    fake_docker.get(name_a).exit_code = 137
    marker = len(fake_docker.calls)

    report = _reconciler(rtm_config, fake_docker).reconcile_once()

    assert report.started == ["app-1"]
    touched = {
        kwargs.get("container")
        for method, kwargs in fake_docker.calls[marker:]
        if method in {"start_container", "stop_container", "remove_container"}
    }
    assert touched <= {name_a, fake_docker.get(name_a).id}
    assert fake_docker.get(name_b).running is True
    after = store.get("app-2")
    assert (after.container_id, after.generation, after.phase) == (b_id, b_generation, PHASE_RUNNING)


# ---------------------------------------------------------------------------
# 5. the loop itself
# ---------------------------------------------------------------------------


def test_loop_aligns_on_start_and_stops_cleanly(rtm_config, fake_docker):
    """The process boots → align once → keep reconciling; shutdown must not hang."""
    _deploy(rtm_config, fake_docker)
    loop = ReconcileLoop(rtm_config, _reconciler(rtm_config, fake_docker))
    try:
        loop.start()
        assert loop.wait_for_first_pass(timeout=5.0) is True
        assert loop.passes >= 1
    finally:
        loop.stop(timeout=5.0)
    assert loop.running is False


def test_loop_survives_a_backend_outage(rtm_config, fake_docker):
    """dockerd bouncing must not kill the reconcile thread — degraded, not dead."""
    _deploy(rtm_config, fake_docker)
    fake_docker.reachable = False
    reconciler = _reconciler(rtm_config, fake_docker)

    report = reconciler.reconcile_once()  # must not raise

    assert report.failures
    assert fake_docker.get(container_name("sales-report", "ver-0123456789abcdef")).running is True


@pytest.mark.docker
def test_real_unhealthy_container_is_rebuilt_within_the_budget():
    """The half a fake cannot prove: a real HEALTHCHECK flipping to unhealthy.

    ``docker kill --signal=SIGSTOP`` / a health endpoint forced to 500, then the
    wall-clock time to a serving instance — CI docker stage and 114 (T075 步 6,
    T095).
    """
    pytest.skip("executed in the CI docker stage / on 114, not in the unit suite")
