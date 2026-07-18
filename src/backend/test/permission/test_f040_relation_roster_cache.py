"""F040 (E) T1: version-keyed relation-roster cache contract.

Safety-critical: a cache hit MUST equal a fresh build, and a version change MUST
force a rebuild (otherwise a stale roster could grant removed permissions). These
tests lock get_or_build's semantics with a counting build fn.
"""

from __future__ import annotations

import pytest

from bisheng.permission.domain.services import relation_roster_cache as rrc


@pytest.fixture(autouse=True)
def _clear_cache():
    rrc.clear_all()
    yield
    rrc.clear_all()


def _counting_builder(value):
    state = {"calls": 0}

    async def _build():
        state["calls"] += 1
        return value

    return _build, state


async def test_same_version_reuses_cached_build():
    build, state = _counting_builder([{"b": 1}])
    v1 = await rrc.get_or_build(name="bindings", tenant_id=1, version="t0", build=build)
    v2 = await rrc.get_or_build(name="bindings", tenant_id=1, version="t0", build=build)
    assert v1 == [{"b": 1}] and v2 == [{"b": 1}]
    assert state["calls"] == 1  # second call served from cache


async def test_version_change_forces_rebuild():
    build, state = _counting_builder([{"b": 1}])
    await rrc.get_or_build(name="bindings", tenant_id=1, version="t0", build=build)
    await rrc.get_or_build(name="bindings", tenant_id=1, version="t1", build=build)
    assert state["calls"] == 2  # update_time changed → rebuilt (no stale roster)


async def test_none_version_never_caches():
    """Fail-safe: version unavailable → always rebuild, never serve from cache."""
    build, state = _counting_builder([{"b": 1}])
    await rrc.get_or_build(name="bindings", tenant_id=1, version=None, build=build)
    await rrc.get_or_build(name="bindings", tenant_id=1, version=None, build=build)
    assert state["calls"] == 2


async def test_tenant_isolation():
    build, state = _counting_builder([{"b": 1}])
    await rrc.get_or_build(name="bindings", tenant_id=1, version="t0", build=build)
    await rrc.get_or_build(name="bindings", tenant_id=2, version="t0", build=build)
    assert state["calls"] == 2  # same version, different tenant → separate entries


async def test_distinct_buckets_do_not_collide():
    b_build, b_state = _counting_builder("bindings-value")
    m_build, m_state = _counting_builder("models-value")
    b = await rrc.get_or_build(name="bindings", tenant_id=1, version="t0", build=b_build)
    m = await rrc.get_or_build(name="models", tenant_id=1, version="t0", build=m_build)
    assert b == "bindings-value" and m == "models-value"
    assert b_state["calls"] == 1 and m_state["calls"] == 1


async def test_empty_value_is_a_valid_hit():
    """An empty roster ([] / {}) must cache as a hit, not be mistaken for a miss."""
    build, state = _counting_builder([])
    await rrc.get_or_build(name="bindings", tenant_id=1, version="t0", build=build)
    out = await rrc.get_or_build(name="bindings", tenant_id=1, version="t0", build=build)
    assert out == []
    assert state["calls"] == 1


# --------- _get_bindings wiring (version read → cache → build) --------- #


def _version_stub(values):
    """classmethod returning successive versions from ``values`` (last repeats)."""
    state = {"i": 0}

    async def _ver(cls, key):
        v = values[min(state["i"], len(values) - 1)]
        state["i"] += 1
        return v

    return classmethod(_ver)


async def test_get_bindings_reuses_parse_on_same_version(monkeypatch):
    """AC-21/AC-30: same config version → ``_build_bindings`` runs once, the parse is
    reused across consecutive ``_get_bindings`` reads."""
    import bisheng.permission.api.endpoints.resource_permission as rp
    from bisheng.common.models.config import ConfigDao

    monkeypatch.setattr(ConfigDao, "aget_config_version", _version_stub(["v1"]))
    monkeypatch.setattr(rp, "_roster_cache_tenant_id", lambda: 1)
    state = {"calls": 0}

    async def _build():
        state["calls"] += 1
        return [{"resource_type": "knowledge_space", "resource_id": "1"}]

    monkeypatch.setattr(rp, "_build_bindings", _build)

    b1 = await rp._get_bindings()
    b2 = await rp._get_bindings()
    assert b1 == b2 == [{"resource_type": "knowledge_space", "resource_id": "1"}]
    assert state["calls"] == 1


async def test_get_bindings_rebuilds_when_version_changes(monkeypatch):
    """A config edit bumps update_time → version changes → roster rebuilt (no stale)."""
    import bisheng.permission.api.endpoints.resource_permission as rp
    from bisheng.common.models.config import ConfigDao

    monkeypatch.setattr(ConfigDao, "aget_config_version", _version_stub(["v1", "v2"]))
    monkeypatch.setattr(rp, "_roster_cache_tenant_id", lambda: 1)
    state = {"calls": 0}

    async def _build():
        state["calls"] += 1
        return []

    monkeypatch.setattr(rp, "_build_bindings", _build)

    await rp._get_bindings()
    await rp._get_bindings()
    assert state["calls"] == 2  # version v1 → v2 forced a rebuild
