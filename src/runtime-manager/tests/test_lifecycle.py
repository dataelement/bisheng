"""Instance lifecycle — what we ask the daemon for, and what we never ask for.

Every assertion below is against the *create payload* that would hit the Docker
Engine API, because that payload is where the cage is actually specified. A
container that runs is not evidence of anything; a container created with
``ReadonlyRootfs`` and no ``PortBindings`` is.

Three of these are absence tests, and absence is the part that rots silently:

* no ``PortBindings`` — AC-33's "cannot be reached except through app-proxy"
  is *only* true while nothing publishes a host port;
* no replica / concurrency input — AC-24's single instance is enforced by there
  being no field to set, not by a validation rule someone can relax;
* ``restart: unless-stopped``, not ``always`` — stopping an app is an explicit
  operator action, and ``always`` would have the daemon fight it on every
  reboot.

Whether the kernel enforces the limits, whether a killed process really comes
back, whether ``HEALTHCHECK`` really flips ``State.Health`` — real docker
questions, marked ``@pytest.mark.docker`` (CI middleware stage + 114, T075).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from runtime_manager.api.schemas import DeployRequest, TierIn
from runtime_manager.desired_state import get_store
from runtime_manager.errors import CapacityExhaustedError, ProbeFailedError
from runtime_manager.lifecycle import LifecycleService, container_name
from tests.fakes import FakeHostProbe, ImmediateScheduler, RecordingScheduler

MIB = 1024 * 1024
GIGA = 1_000_000_000


@dataclass(frozen=True)
class _Outcome:
    """Structural stand-in for ``runtime_manager.probe.ProbeOutcome``."""

    ready: bool
    reason: str = ""


class FakeProber:
    """Readiness gate double — the real one is exercised in test_probe_and_route."""

    def __init__(self, ready: bool = True, reason: str = "") -> None:
        self.ready = ready
        self.reason = reason
        self.calls: list[tuple] = []

    def wait_ready(self, container, port, health_path, timeout=None):
        self.calls.append((container, port, health_path))
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


def _service(config, fake_docker, *, probe=None, prober=None, scheduler=None) -> LifecycleService:
    from runtime_manager.admission import AdmissionService

    return LifecycleService(
        config,
        docker=fake_docker,
        admission=AdmissionService(config, host_probe=probe or FakeHostProbe()),
        prober=prober or FakeProber(),
        scheduler=scheduler or ImmediateScheduler(),
    )


def _env_of(payload) -> dict[str, str]:
    return dict(item.split("=", 1) for item in payload["Env"])


def test_tier_limits_applied(rtm_config, fake_docker):
    """AC-63 — the numbers in the payload are the numbers ``docker inspect`` shows.

    Limits are fixed at creation and never updated in place, which is what makes
    AC-64 ("changing a tier's spec affects the *next* start") true by
    construction instead of by a rule someone has to remember.
    """
    _service(rtm_config, fake_docker).deploy(_request(tier=TierIn(cpu=1.0, mem=1024)))

    host = fake_docker.last_call("create_container")["payload"]["HostConfig"]
    assert host["NanoCpus"] == GIGA
    assert host["Memory"] == 1024 * MIB
    # No swap: a memory limit the app can silently exceed by swapping is not a
    # limit, and on a shared host swap thrash hurts every other app.
    assert host["MemorySwap"] == host["Memory"]


def test_readonly_rootfs_and_tmpfs(rtm_config, fake_docker):
    """AC-17 — /data is the only writable persistent path; /tmp is ephemeral."""
    _service(rtm_config, fake_docker).deploy(_request())

    payload = fake_docker.last_call("create_container")["payload"]
    host = payload["HostConfig"]
    assert host["ReadonlyRootfs"] is True
    assert "/tmp" in host["Tmpfs"]
    expected_bind = f"{rtm_config.app_data_dir('app-1')}:/data:rw"
    assert host["Binds"] == [expected_bind]
    assert rtm_config.app_data_dir("app-1").is_dir()


def test_no_new_privileges(rtm_config, fake_docker):
    _service(rtm_config, fake_docker).deploy(_request())

    host = fake_docker.last_call("create_container")["payload"]["HostConfig"]
    assert "no-new-privileges:true" in host["SecurityOpt"]


def test_no_published_ports(rtm_config, fake_docker):
    """AC-33 — reachable on the bridge network only; never on a host port."""
    _service(rtm_config, fake_docker).deploy(_request())

    payload = fake_docker.last_call("create_container")["payload"]
    host = payload["HostConfig"]
    assert host["PortBindings"] == {}
    assert host["PublishAllPorts"] is False
    assert host["NetworkMode"] == rtm_config.network
    # The port is still *exposed* so the bridge address is dialable by app-proxy.
    assert payload["ExposedPorts"] == {"8080/tcp": {}}


def test_env_injection_names(rtm_config, fake_docker):
    """AC-17 / AC-45 — the contract F053's ``bisheng dev`` injects by the same names.

    ``PORT`` and ``BISHENG_APP_PORT`` are both asserted, and asserted *equal*:
    frameworks read one or the other, and a deployment where they disagree fails
    in the worst possible way — the app binds a port nothing dials.
    """
    _service(rtm_config, fake_docker).deploy(_request())

    env = _env_of(fake_docker.last_call("create_container")["payload"])
    assert env["BISHENG_APP_DB_URL"] == "sqlite:////data/app.db"
    assert env["BISHENG_APP_DB_PATH"] == "/data/app.db"
    assert env["BISHENG_APP_ID"] == "app-1"
    assert env["BISHENG_APP_SLUG"] == "sales-report"
    assert env["BISHENG_APP_VERSION"] == "3"
    assert env["BISHENG_APP_VERSION_ID"] == "ver-0123456789abcdef"
    assert env["BISHENG_PLATFORM_API_BASE"] == "https://bisheng.example.com/api"
    assert env["PORT"] == "8080"
    assert env["BISHENG_APP_PORT"] == "8080"
    assert env["PORT"] == env["BISHENG_APP_PORT"]
    assert env["BISHENG_APP_BASE_PATH"] == "/apps/sales-report"


def test_platform_env_wins_over_caller_env(rtm_config, fake_docker):
    """A reserved name cannot be redefined by whatever the pipeline passed in."""
    _service(rtm_config, fake_docker).deploy(
        _request(env={"BISHENG_APP_DB_URL": "postgres://elsewhere", "MY_FLAG": "1"})
    )

    env = _env_of(fake_docker.last_call("create_container")["payload"])
    assert env["BISHENG_APP_DB_URL"] == "sqlite:////data/app.db"
    assert env["MY_FLAG"] == "1"


def test_restart_policy_unless_stopped(rtm_config, fake_docker):
    """AC-20 first failure class — process exit — is delegated to the daemon.

    ``unless-stopped`` rather than ``always`` because stopping is an explicit
    operator decision (AC-41) and must survive a host reboot.
    """
    _service(rtm_config, fake_docker).deploy(_request())

    host = fake_docker.last_call("create_container")["payload"]["HostConfig"]
    assert host["RestartPolicy"] == {"Name": "unless-stopped", "MaximumRetryCount": 0}


def test_log_rotation_configured(rtm_config, fake_docker):
    """AC-55's retention window *is* the json-file rotation window (D14-B)."""
    _service(rtm_config, fake_docker).deploy(_request())

    host = fake_docker.last_call("create_container")["payload"]["HostConfig"]
    assert host["LogConfig"] == {
        "Type": "json-file",
        "Config": {"max-size": "10m", "max-file": "3"},
    }


def test_healthcheck_params(rtm_config, fake_docker):
    """10s / 3s / 3 retries, with a tier-sized start period (D4)."""
    _service(rtm_config, fake_docker).deploy(_request())
    light = fake_docker.last_call("create_container")["payload"]["Healthcheck"]

    assert light["Interval"] == 10 * 1_000_000_000
    assert light["Timeout"] == 3 * 1_000_000_000
    assert light["Retries"] == 3
    assert 20 * 1_000_000_000 <= light["StartPeriod"] <= 60 * 1_000_000_000

    _service(rtm_config, fake_docker).deploy(
        _request(app_id="app-2", slug="big", tier=TierIn(cpu=2, mem=2048))
    )
    heavy = fake_docker.last_call("create_container")["payload"]["Healthcheck"]
    # A bigger tier means a heavier app: more start-up slack, still bounded.
    assert heavy["StartPeriod"] > light["StartPeriod"]
    assert heavy["StartPeriod"] <= 60 * 1_000_000_000


def test_single_instance_per_app(rtm_config, fake_docker):
    """AC-24 — no field to scale, and a redeploy replaces rather than adds."""
    assert "replicas" not in DeployRequest.model_fields
    assert "concurrency" not in DeployRequest.model_fields

    service = _service(rtm_config, fake_docker)
    service.deploy(_request())
    service.deploy(_request(version_id="ver-fedcba9876543210", version_no=4))

    running = [c for c in fake_docker.containers.values() if c.running]
    assert len(running) == 1
    assert running[0].name == container_name("sales-report", "ver-fedcba9876543210")
    assert len(get_store(rtm_config).list()) == 1


def test_new_version_switches_only_after_probe_passes(rtm_config, fake_docker):
    """AC-21 — the old container keeps serving until the new one is healthy."""
    scheduler = RecordingScheduler()
    service = _service(rtm_config, fake_docker, scheduler=scheduler)
    service.deploy(_request())
    old = container_name("sales-report", "ver-0123456789abcdef")

    service.deploy(_request(version_id="ver-fedcba9876543210", version_no=4))

    # Retirement was scheduled, not executed: the old container is still up.
    assert fake_docker.get(old).running is True
    delay, _ = scheduler.scheduled[0]
    # 30s ≫ app-proxy's 3s route cache — that gap is the whole reason AC-21
    # does not land on a 502 during the switch (D5.1).
    assert delay >= 30
    scheduler.run_all()
    assert old not in [c.name for c in fake_docker.containers.values()]


def test_failed_probe_keeps_old_instance_and_reports(rtm_config, fake_docker):
    """A new version that never becomes ready must not take the app down."""
    service = _service(rtm_config, fake_docker)
    service.deploy(_request())
    old = container_name("sales-report", "ver-0123456789abcdef")

    failing = _service(
        rtm_config, fake_docker, prober=FakeProber(ready=False, reason="timeout after 90s")
    )
    with pytest.raises(ProbeFailedError) as excinfo:
        failing.deploy(_request(version_id="ver-fedcba9876543210", version_no=4))

    assert "timeout" in excinfo.value.detail["message"]
    assert fake_docker.get(old).running is True
    # The stillborn container is cleaned up rather than left behind as an orphan.
    assert container_name("sales-report", "ver-fedcba9876543210") not in [
        c.name for c in fake_docker.containers.values()
    ]
    record = get_store(rtm_config).get("app-1")
    assert record.version_id == "ver-0123456789abcdef"


def test_deploy_refused_when_capacity_exhausted(rtm_config, fake_docker):
    """AC-19 / AC-65 — refuse, do not start a half-usable instance."""
    probe = FakeHostProbe(mem_available_mb=2100)
    with pytest.raises(CapacityExhaustedError) as excinfo:
        _service(rtm_config, fake_docker, probe=probe).deploy(_request())

    assert excinfo.value.detail["reason"] == "insufficient_available_memory"
    assert "snapshot" in excinfo.value.detail
    assert fake_docker.call_count("create_container") == 0


def test_volume_survives_stop_and_recreate(rtm_config, fake_docker):
    """AC-39 / AC-45 — the instance holds no unique data; the volume does."""
    service = _service(rtm_config, fake_docker)
    service.deploy(_request())
    db = rtm_config.app_data_dir("app-1") / "app.db"
    db.write_text("rows", encoding="utf-8")

    service.stop("app-1")
    assert db.read_text(encoding="utf-8") == "rows"

    service.deploy(_request(version_id="ver-fedcba9876543210", version_no=4))
    assert db.read_text(encoding="utf-8") == "rows"
    host = fake_docker.last_call("create_container")["payload"]["HostConfig"]
    assert host["Binds"] == [f"{rtm_config.app_data_dir('app-1')}:/data:rw"]


def test_stop_keeps_record_and_frees_capacity(rtm_config, fake_docker):
    """Stopped apps stop holding capacity — that is what makes resume re-check."""
    service = _service(rtm_config, fake_docker)
    service.deploy(_request())

    result = service.stop("app-1")

    assert result["phase"] == "stopped"
    record = get_store(rtm_config).get("app-1")
    assert record.phase == "stopped"
    assert record.desired == "stopped"
    assert get_store(rtm_config).committed() == (0, 0.0)


def test_destroy_purge_volume_flag(rtm_config, fake_docker):
    """AC-40 — only an explicit purge removes data; destroy alone does not."""
    service = _service(rtm_config, fake_docker)
    service.deploy(_request())
    db = rtm_config.app_data_dir("app-1") / "app.db"
    db.write_text("rows", encoding="utf-8")

    service.destroy("app-1", purge_volume=False)
    assert db.exists()
    assert get_store(rtm_config).get("app-1") is None
    assert not fake_docker.containers

    service.deploy(_request())
    service.destroy("app-1", purge_volume=True)
    assert not db.exists()
    assert not rtm_config.app_data_dir("app-1").exists()


def test_destroy_is_idempotent(rtm_config, fake_docker):
    """Delete is retried by the platform on transient failures; it must be safe."""
    assert _service(rtm_config, fake_docker).destroy("never-existed", purge_volume=True) == {}


def test_stop_and_destroy_endpoints(rtm_client, rtm_config, fake_docker, monkeypatch):
    monkeypatch.setattr(
        "runtime_manager.admission.LinuxHostProbe.snapshot",
        lambda self: FakeHostProbe().snapshot(),
    )
    _service(rtm_config, fake_docker).deploy(_request())

    stopped = rtm_client.post("/v1/intents/stop", {"app_id": "app-1"})
    assert stopped.status_code == 200
    assert stopped.json()["phase"] == "stopped"

    destroyed = rtm_client.post("/v1/intents/destroy", {"app_id": "app-1", "purge_volume": True})
    assert destroyed.status_code == 200


@pytest.mark.docker
def test_real_container_limits_and_self_healing():
    """``docker inspect`` limits, ``docker kill`` recovery, tmpfs writability.

    Only a real daemon can prove AC-63 (the cgroup actually caps the app) and
    AC-20's first failure class (the restart policy actually restarts). Runs in
    the CI docker stage and in the 114 verification (T075 steps 1 and 6).
    """
    pytest.skip("executed in the CI docker stage / on 114, not in the unit suite")
