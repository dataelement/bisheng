"""Approval-time preview instances (F055 AC-26 / AC-27 / AC-28 / AC-29).

The properties worth a test are the ones that separate a preview from a deploy,
because getting any of them wrong looks fine locally and costs a production
application:

* a preview writes **no desired-state record**, so it consumes no instance slot
  and the reconciler neither adopts nor reclaims it (AC-26);
* its ``/data`` is a **tmpfs, never the app's bind** — trial data cannot reach
  production (AC-29);
* starting one **does not disturb the application's own instance**, even though
  both exist on the same daemon at the same time;
* reclaiming is **idempotent**, because three independent triggers can fire for
  the same session (AC-28).
"""

from __future__ import annotations

import pytest

from runtime_manager.admission import AdmissionService, Tier
from runtime_manager.api.schemas import DeployRequest, HealthIn, TierIn
from runtime_manager.config import (
    LABEL_MANAGED,
    LABEL_PREVIEW_EXPIRES_AT,
    LABEL_PREVIEW_SESSION,
    PREVIEW_MANAGED_VALUE,
)
from runtime_manager.errors import CapacityExhaustedError, InvalidRequestError, NotFoundError, ProbeFailedError
from runtime_manager.preview import PreviewService, preview_container_name
from tests.fakes import FakeHostProbe, ImmediateScheduler

from .test_lifecycle import FakeProber

SESSION = "prev-0123456789abcdef"


def _absent(fake_docker, name: str) -> bool:
    """The fake raises rather than answering ``None`` for an unknown container."""
    return name not in {c.name for c in fake_docker.containers.values()}


def _preview(config, fake_docker, prober=None, host_probe=None):
    return PreviewService(
        config,
        docker=fake_docker,
        admission=AdmissionService(config, host_probe=host_probe or FakeHostProbe()),
        prober=prober or FakeProber(),
    )


def _start(service, **overrides):
    payload = {
        "session_id": SESSION,
        "app_id": "app-1",
        "slug": "sales-report",
        "version_id": "ver-0123456789abcdef",
        "version_no": 4,
        "image_ref": "bisheng-app/sales-report:4-ver-0123",
        "tier": Tier(cpu=0.5, mem_mb=512),
        "port": 8080,
        "health_path": "/healthz",
        "platform_api_base": "https://platform.example.com",
        "base_path": f"/apps/preview/{SESSION}",
        "env": {"APP_OWN_SETTING": "1"},
    }
    payload.update(overrides)
    return service.start(**payload)


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


def test_start_answers_with_the_bridge_address_of_a_running_container(rtm_config, fake_docker):
    outcome = _start(_preview(rtm_config, fake_docker))

    container = fake_docker.get(preview_container_name(SESSION))
    assert container.running is True
    assert outcome.upstream == f"http://{container.ip}:8080"
    assert outcome.instance_id == container.id


def test_preview_data_is_a_tmpfs_and_never_the_application_volume(rtm_config, fake_docker):
    """AC-29 — trial data must not be able to reach the production database."""
    _start(_preview(rtm_config, fake_docker))

    host_config = fake_docker.get(preview_container_name(SESSION)).payload["HostConfig"]
    assert "Binds" not in host_config
    assert host_config["Tmpfs"]["/data"].startswith("rw,")
    # Non-root app user (uid 10001) must be able to create /data/app.db, or the
    # container exits 1 on start-up and the preview fails for a reason nobody
    # would guess from "preview did not become ready".
    assert "mode=1777" in host_config["Tmpfs"]["/data"]


def _env_of(fake_docker, name: str) -> dict[str, str]:
    raw = fake_docker.get(name).payload["Env"]
    return dict(entry.split("=", 1) for entry in raw)


def test_a_preview_gets_the_whole_environment_contract(rtm_config, fake_docker):
    """§5's names, all of them — a partial environment is a broken app, not a preview.

    The one that bites first is ``BISHENG_APP_DB_URL``: an app that is not told
    where its database lives exits on start-up, and the approver reads that as
    "this release is broken" rather than as "the platform forgot to tell it".
    """
    _start(_preview(rtm_config, fake_docker))

    env = _env_of(fake_docker, preview_container_name(SESSION))
    assert env["BISHENG_APP_DB_URL"] == "sqlite:////data/app.db"
    assert env["BISHENG_APP_DB_PATH"] == "/data/app.db"
    assert env["BISHENG_APP_ID"] == "app-1"
    assert env["BISHENG_APP_SLUG"] == "sales-report"
    assert env["BISHENG_APP_VERSION"] == "4"
    assert env["BISHENG_APP_VERSION_ID"] == "ver-0123456789abcdef"
    assert env["BISHENG_PLATFORM_API_BASE"] == "https://platform.example.com"
    assert env["PORT"] == env["BISHENG_APP_PORT"] == "8080"
    assert env["BISHENG_APP_HEALTH_PATH"] == "/healthz"
    # The app's own declared variables survive; platform-reserved names win.
    assert env["APP_OWN_SETTING"] == "1"


def test_the_preview_is_told_its_own_base_path_not_the_applications(rtm_config, fake_docker):
    """D5.2 — the same source runs at ``/apps/{slug}`` and at the preview entry."""
    _start(_preview(rtm_config, fake_docker))

    env = _env_of(fake_docker, preview_container_name(SESSION))
    assert env["BISHENG_APP_BASE_PATH"] == f"/apps/preview/{SESSION}"


def test_a_preview_carries_no_attachment_handle(rtm_config, fake_docker):
    """AC-29's other half: a trial upload must not land in production attachments.

    The app's storage bearer is per application and lifelong; handing it to a
    throwaway instance would write test files into the real attachment prefix,
    which is the same crossing the AC forbids for the database.
    """
    _start(_preview(rtm_config, fake_docker))

    env = _env_of(fake_docker, preview_container_name(SESSION))
    assert "BISHENG_APP_STORAGE_ENDPOINT" not in env
    assert "BISHENG_APP_STORAGE_TOKEN" not in env


def test_a_preview_is_labelled_preview_so_the_reconciler_cannot_see_it(rtm_config, fake_docker):
    """AC-26 — the reconciler filters ``bisheng.managed=true``; a preview is not it."""
    _start(_preview(rtm_config, fake_docker))

    labels = fake_docker.get(preview_container_name(SESSION)).labels
    assert labels[LABEL_MANAGED] == PREVIEW_MANAGED_VALUE
    assert labels[LABEL_PREVIEW_SESSION] == SESSION


def test_a_preview_never_restarts_itself(rtm_config, fake_docker):
    _start(_preview(rtm_config, fake_docker))

    host_config = fake_docker.get(preview_container_name(SESSION)).payload["HostConfig"]
    assert host_config["RestartPolicy"] == {"Name": "no"}
    assert host_config["PortBindings"] == {}
    assert host_config["PublishAllPorts"] is False


def test_the_tier_limits_are_fixed_on_the_preview_container(rtm_config, fake_docker):
    _start(_preview(rtm_config, fake_docker), tier=Tier(cpu=2.0, mem_mb=4096))

    host_config = fake_docker.get(preview_container_name(SESSION)).payload["HostConfig"]
    assert host_config["NanoCpus"] == 2_000_000_000
    assert host_config["Memory"] == 4096 * 1024 * 1024


def test_starting_a_preview_writes_no_desired_state_record(rtm_config, fake_docker):
    """AC-26 「不占应用运行实例名额」 — the quota is the sum over the records."""
    from runtime_manager.desired_state import get_store

    store = get_store(rtm_config)
    before_mb, before_cpu = store.committed()

    _start(_preview(rtm_config, fake_docker))

    assert store.list() == []
    assert store.committed() == (before_mb, before_cpu)
    assert store.get(SESSION) is None
    assert store.get("app-1") is None


def test_a_preview_leaves_the_applications_own_instance_alone(rtm_config, fake_docker):
    """The whole point of addressing by session rather than by app id."""
    from runtime_manager.desired_state import get_store
    from runtime_manager.lifecycle import LifecycleService

    lifecycle = LifecycleService(
        rtm_config,
        docker=fake_docker,
        admission=AdmissionService(rtm_config, host_probe=FakeHostProbe()),
        prober=FakeProber(),
        scheduler=ImmediateScheduler(),
    )
    lifecycle.deploy(
        DeployRequest(
            app_id="app-1",
            slug="sales-report",
            version_id="ver-live",
            version_no=3,
            image_ref="bisheng-app/sales-report:3-ver-live",
            tier=TierIn(cpu=0.5, mem=512),
            health=HealthIn(path="/healthz"),
        )
    )
    live = get_store(rtm_config).get("app-1")
    assert live is not None

    _start(_preview(rtm_config, fake_docker))

    after = get_store(rtm_config).get("app-1")
    assert after is not None
    assert after.container_name == live.container_name
    assert after.generation == live.generation
    assert fake_docker.get(live.container_name).running is True


def test_capacity_shortage_refuses_the_preview(rtm_config, fake_docker):
    """AC-26 — 「受编排器整体容量约束」: the memory is real even when the quota is not charged."""
    starved = FakeHostProbe(mem_total_mb=32768, mem_available_mb=2100)

    with pytest.raises(CapacityExhaustedError):
        _start(_preview(rtm_config, fake_docker, host_probe=starved))

    assert _absent(fake_docker, preview_container_name(SESSION))


def test_a_preview_that_never_becomes_ready_is_torn_down(rtm_config, fake_docker):
    """No record exists, so anything left behind would hold memory forever."""
    with pytest.raises(ProbeFailedError):
        _start(_preview(rtm_config, fake_docker, prober=FakeProber(ready=False, reason="exited on start-up")))

    assert _absent(fake_docker, preview_container_name(SESSION))


def test_restarting_the_same_session_replaces_the_stale_body(rtm_config, fake_docker):
    service = _preview(rtm_config, fake_docker)
    first = _start(service)
    second = _start(service)

    assert first.instance_id != second.instance_id
    assert fake_docker.get(preview_container_name(SESSION)).id == second.instance_id


def test_an_illegal_session_id_is_refused_before_anything_is_created(rtm_config, fake_docker):
    service = _preview(rtm_config, fake_docker)
    for bad in ("", "short", "../../etc", "has space", "a" * 65):
        with pytest.raises(InvalidRequestError):
            _start(service, session_id=bad)
    assert fake_docker.containers == {}


def test_a_preview_without_an_image_is_refused(rtm_config, fake_docker):
    with pytest.raises(InvalidRequestError):
        _start(_preview(rtm_config, fake_docker), image_ref="")


# ---------------------------------------------------------------------------
# route
# ---------------------------------------------------------------------------


def test_route_answers_the_bridge_address_and_the_version_being_tried(rtm_config, fake_docker):
    service = _preview(rtm_config, fake_docker)
    _start(service)

    route = service.route(SESSION)

    assert route["upstream"] == f"http://{fake_docker.get(preview_container_name(SESSION)).ip}:8080"
    assert route["version_id"] == "ver-0123456789abcdef"
    assert route["generation"] == 0


def test_route_of_an_unknown_session_is_404(rtm_config, fake_docker):
    with pytest.raises(NotFoundError):
        _preview(rtm_config, fake_docker).route("prev-doesnotexist00")


def test_route_of_a_reclaimed_preview_is_404(rtm_config, fake_docker):
    service = _preview(rtm_config, fake_docker)
    _start(service)
    service.stop(SESSION)

    with pytest.raises(NotFoundError):
        service.route(SESSION)


def test_route_of_a_stopped_but_present_container_is_404(rtm_config, fake_docker):
    service = _preview(rtm_config, fake_docker)
    _start(service)
    fake_docker.stop_container(preview_container_name(SESSION))

    with pytest.raises(NotFoundError):
        service.route(SESSION)


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


def test_stop_removes_the_container_and_is_idempotent(rtm_config, fake_docker):
    """AC-28 — terminal approval, the button and the timeout sweep all call this."""
    service = _preview(rtm_config, fake_docker)
    _start(service)

    assert service.stop(SESSION) == {"reclaimed": True}
    assert _absent(fake_docker, preview_container_name(SESSION))
    assert service.stop(SESSION) == {"reclaimed": False}


# ---------------------------------------------------------------------------
# intent RPC
# ---------------------------------------------------------------------------


def test_preview_intents_are_hmac_protected_like_every_other_intent(rtm_client):
    unsigned = rtm_client.post("/v1/intents/preview/stop", {"session_id": SESSION}, sign=False)
    assert unsigned.status_code == 401


def test_preview_start_stop_and_route_over_the_rpc(rtm_client, fake_docker, monkeypatch):
    from runtime_manager import preview as preview_module

    monkeypatch.setattr("runtime_manager.admission.LinuxHostProbe.snapshot", lambda self: FakeHostProbe().snapshot())
    monkeypatch.setattr(preview_module.PreviewService, "_get_prober", lambda self: FakeProber())

    started = rtm_client.post(
        "/v1/intents/preview",
        {
            "session_id": SESSION,
            "app_id": "app-1",
            "version_id": "ver-0123456789abcdef",
            "image_ref": "bisheng-app/sales-report:4",
            "tier": {"cpu": 0.5, "mem": 512},
            "health": {"path": "/healthz"},
        },
    )
    assert started.status_code == 200, started.text
    assert started.json()["upstream"].startswith("http://")

    route = rtm_client.get(f"/v1/previews/{SESSION}/route")
    assert route.status_code == 200, route.text
    assert route.json()["upstream"] == started.json()["upstream"]

    stopped = rtm_client.post("/v1/intents/preview/stop", {"session_id": SESSION})
    assert stopped.status_code == 200
    assert stopped.json() == {"reclaimed": True}

    assert rtm_client.get(f"/v1/previews/{SESSION}/route").status_code == 404


# ---------------------------------------------------------------------------
# expiry (AC-28's timeout leg)
# ---------------------------------------------------------------------------


def test_the_deadline_rides_on_the_container_as_a_label(rtm_config, fake_docker):
    _start(_preview(rtm_config, fake_docker), expires_at=1_900_000_000)

    labels = fake_docker.get(preview_container_name(SESSION)).labels
    assert labels[LABEL_PREVIEW_EXPIRES_AT] == "1900000000"


def test_the_sweep_removes_a_preview_past_its_deadline(rtm_config, fake_docker):
    service = _preview(rtm_config, fake_docker)
    _start(service, expires_at=1_000)

    assert service.reclaim_expired(now=1_001) == [SESSION]
    assert _absent(fake_docker, preview_container_name(SESSION))


def test_the_sweep_leaves_a_preview_inside_its_deadline_alone(rtm_config, fake_docker):
    service = _preview(rtm_config, fake_docker)
    _start(service, expires_at=2_000)

    assert service.reclaim_expired(now=1_999) == []
    assert fake_docker.get(preview_container_name(SESSION)).running is True


def test_a_preview_without_a_deadline_is_never_swept(rtm_config, fake_docker):
    """A missing label means "no deadline recorded", never "reclaim it now"."""
    service = _preview(rtm_config, fake_docker)
    _start(service)  # expires_at defaults to 0

    assert service.reclaim_expired(now=9_999_999_999) == []
    assert fake_docker.get(preview_container_name(SESSION)).running is True


def test_the_sweep_never_touches_an_applications_own_container(rtm_config, fake_docker):
    """It filters ``bisheng.managed=preview``; an app carries ``=true``."""
    from runtime_manager.lifecycle import LifecycleService

    lifecycle = LifecycleService(
        rtm_config,
        docker=fake_docker,
        admission=AdmissionService(rtm_config, host_probe=FakeHostProbe()),
        prober=FakeProber(),
        scheduler=ImmediateScheduler(),
    )
    lifecycle.deploy(
        DeployRequest(
            app_id="app-1",
            slug="sales-report",
            version_id="ver-live",
            version_no=3,
            image_ref="bisheng-app/sales-report:3-ver-live",
            tier=TierIn(cpu=0.5, mem=512),
            health=HealthIn(path="/healthz"),
        )
    )
    live_name = next(c.name for c in fake_docker.containers.values() if c.labels.get(LABEL_MANAGED) == "true")

    assert _preview(rtm_config, fake_docker).reclaim_expired(now=9_999_999_999) == []
    assert fake_docker.get(live_name).running is True


def test_the_reconcile_pass_runs_the_preview_sweep(rtm_config, fake_docker):
    """AC-28 without a platform timer: the loop that already exists carries it."""
    from runtime_manager.reconciler import Reconciler

    _start(_preview(rtm_config, fake_docker), expires_at=1)

    report = Reconciler(rtm_config, docker=fake_docker, prober=FakeProber()).reconcile_once()

    assert SESSION in report.reclaimed
    assert _absent(fake_docker, preview_container_name(SESSION))
