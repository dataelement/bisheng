"""Replica discover() contract (F068 T015). DNS + health are mocked; no real cluster."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from fake_runner import FakeRunnerClient

from bisheng.common.errcode.sandbox import SandboxUnreachableError
from bisheng.core.config.settings import SandboxConf
from bisheng_langchain.gpts.tools.code_interpreter.container_executor import ContainerExecutor
from bisheng_langchain.gpts.tools.code_interpreter.discover import ReplicaDiscoverer, discover

_SHUFFLE = "bisheng_langchain.gpts.tools.code_interpreter.container_executor.random.shuffle"
_FAKE_IP = "10.9.8.7"


def _gai(live: set[str]):
    probed: list[str] = []

    def impl(host, port=None, *args, **kwargs):
        probed.append(host)
        if host in live:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_FAKE_IP, port or 0))]
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    impl.probed = probed  # type: ignore[attr-defined]
    return impl


def _always_up(_host: str, _port: int) -> bool:
    return True


def test_compose_pattern_caches_hostname_urls_not_ips():
    gai = _gai({"code-runner-1", "code-runner-2"})
    disc = ReplicaDiscoverer(
        discover_host_pattern="code-runner-{n}",
        discover_index_start=1,
        getaddrinfo=gai,
        health_probe=_always_up,
        clock=lambda: 0.0,
    )
    urls = disc.urls()
    assert urls == ["http://code-runner-1:8080", "http://code-runner-2:8080"]
    assert all(_FAKE_IP not in url for url in urls)
    assert gai.probed == ["code-runner-1", "code-runner-2", "code-runner-3"]


def test_k8s_pattern_scans_from_zero_until_nxdomain():
    gai = _gai({"code-runner-0.code-runner", "code-runner-1.code-runner"})
    urls = discover(
        SandboxConf(
            discover_host_pattern="code-runner-{n}.code-runner",
            discover_index_start=0,
            endpoints=[],
        ),
        getaddrinfo=gai,
        health_probe=_always_up,
        clock=lambda: 0.0,
    )
    assert urls == [
        "http://code-runner-0.code-runner:8080",
        "http://code-runner-1.code-runner:8080",
    ]
    assert gai.probed[0] == "code-runner-0.code-runner"
    assert "code-runner-2.code-runner" in gai.probed
    assert "code-runner-3.code-runner" not in gai.probed


def test_ttl_skips_reprobe_until_expiry():
    gai = _gai({"code-runner-1", "code-runner-2"})
    now = [0.0]
    disc = ReplicaDiscoverer(
        discover_ttl_s=15,
        getaddrinfo=gai,
        health_probe=_always_up,
        clock=lambda: now[0],
    )
    assert disc.urls() == ["http://code-runner-1:8080", "http://code-runner-2:8080"]
    first = list(gai.probed)
    now[0] = 14.9
    assert disc.urls() == ["http://code-runner-1:8080", "http://code-runner-2:8080"]
    assert gai.probed == first
    now[0] = 15.1
    disc.urls()
    assert gai.probed == [*first, "code-runner-1", "code-runner-2", "code-runner-3"]


def test_consecutive_miss_stops_without_skipping_index():
    gai = _gai({"code-runner-1", "code-runner-3"})
    disc = ReplicaDiscoverer(getaddrinfo=gai, health_probe=_always_up, clock=lambda: 0.0)
    assert disc.urls() == ["http://code-runner-1:8080"]
    assert "code-runner-3" not in gai.probed


def test_health_miss_stops_without_skipping_index():
    gai = _gai({"code-runner-1", "code-runner-2", "code-runner-3"})
    health_hosts: list[str] = []

    def health(host: str, _port: int) -> bool:
        health_hosts.append(host)
        return host == "code-runner-1"

    disc = ReplicaDiscoverer(getaddrinfo=gai, health_probe=health, clock=lambda: 0.0)
    assert disc.urls() == ["http://code-runner-1:8080"]
    assert health_hosts == ["code-runner-1", "code-runner-2"]
    assert "code-runner-3" not in gai.probed


def test_endpoints_non_empty_skip_dns_entirely():
    gai = _gai({"code-runner-1"})

    def boom(*_a, **_k):
        raise AssertionError("DNS must not run when endpoints are set")

    urls = discover(
        endpoints=["http://runner-a:8080", "http://runner-b:8080/"],
        getaddrinfo=boom,
        health_probe=lambda *_: (_ for _ in ()).throw(AssertionError("health skipped")),
    )
    assert urls == ["http://runner-a:8080", "http://runner-b:8080"]
    assert gai.probed == []


def test_sticky_bound_instance_does_not_rediscover(tmp_path, monkeypatch):
    monkeypatch.setattr(_SHUFFLE, lambda seq: None)
    gai = _gai({"code-runner-1", "code-runner-2"})
    disc = ReplicaDiscoverer(getaddrinfo=gai, health_probe=_always_up, clock=lambda: 0.0)
    calls = {"n": 0}
    orig = disc.urls

    def counted():
        calls["n"] += 1
        return orig()

    disc.urls = counted  # type: ignore[method-assign]
    fake = FakeRunnerClient()
    fake.add_replica("http://code-runner-1:8080")
    fake.add_replica("http://code-runner-2:8080")
    exe = ContainerExecutor(
        minio={},
        endpoints=[],
        token="test-token",
        client=fake,
        keep_session=True,
        discoverer=disc,
    )
    assert exe.execute_code("print(1)", work_dir=str(tmp_path))[0] == 0
    assert calls["n"] == 1
    dns_after_first = list(gai.probed)
    assert exe.execute_code("print(2)", work_dir=str(tmp_path))[0] == 0
    assert calls["n"] == 1
    assert gai.probed == dns_after_first


def test_empty_discovery_is_unreachable(tmp_path):
    gai = _gai(set())
    disc = ReplicaDiscoverer(getaddrinfo=gai, health_probe=_always_up, clock=lambda: 0.0)
    fake = FakeRunnerClient()
    exe = ContainerExecutor(
        minio={},
        endpoints=[],
        token="test-token",
        client=fake,
        discoverer=disc,
    )
    with pytest.raises(SandboxUnreachableError) as err:
        exe.execute_code("print(1)", work_dir=str(tmp_path))
    assert err.value.Code == 28001


def test_discover_has_no_deploy_mode_branch():
    source = (
        Path(__file__).resolve().parents[2]
        / "bisheng_langchain"
        / "gpts"
        / "tools"
        / "code_interpreter"
        / "discover.py"
    ).read_text(encoding="utf-8")
    assert "deploy_mode" not in source
    assert "orchestrator" not in source
    assert "kubernetes" not in source
    assert "import docker" not in source
