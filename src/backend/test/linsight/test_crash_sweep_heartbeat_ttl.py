"""The worker-startup crash sweep must not trust a heartbeat key that outlives its node.

A node's heartbeat key expires one TTL (15 s) after its last refresh. On a pod
eviction the replacement started 4 s after the old pod was killed, so the sweep
found the dead node's key still present, logged "running on active node" and
skipped its task. The sweep runs once per worker start, so the task stayed
IN_PROGRESS and the page spun until someone stopped it by hand.

``asyncio_mode = auto`` — async tests need no decorator.
"""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.linsight.domain import utils


class StubNodeManager:
    """``is_node_alive`` answers from a per-owner list, one answer per call."""

    answers: dict[str, list[bool]] = {}
    ttl = 15

    def __init__(self, redis_client, node_id):
        pass

    async def is_node_alive(self, owner):
        return self.answers[owner].pop(0)


@pytest.fixture
def sweep(monkeypatch):
    fake_worker = ModuleType("bisheng.linsight.worker")
    fake_worker.NodeManager = StubNodeManager
    monkeypatch.setitem(sys.modules, "bisheng.linsight.worker", fake_worker)
    monkeypatch.setattr(type(utils.settings), "aget_all_config", AsyncMock(return_value={}))
    monkeypatch.setattr(utils.LinsightExecuteTaskDao, "batch_update_status_by_session_version_id", AsyncMock())
    monkeypatch.setattr(utils, "announce_stranded_session_failure", AsyncMock())
    failed = AsyncMock()
    monkeypatch.setattr(utils.LinsightSessionVersionDao, "batch_update_session_versions_status", failed)
    slept: list[float] = []

    async def _sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(utils.asyncio, "sleep", _sleep)

    def _run(owners: dict[str, str | None], answers: dict[str, list[bool]]):
        StubNodeManager.answers = {owner: list(seq) for owner, seq in answers.items()}
        sessions = [SimpleNamespace(id=svid, user_id=1) for svid in owners]
        monkeypatch.setattr(
            utils.LinsightSessionVersionDao, "get_session_versions_by_status", AsyncMock(return_value=sessions)
        )
        redis = SimpleNamespace(aget=AsyncMock(side_effect=lambda key: owners[key.rsplit(":", 1)[1]]))
        monkeypatch.setattr(utils, "get_redis_client", AsyncMock(return_value=redis))
        return failed, slept

    return _run


def _failed_ids(failed) -> list[str]:
    return failed.await_args.kwargs["session_version_ids"] if failed.await_args else []


async def test_owner_whose_key_lingers_after_death_is_failed(sweep):
    failed, slept = sweep({"sv-1": "old-pod"}, {"old-pod": [True, False]})

    await utils.check_and_terminate_incomplete_tasks("new-pod")

    assert _failed_ids(failed) == ["sv-1"]
    assert slept == [StubNodeManager.ttl + 1]


async def test_owner_still_heartbeating_after_one_ttl_is_skipped(sweep):
    failed, slept = sweep({"sv-1": "live-pod"}, {"live-pod": [True, True]})

    await utils.check_and_terminate_incomplete_tasks("new-pod")

    assert _failed_ids(failed) == []
    assert slept == [StubNodeManager.ttl + 1]


async def test_no_wait_when_every_owner_is_already_gone(sweep):
    failed, slept = sweep({"sv-1": None, "sv-2": "dead-pod"}, {"dead-pod": [False]})

    await utils.check_and_terminate_incomplete_tasks("new-pod")

    assert sorted(_failed_ids(failed)) == ["sv-1", "sv-2"]
    assert slept == []


async def test_mixed_owners_wait_once(sweep):
    failed, slept = sweep(
        {"sv-1": "old-pod", "sv-2": "live-pod", "sv-3": None},
        {"old-pod": [True, False], "live-pod": [True, True]},
    )

    await utils.check_and_terminate_incomplete_tasks("new-pod")

    assert sorted(_failed_ids(failed)) == ["sv-1", "sv-3"]
    assert slept == [StubNodeManager.ttl + 1]
