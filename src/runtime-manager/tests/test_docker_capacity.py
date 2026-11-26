"""Docker memory accounting compatibility and fail-closed capacity sampling."""

from types import SimpleNamespace

import pytest

from runtime_manager.config import Config
from runtime_manager.executors.docker import DockerExecutor, working_set_bytes

MIB = 1024**2
GIB = 1024**3


@pytest.mark.parametrize(
    "stats,expected",
    [
        ({"total_inactive_file": 40}, 60),
        ({"inactive_file": 30}, 70),
        ({"cache": 20}, 80),
        ({"total_inactive_file": 0, "inactive_file": 50, "cache": 60}, 100),
        ({"inactive_file": 0, "cache": 60}, 100),
        ({"cache": 0}, 100),
        ({"total_inactive_file": 40, "inactive_file": 50, "cache": 60}, 60),
        ({"inactive_file": 30, "cache": 60}, 70),
        ({"file": 99}, 100),
        ({}, 100),
        (None, 100),
        ([], 100),
        ("malformed", 100),
    ],
    ids=[
        "v1",
        "v2",
        "old-docker",
        "v1-zero",
        "v2-zero",
        "old-zero",
        "v1-precedence",
        "v2-precedence",
        "all-file-not-deducted",
        "missing-cache",
        "null-stats",
        "empty-list-stats",
        "invalid-stats",
    ],
)
def test_working_set_uses_only_the_first_present_cache_accounting_field(stats, expected):
    assert working_set_bytes({"usage": 100, "stats": stats}) == expected


@pytest.mark.parametrize("key", ["total_inactive_file", "inactive_file", "cache"])
@pytest.mark.parametrize("cache", [-1, 100, 101, None, "10", 10.5, True, False])
def test_invalid_cache_keeps_total_usage_instead_of_using_another_field(key, cache):
    stats = {"cache": 50, key: cache}
    assert working_set_bytes({"usage": 100, "stats": stats}) == 100


@pytest.mark.parametrize("usage", [None, -1, "100", 100.0, True, False])
def test_invalid_usage_is_a_sampling_failure(usage):
    with pytest.raises(ValueError, match="Invalid container memory usage"):
        working_set_bytes({"usage": usage, "stats": {"inactive_file": 10}})


@pytest.mark.parametrize("sample", [None, [], "invalid", 1])
def test_malformed_memory_stats_is_a_sampling_failure(sample):
    with pytest.raises(ValueError, match="Invalid container memory usage"):
        working_set_bytes(sample)


def test_missing_usage_is_not_a_zero_sample():
    with pytest.raises(ValueError, match="Invalid container memory usage"):
        working_set_bytes({"stats": {"inactive_file": 10}})
    assert working_set_bytes({"usage": 0, "stats": {"inactive_file": 0}}) == 0


def executor(tmp_path, *, memory_limit=0, sample=None):
    calls, heartbeats = [], []
    config = Config(data_root=tmp_path, node_id="node-a")

    def stats(container):
        calls.append(container)
        return {"memory_stats": sample}

    engine = SimpleNamespace(
        info=lambda: {
            "ID": "docker-host",
            "OSType": "linux",
            "Architecture": "x86_64",
            "MemTotal": 16 * GIB,
            "NCPU": 8,
        },
        list_containers=lambda **kwargs: [{"Id": "external", "Labels": {}}],
        inspect_container=lambda ref: {"HostConfig": {"Memory": memory_limit, "NanoCpus": 10**9}},
        container_stats=stats,
    )
    result = DockerExecutor(config, SimpleNamespace(heartbeat=heartbeats.append), engine)
    return result, engine, calls, heartbeats


@pytest.mark.parametrize("key", ["total_inactive_file", "inactive_file", "cache"])
def test_heartbeat_preserves_ratio_reserve_cpu_and_rounded_committed_memory(tmp_path, key):
    runtime, _, calls, heartbeats = executor(tmp_path, sample={"usage": 4 * GIB + 1, "stats": {key: 3 * GIB}})
    runtime.heartbeat()
    # ceil(1 GiB + 1 byte) = 1025 MiB, following the existing formula.
    assert heartbeats == [
        {
            "engine_id": "docker-host",
            "platform": "linux/amd64",
            "memory_budget_mb": 10034,
            "cpu_budget_millicores": 5400,
        }
    ]
    assert calls == ["external"]
    assert runtime.config.overcommit_ratio == 0.8 and runtime.config.reserve_mb == 2048


def test_configured_memory_limit_is_committed_without_sampling_working_set(tmp_path):
    runtime, _, calls, heartbeats = executor(tmp_path, memory_limit=2 * GIB, sample={"usage": 1})
    runtime.heartbeat()
    assert heartbeats[0]["memory_budget_mb"] == 9011
    assert calls == []


@pytest.mark.parametrize("sample", [{}, {"stats": {"cache": 1}}, {"usage": -1}, {"usage": "100"}, {"usage": False}])
def test_bad_unlimited_container_sample_never_publishes_a_fabricated_budget(tmp_path, sample):
    runtime, _, calls, heartbeats = executor(tmp_path, sample=sample)
    with pytest.raises(ValueError, match="Invalid container memory usage"):
        runtime.heartbeat()
    assert calls == ["external"] and heartbeats == []


def test_runtime_owned_containers_are_reserved_by_the_platform_not_double_counted(tmp_path):
    runtime, engine, calls, heartbeats = executor(tmp_path, sample={"usage": GIB, "stats": {"inactive_file": 0}})
    engine.list_containers = lambda **kwargs: [
        {"Id": "external", "Labels": {}},
        {"Id": "owned", "Labels": {"bisheng.managed": "v2", "bisheng.runtime.node": "node-a"}},
        {"Id": "legacy", "Labels": {}},
    ]
    runtime._legacy_owned = {"legacy"}
    runtime.heartbeat()
    assert calls == ["external"]
    assert heartbeats[0]["memory_budget_mb"] == 10035
