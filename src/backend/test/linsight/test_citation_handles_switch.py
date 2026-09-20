"""F069 T031: the kill switch and the per-session contract pin (AC-16, AC-18).

``_create_agent`` reads ``citation_handles_enabled`` from the system config for
a NEW session, but a session that already has a handle table keeps whatever
contract is pinned in it (``meta:enabled``), so flipping the switch never
changes the contract of an in-flight or follow-up run.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.citation.domain.services import citation_handle_service as handle_svc
from bisheng.citation.domain.services import linsight_citation_scope as scope_mod
from bisheng.linsight.domain import task_exec as task_exec_mod
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask


class FakeRedis:
    def __init__(self):
        self.store: dict[str, dict[str, str]] = {}

    def _h(self, name):
        return self.store.setdefault(name, {})

    async def ahgetall(self, name):
        return dict(self._h(name))

    async def ahget(self, name, key):
        return self._h(name).get(key)

    async def ahset(self, name, key=None, value=None, mapping=None, items=None, expiration=3600):
        h = self._h(name)
        if mapping:
            h.update(mapping)
        if key is not None:
            h[key] = value

    async def ahsetnx(self, name, key, value):
        h = self._h(name)
        if key in h:
            return False
        h[key] = value
        return True

    async def aexpire_key(self, key, expiration):
        return None


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    redis = FakeRedis()
    monkeypatch.setattr(handle_svc, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(scope_mod, "get_redis_client", AsyncMock(return_value=redis))

    captured: dict = {}

    async def fake_create_linsight_agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(name="agent")

    class _Backend:
        def __init__(self, **kwargs):
            captured["backend_kwargs"] = kwargs

    monkeypatch.setattr(task_exec_mod, "create_linsight_agent", fake_create_linsight_agent)
    monkeypatch.setattr(task_exec_mod, "get_minio_storage", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr("bisheng.linsight.domain.services.workspace_backend.WorkspaceBackend", _Backend)
    monkeypatch.setattr(
        "bisheng.linsight.domain.services.skill_provisioning.materialize_session_skills",
        AsyncMock(return_value=SimpleNamespace(failed=[], copied=[])),
    )
    conf = {"enabled": True}

    async def _aget_linsight_conf():
        return SimpleNamespace(citation_handles_enabled=conf["enabled"])

    # ``settings`` is a pydantic instance (attributes cannot be monkeypatched);
    # swap the module-level object for a stand-in exposing only what
    # _create_agent reads.
    fake_settings = SimpleNamespace(aget_linsight_conf=_aget_linsight_conf)
    monkeypatch.setattr(task_exec_mod, "settings", fake_settings)
    return SimpleNamespace(redis=redis, captured=captured, conf=conf, settings=fake_settings)


def _session():
    return LinsightSessionVersion(id="SV-1", session_id="chat-1", user_id=1, question="q", tenant_id=1)


async def _create(env):
    task = LinsightWorkflowTask()
    task.file_dir = "/tmp/f069"
    task._turn_budget = {}
    task._push_skill_load_failure = AsyncMock()
    await task._create_agent(_session(), tools=[])
    return task


async def test_new_session_takes_the_switch_value(env):
    env.conf["enabled"] = True
    task = await _create(env)
    assert task._citation_scope.enabled is True
    assert env.captured["citation_scope"] is task._citation_scope
    assert env.captured["backend_kwargs"]["citation_scope"] is task._citation_scope

    # a NEW session (no table yet) follows the flipped switch
    env.redis.store.clear()
    env.conf["enabled"] = False
    task = await _create(env)
    assert task._citation_scope.enabled is False


async def test_pinned_session_keeps_its_contract_after_a_flip(env):
    # the session already runs under the verbatim contract (table pinned to 0)
    env.redis.store["linsight:cite_handles:chat-1"] = {
        "next": "1",
        "meta:enabled": "0",
        "h:S1": json.dumps({"key": "knowledgesearch_aaaa1111:3", "type": "rag", "title": "t", "loc": ""}),
    }
    env.conf["enabled"] = True

    task = await _create(env)

    assert task._citation_scope.enabled is False
    assert task._citation_scope.handles == {"S1": "knowledgesearch_aaaa1111:3"}


async def test_pinned_handle_session_survives_switch_off(env):
    env.redis.store["linsight:cite_handles:chat-1"] = {"next": "0", "meta:enabled": "1"}
    env.conf["enabled"] = False

    task = await _create(env)

    assert task._citation_scope.enabled is True


async def test_config_failure_defaults_to_on(env, monkeypatch):
    env.settings.aget_linsight_conf = AsyncMock(side_effect=RuntimeError("db down"))

    task = await _create(env)

    assert task._citation_scope.enabled is True


async def test_new_session_pins_its_contract_even_without_handles(env):
    """A verbatim-contract session allocates no handles, so the pin must not
    wait for the first allocation — otherwise a later switch-on would change
    the contract of its follow-up turn."""
    env.conf["enabled"] = False

    task = await _create(env)

    assert env.redis.store["linsight:cite_handles:chat-1"]["meta:enabled"] == "0"
    assert task._citation_scope.pinned is True

    env.conf["enabled"] = True
    task = await _create(env)
    assert task._citation_scope.enabled is False
