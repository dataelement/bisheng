"""Read side — status, logs, runtime status (AC-23 / AC-55).

Three endpoints with one job: let the platform answer "what is this app doing"
without the platform ever learning what a container is. So the assertions here
are as much about *vocabulary* as behaviour — INV-33 says a field name in these
payloads must survive F059 swapping dockerd for k8s, which means no ``container``
and no ``compose`` anywhere in a key.

The logs endpoint carries the one promise that is easy to overstate. AC-55 says
"密钥值不出现"; what is actually implemented (D14) is a literal replacement of
**values the platform itself injected** into the instance. The application's own
prints are not scrubbed, because a general secret detector over arbitrary
application output is a promise nobody can keep — leaked keys are caught by
F055's publish-time scan instead. ``test_logs_do_not_pretend_to_redact_app_output``
exists to keep that boundary from silently drifting into a false claim.

Real ``docker logs`` output (rotation windows, multiplexed stdout/stderr framing)
is a real-daemon question, marked ``@pytest.mark.docker``.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from runtime_manager.admission import AdmissionService
from runtime_manager.api.schemas import DeployRequest, TierIn
from runtime_manager.config import set_config
from runtime_manager.desired_state import ALL_PHASES, get_store
from runtime_manager.lifecycle import LifecycleService, container_name
from tests.fakes import FakeHostProbe

APP_ID = "app-1"
SLUG = "sales-report"
VERSION_ID = "ver-0123456789abcdef"

STATUS_FIELDS = {
    "instance_id",
    "phase",
    "health",
    "current_version_id",
    "started_at",
    "restart_count",
    "last_probe_at",
}


class _Ready:
    def wait_ready(self, container, port, health_path, timeout=None):
        class _Outcome:
            ready = True
            reason = ""

        return _Outcome()


@pytest.fixture(autouse=True)
def _readable_host(monkeypatch):
    """``/proc/meminfo`` does not exist on every dev machine; the numbers do."""
    monkeypatch.setattr(
        "runtime_manager.admission.LinuxHostProbe.snapshot",
        lambda self: FakeHostProbe().snapshot(),
    )


def _deploy(config, fake_docker, **env) -> str:
    request = DeployRequest(
        app_id=APP_ID,
        slug=SLUG,
        version_id=VERSION_ID,
        version_no=3,
        image_ref="bisheng-app/sales-report:3-ver-0123",
        tier=TierIn(cpu=0.5, mem=512),
        port=8080,
        env=env,
        platform_api_base="https://bisheng.example.com/api",
    )
    LifecycleService(
        config,
        docker=fake_docker,
        admission=AdmissionService(config, host_probe=FakeHostProbe()),
        prober=_Ready(),
    ).deploy(request)
    return container_name(SLUG, VERSION_ID)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_shape(rtm_client, rtm_config, fake_docker):
    """AC-23 — exactly the seven agreed fields, and not one form-specific name."""
    name = _deploy(rtm_config, fake_docker)
    fake_docker.set_health(name, "healthy")

    response = rtm_client.get(f"/v1/apps/{APP_ID}/status")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == STATUS_FIELDS
    assert body["phase"] in ALL_PHASES
    assert body["current_version_id"] == VERSION_ID
    assert body["health"] == "healthy"
    # INV-33: this payload has to survive F059 replacing dockerd with k8s.
    blob = " ".join(body).lower()
    assert "container" not in blob
    assert "compose" not in blob


def test_status_reports_live_health_and_total_restarts(rtm_client, rtm_config, fake_docker):
    """Restarts are the daemon's *and* ours, summed — both are recoveries.

    A rebuild resets the new container's ``RestartCount`` to zero, so reporting
    only the daemon's number would make an app that has been rebuilt six times
    look untouched on the detail page.
    """
    name = _deploy(rtm_config, fake_docker)
    fake_docker.get(name).restart_count = 1
    fake_docker.set_health(name, "unhealthy")
    get_store(rtm_config).mutate(APP_ID, restart_count=2)

    body = rtm_client.get(f"/v1/apps/{APP_ID}/status").json()

    assert body["health"] == "unhealthy"
    assert body["phase"] == "unhealthy"
    assert body["restart_count"] == 3


def test_status_404_when_no_instance(rtm_client):
    response = rtm_client.get("/v1/apps/app-nope/status")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------


def test_logs_tail_since_keyword(rtm_client, rtm_config, fake_docker):
    """AC-23 / AC-55 — the three filters, and where each one is applied.

    ``tail`` and ``since`` go to the daemon (they are the rotation window we can
    actually narrow); ``keyword`` filters what came back. Applying keyword
    daemon-side is not possible, and pretending otherwise would silently change
    what ``tail=200`` means.
    """
    name = _deploy(rtm_config, fake_docker)
    fake_docker.get(name).logs = "\n".join(
        [
            "2026-08-17T10:00:00Z INFO booted",
            "2026-08-17T10:00:01Z ERROR ValueError: bad row",
            "2026-08-17T10:00:02Z INFO served /health",
        ]
    )

    response = rtm_client.get(f"/v1/apps/{APP_ID}/logs", params={"tail": 50, "since": 1700000000, "keyword": "error"})

    assert response.status_code == 200
    lines = response.json()["lines"]
    assert len(lines) == 1
    assert "ValueError" in lines[0]
    call = fake_docker.last_call("container_logs")
    assert call["tail"] == 50
    assert call["since"] == 1700000000


def test_logs_since_accepts_a_relative_window(rtm_client, rtm_config, fake_docker):
    """``since=30m`` is what a human types; the daemon wants epoch seconds."""
    _deploy(rtm_config, fake_docker)

    before = int(time.time())
    response = rtm_client.get(f"/v1/apps/{APP_ID}/logs", params={"since": "30m"})

    assert response.status_code == 200
    since = fake_docker.last_call("container_logs")["since"]
    assert before - 1800 - 5 <= since <= before - 1800 + 5


def test_logs_rejects_an_unparseable_since(rtm_client, rtm_config, fake_docker):
    _deploy(rtm_config, fake_docker)
    response = rtm_client.get(f"/v1/apps/{APP_ID}/logs", params={"since": "last tuesday"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_request"


def test_logs_redact_known_injected_secrets(rtm_client, rtm_config, fake_docker):
    """AC-55 — values *we* put in the instance never come back out in a log line."""
    secret = "attach-tok-9f3c8b21d4e6"
    name = _deploy(rtm_config, fake_docker, BISHENG_APP_STORAGE_TOKEN=secret)
    fake_docker.get(name).logs = f"INFO uploading with token={secret}\n"

    lines = rtm_client.get(f"/v1/apps/{APP_ID}/logs").json()["lines"]

    assert secret not in "\n".join(lines)
    assert "***" in lines[0]


def test_logs_do_not_pretend_to_redact_app_output(rtm_client, rtm_config, fake_docker):
    """The boundary D14 draws on purpose: no general-purpose secret scrubbing.

    A regex sweep over arbitrary application output would be a promise the
    platform cannot keep (and would mangle legitimate output). Publish-time
    scanning (F055) is where leaked keys are caught; this test is here so the
    day someone "improves" redaction, they read *why* first.
    """
    name = _deploy(rtm_config, fake_docker)
    fake_docker.get(name).logs = "INFO my own api_key=sk-live-not-injected-by-us\n"

    lines = rtm_client.get(f"/v1/apps/{APP_ID}/logs").json()["lines"]

    assert "sk-live-not-injected-by-us" in lines[0]


def test_logs_empty_when_the_instance_printed_nothing(rtm_client, rtm_config, fake_docker):
    _deploy(rtm_config, fake_docker)
    assert rtm_client.get(f"/v1/apps/{APP_ID}/logs").json() == {"lines": []}


def test_logs_404_when_no_instance(rtm_client):
    assert rtm_client.get("/v1/apps/app-nope/logs").status_code == 404


# ---------------------------------------------------------------------------
# runtime status
# ---------------------------------------------------------------------------


def test_runtime_status_shape(rtm_client, rtm_config, fake_docker):
    """AC-23 — the super-admin's "is this host able to run apps at all" answer."""
    _deploy(rtm_config, fake_docker)

    body = rtm_client.get("/v1/runtime/status").json()

    assert set(body) == {"backend_available", "supported_runtimes", "capacity", "preflight"}
    assert body["backend_available"] is True
    assert body["supported_runtimes"] == ["python3.11"]
    capacity = body["capacity"]
    assert capacity["readable"] is True
    assert capacity["total_mb"] == 32768
    assert capacity["committed_mb"] == 512
    assert capacity["instances"] == 1
    for key in ("mem_available_mb", "cpu", "committed_cpu", "reserve_mb", "overcommit_ratio"):
        assert key in capacity
    checks = {item["name"]: item for item in body["preflight"]}
    assert checks["orchestration_backend"]["ok"] is True
    assert checks["application_network"]["ok"] is True
    assert checks["data_root_writable"]["ok"] is True
    assert checks["host_data_root_mapping"]["ok"] is True
    assert checks["runtime_templates"]["ok"] is True
    assert checks["base_images"]["ok"] is False  # nothing pulled in the fake daemon
    assert all({"name", "ok", "detail"} == set(item) for item in body["preflight"])


def test_runtime_status_flags_a_missing_application_network(rtm_client, fake_docker):
    """The 114 failure that costs an afternoon: ``bisheng-apps`` was never created.

    Without it *every* deploy fails at create time with a daemon error nobody
    reads as "run one ``docker network create``", so the pre-flight has to say it
    in words before the first app is ever published.
    """
    fake_docker.networks = []

    body = rtm_client.get("/v1/runtime/status").json()

    check = next(item for item in body["preflight"] if item["name"] == "application_network")
    assert check["ok"] is False
    assert "bisheng-apps" in check["detail"]


def test_runtime_status_flags_a_relative_host_data_root(rtm_client, rtm_config):
    """The compose-shape misconfiguration that dockerd rejects on every bind.

    ``RTM_HOST_DATA_ROOT`` is the *host* side of the volume, so a relative value
    (the shape you get from reusing ``${DOCKER_VOLUME_DIRECTORY:-.}``) makes the
    daemon refuse every container create. Nothing else in the process can tell
    you that: it is the daemon's rule, about a path this process never opens.
    """
    set_config(rtm_config.with_overrides(host_data_root=Path("./data/app-runtime")))
    try:
        body = rtm_client.get("/v1/runtime/status").json()
    finally:
        set_config(rtm_config)

    check = next(item for item in body["preflight"] if item["name"] == "host_data_root_mapping")
    assert check["ok"] is False
    assert "RTM_HOST_DATA_ROOT" in check["detail"]


def test_backend_unavailable_reports_not_500(rtm_client, rtm_config, fake_docker):
    """dockerd down is an *answer*, not a crash (backend maps 503 → 16121)."""
    _deploy(rtm_config, fake_docker)
    fake_docker.reachable = False

    runtime_status = rtm_client.get("/v1/runtime/status")
    assert runtime_status.status_code == 200
    assert runtime_status.json()["backend_available"] is False

    for path in (f"/v1/apps/{APP_ID}/status", f"/v1/apps/{APP_ID}/logs"):
        response = rtm_client.get(path)
        assert response.status_code == 503, path
        assert response.json()["detail"]["code"] == "backend_unavailable"


def test_runtime_status_survives_an_unreadable_host(rtm_client, monkeypatch):
    """No ``/proc/meminfo`` (a non-Linux host, a weird container) → say so, don't 500."""
    from runtime_manager.admission import HostProbeUnavailable

    def _boom(self):
        raise HostProbeUnavailable("cannot read /proc/meminfo")

    monkeypatch.setattr("runtime_manager.admission.LinuxHostProbe.snapshot", _boom)

    body = rtm_client.get("/v1/runtime/status").json()

    assert body["capacity"]["readable"] is False
    assert body["capacity"]["total_mb"] == 0


def test_readonly_endpoints_require_a_signature(rtm_client, rtm_config, fake_docker):
    """Status and logs are operational intelligence; ``/healthz`` is not."""
    _deploy(rtm_config, fake_docker)
    for path in (f"/v1/apps/{APP_ID}/status", f"/v1/apps/{APP_ID}/logs", "/v1/runtime/status"):
        assert rtm_client.get(path, sign=False).status_code == 401, path


@pytest.mark.docker
def test_real_docker_logs_rotation_window():
    """Rotation (10 MB × 3) and stdout/stderr framing against a real daemon.

    CI docker stage + 114: what "最近的运行日志" actually spans is a property of
    the driver, and the product口径 depends on it being true.
    """
    pytest.skip("executed in the CI docker stage / on 114, not in the unit suite")
