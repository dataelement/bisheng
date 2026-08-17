"""Start-up probe and the route table (AC-18, AC-21, AC-25, AC-33).

The route table is the single most easily got-wrong piece of the compose form,
and the reason is 坑 30: on 114 the app-proxy runs as a *host* systemd unit, not
as a container. It cannot resolve ``bisheng-app-sales-report`` — docker's DNS
does not exist outside the network — and AC-33 forbids publishing a host port.
What is left, and what works identically in both deployment shapes, is the
container's address on the bridge: reachable from the host, unreachable from
anywhere else. So the manager answers with an address, never with a name.

The probe is the gate in front of every switch: the route's ``generation``
increments only after readiness, which is what makes "iterate a version" not
mean "serve 502s for a while" (AC-21).
"""

from __future__ import annotations

import pytest

from runtime_manager.api.schemas import DeployRequest, HealthIn, TierIn
from runtime_manager.errors import NotFoundError
from runtime_manager.probe import ProbeService
from runtime_manager.routing import RoutingService
from tests.fakes import FakeClock, FakeHostProbe, FakeHttpProbe, ImmediateScheduler

from .test_lifecycle import FakeProber


def _deploy_request(**overrides) -> DeployRequest:
    payload = {
        "app_id": "app-1",
        "slug": "sales-report",
        "version_id": "ver-0123456789abcdef",
        "version_no": 3,
        "image_ref": "bisheng-app/sales-report:3-ver-0123",
        "tier": TierIn(cpu=0.5, mem=512),
        "port": 8080,
        "health": HealthIn(path="/healthz"),
    }
    payload.update(overrides)
    return DeployRequest(**payload)


def _lifecycle(config, fake_docker, prober=None):
    from runtime_manager.admission import AdmissionService
    from runtime_manager.lifecycle import LifecycleService

    return LifecycleService(
        config,
        docker=fake_docker,
        admission=AdmissionService(config, host_probe=FakeHostProbe()),
        prober=prober or FakeProber(),
        scheduler=ImmediateScheduler(),
    )


def _started_container(fake_docker, name="bisheng-app-sales-report-ver-0123", ip="172.31.0.7"):
    cid = fake_docker.create_container(name, {"Image": "img", "Env": [], "HostConfig": {}})
    fake_docker.start_container(cid)
    fake_docker.get(cid).ip = ip
    return cid


def test_probe_ready_within_timeout(rtm_config, fake_docker):
    cid = _started_container(fake_docker)
    http = FakeHttpProbe([ConnectionRefusedError("connection refused"), 503, 200])
    service = ProbeService(rtm_config, docker=fake_docker, http=http, clock=FakeClock())

    outcome = service.wait_ready(cid, 8080, "/healthz", timeout=30)

    assert outcome.ready is True
    assert outcome.reason == ""
    # Dialled the bridge address, not a container name and not localhost (坑 30).
    assert http.requests[-1] == "http://172.31.0.7:8080/healthz"


def test_probe_timeout_returns_readable_reason(rtm_config, fake_docker):
    """AC-18 — "not ready" must say *why*; F055 shows this to a human."""
    cid = _started_container(fake_docker)
    http = FakeHttpProbe([ConnectionRefusedError("connection refused")])
    clock = FakeClock()
    service = ProbeService(rtm_config, docker=fake_docker, http=http, clock=clock)

    outcome = service.wait_ready(cid, 8080, "/healthz", timeout=5)

    assert outcome.ready is False
    assert "5" in outcome.reason
    assert "connection refused" in outcome.reason
    assert clock.slept, "the probe must back off between attempts, not spin"


def test_probe_reports_exited_container_instead_of_waiting(rtm_config, fake_docker):
    """A container that died is a verdict now, not in 90 seconds.

    Waiting out the full timeout here would be honest but useless: the usual
    cause is a start command that crashes instantly, and the fast answer is what
    makes F055's pre-flight feel like a check rather than a hang.
    """
    cid = _started_container(fake_docker)
    fake_docker.get(cid).running = False
    fake_docker.get(cid).exit_code = 78

    outcome = ProbeService(
        rtm_config, docker=fake_docker, http=FakeHttpProbe([ConnectionRefusedError("no")]), clock=FakeClock()
    ).wait_ready(cid, 8080, "/healthz", timeout=90)

    assert outcome.ready is False
    assert "exit" in outcome.reason.lower()
    assert "78" in outcome.reason


def test_probe_standalone_image(rtm_config, fake_docker):
    """AC-18 — the same readiness definition, with no app and no volume.

    F055's pre-flight and the approval-time preview instance both need "does
    this image come up" *before* an app exists. Sharing this path is what keeps
    pre-flight from drifting into a second, subtly different notion of ready.
    """
    http = FakeHttpProbe([200])
    service = ProbeService(rtm_config, docker=fake_docker, http=http, clock=FakeClock())

    outcome = service.probe_image(
        image_ref="bisheng-app/sales-report:3-ver-0123",
        env={"FOO": "bar"},
        port=8080,
        health_path="/healthz",
        timeout=30,
    )

    assert outcome.ready is True
    payload = fake_docker.last_call("create_container")["payload"]
    assert payload["HostConfig"]["PortBindings"] == {}
    assert payload["HostConfig"]["ReadonlyRootfs"] is True
    # No bind mount: a throwaway probe must never touch an app's real data.
    assert not payload["HostConfig"].get("Binds")
    assert "/data" in payload["HostConfig"]["Tmpfs"]
    assert payload["HostConfig"]["RestartPolicy"] == {"Name": "no"}
    # Cleaned up whatever the verdict — probe containers are never left behind.
    assert fake_docker.containers == {}


def test_probe_standalone_image_cleans_up_on_failure(rtm_config, fake_docker):
    service = ProbeService(
        rtm_config,
        docker=fake_docker,
        http=FakeHttpProbe([ConnectionRefusedError("nope")]),
        clock=FakeClock(),
    )

    outcome = service.probe_image(
        image_ref="img", env={}, port=8080, health_path="/", timeout=3
    )

    assert outcome.ready is False
    assert fake_docker.containers == {}


def test_route_returns_bridge_ip_port(rtm_config, fake_docker):
    """AC-25 / AC-33 — an address on the bridge: host-reachable, world-unreachable."""
    _lifecycle(rtm_config, fake_docker).deploy(_deploy_request())
    for container in fake_docker.containers.values():
        container.ip = "172.31.0.9"

    route = RoutingService(rtm_config, docker=fake_docker).get_route("app-1")

    assert route.upstream == "http://172.31.0.9:8080"
    assert route.version_id == "ver-0123456789abcdef"
    assert route.generation == 1
    # Not a container name: app-proxy is a host process and cannot resolve one.
    assert "bisheng-app-" not in route.upstream
    assert "127.0.0.1" not in route.upstream


def test_route_generation_bumps_only_after_probe_pass(rtm_config, fake_docker):
    """AC-21 — a version that never became ready never becomes the route."""
    from runtime_manager.errors import ProbeFailedError

    _lifecycle(rtm_config, fake_docker).deploy(_deploy_request())
    routing = RoutingService(rtm_config, docker=fake_docker)
    assert routing.get_route("app-1").generation == 1

    with pytest.raises(ProbeFailedError):
        _lifecycle(rtm_config, fake_docker, prober=FakeProber(ready=False, reason="timeout")).deploy(
            _deploy_request(version_id="ver-fedcba9876543210", version_no=4)
        )

    still = routing.get_route("app-1")
    assert still.generation == 1
    assert still.version_id == "ver-0123456789abcdef"

    _lifecycle(rtm_config, fake_docker).deploy(
        _deploy_request(version_id="ver-fedcba9876543210", version_no=4)
    )
    switched = routing.get_route("app-1")
    assert switched.generation == 2
    assert switched.version_id == "ver-fedcba9876543210"


def test_route_404_when_no_instance(rtm_config, fake_docker):
    with pytest.raises(NotFoundError):
        RoutingService(rtm_config, docker=fake_docker).get_route("nobody")


def test_route_404_when_stopped(rtm_config, fake_docker):
    """A stopped app has no upstream — app-proxy renders the stopped page."""
    lifecycle = _lifecycle(rtm_config, fake_docker)
    lifecycle.deploy(_deploy_request())
    lifecycle.stop("app-1")

    with pytest.raises(NotFoundError):
        RoutingService(rtm_config, docker=fake_docker).get_route("app-1")


def test_route_endpoint_shape(rtm_client, rtm_config, fake_docker):
    """``GET /v1/apps/{id}/route`` — the app-proxy's only question (D5.1)."""
    _lifecycle(rtm_config, fake_docker).deploy(_deploy_request())

    response = rtm_client.get("/v1/apps/app-1/route")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"upstream", "version_id", "generation"}
    assert body["upstream"].startswith("http://")


def test_route_endpoint_404(rtm_client):
    assert rtm_client.get("/v1/apps/ghost/route").status_code == 404


def test_probe_endpoint_app_and_standalone(rtm_client, rtm_config, fake_docker, monkeypatch):
    _lifecycle(rtm_config, fake_docker).deploy(_deploy_request())
    monkeypatch.setattr(
        "runtime_manager.probe.HttpxProbe.get", lambda self, url, timeout=2.0: 200
    )

    by_app = rtm_client.post("/v1/intents/probe", {"app_id": "app-1"})
    assert by_app.status_code == 200
    assert by_app.json() == {"ready": True, "reason": ""}

    standalone = rtm_client.post(
        "/v1/intents/probe",
        {"image_ref": "bisheng-app/x:1-aaaa", "port": 8080, "health": {"path": "/healthz"}},
    )
    assert standalone.status_code == 200
    assert standalone.json()["ready"] is True


def test_probe_endpoint_requires_app_or_image(rtm_client):
    assert rtm_client.post("/v1/intents/probe", {}).status_code == 400


@pytest.mark.docker
def test_real_probe_and_route_against_daemon():
    """Real bridge IP, real health endpoint, real switch with no dropped request.

    Runs in the CI docker stage and on 114 (T075): only there can we show that
    the address the manager hands out is actually dialable from the host while
    being unreachable from outside it (AC-33).
    """
    pytest.skip("executed in the CI docker stage / on 114, not in the unit suite")


def test_deploy_endpoint_end_to_end(rtm_client, rtm_config, fake_docker, monkeypatch):
    """``POST /v1/intents/deploy`` with the real readiness gate wired in.

    Lives here rather than in test_lifecycle because the deploy route's default
    prober is the real :class:`ProbeService` — this is the first point at which
    the whole chain (admission → create → probe → route) exists.
    """
    monkeypatch.setattr(
        "runtime_manager.admission.LinuxHostProbe.snapshot",
        lambda self: FakeHostProbe().snapshot(),
    )
    monkeypatch.setattr("runtime_manager.probe.HttpxProbe.get", lambda self, url, timeout=2.0: 200)

    response = rtm_client.post("/v1/intents/deploy", _deploy_request().model_dump())

    assert response.status_code == 200
    body = response.json()
    assert body["phase"] == "running"
    assert body["generation"] == 1

    route = rtm_client.get("/v1/apps/app-1/route")
    assert route.status_code == 200
    assert route.json()["generation"] == 1


def test_deploy_endpoint_reports_capacity_refusal(rtm_client, monkeypatch):
    """AC-19 / AC-65 — the backend needs the *reason* to render 待上线（资源不足）."""
    monkeypatch.setattr(
        "runtime_manager.admission.LinuxHostProbe.snapshot",
        lambda self: FakeHostProbe(mem_available_mb=2100).snapshot(),
    )

    response = rtm_client.post("/v1/intents/deploy", _deploy_request().model_dump())

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "capacity_exhausted"
    assert detail["reason"] == "insufficient_available_memory"
    assert detail["snapshot"]["mem_available_mb"] == 2100
