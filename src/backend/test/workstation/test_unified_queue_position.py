"""F004 AC-36: the queue position of a conversation's deep-research run.

``GET /conversations/{id}/queue-position`` finds the run that holds the
conversation, its run record (the deep-research version) and that version's
place in the worker queue. Owner only.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.workstation.domain.services import run_send
from test.workstation.test_unified_run_api import CID, OWNER, PREFIX, TENANT, _World, client, world  # noqa: F401


def _patch_queue(monkeypatch, record_id: str | None, index: int) -> list[str]:
    looked_up: list[str] = []

    async def record(conversation_id, run_id):
        return SimpleNamespace(id=record_id) if record_id else None

    async def queue_index(version_id):
        looked_up.append(version_id)
        return index

    monkeypatch.setattr(run_send, "_planned_run_record", record)
    monkeypatch.setattr(run_send, "_queue_index", queue_index)
    return looked_up


async def _hold(world: _World, *, task_mode: bool) -> str:  # noqa: F811
    held = await world.dispatch.submit(
        CID, {"text": "调研一下", "task_mode": task_mode, "user_id": OWNER, "tenant_id": TENANT}
    )
    return held.run_id


async def test_waiting_deep_research_run_reports_its_position(world: _World, client: httpx.AsyncClient, monkeypatch):  # noqa: F811
    run_id = await _hold(world, task_mode=True)
    looked_up = _patch_queue(monkeypatch, "svid-7", 3)

    resp = await client.get(f"{PREFIX}/conversations/{CID}/queue-position")

    assert resp.json()["data"] == {"run_id": run_id, "position": 3}
    assert looked_up == ["svid-7"]


async def test_run_the_worker_took_has_no_position(world: _World, client: httpx.AsyncClient, monkeypatch):  # noqa: F811
    run_id = await _hold(world, task_mode=True)
    _patch_queue(monkeypatch, "svid-7", 0)

    resp = await client.get(f"{PREFIX}/conversations/{CID}/queue-position")

    assert resp.json()["data"] == {"run_id": run_id, "position": None}


async def test_direct_run_and_idle_conversation_have_no_position(world: _World, client: httpx.AsyncClient, monkeypatch):  # noqa: F811
    looked_up = _patch_queue(monkeypatch, "svid-7", 3)

    idle = await client.get(f"{PREFIX}/conversations/{CID}/queue-position")
    assert idle.json()["data"] == {"run_id": None, "position": None}

    await _hold(world, task_mode=False)
    direct = await client.get(f"{PREFIX}/conversations/{CID}/queue-position")
    assert direct.json()["data"]["position"] is None
    # Neither case looks the queue up.
    assert looked_up == []


async def test_run_without_a_record_yet_has_no_position(world: _World, client: httpx.AsyncClient, monkeypatch):  # noqa: F811
    await _hold(world, task_mode=True)
    _patch_queue(monkeypatch, None, 3)

    resp = await client.get(f"{PREFIX}/conversations/{CID}/queue-position")

    assert resp.json()["data"]["position"] is None


async def test_queue_position_is_owner_only(world: _World, client: httpx.AsyncClient, monkeypatch):  # noqa: F811
    await _hold(world, task_mode=True)
    looked_up = _patch_queue(monkeypatch, "svid-7", 3)
    world.user = SimpleNamespace(user_id=OWNER + 1, user_name="other", tenant_id=TENANT)

    other = await client.get(f"{PREFIX}/conversations/{CID}/queue-position")
    missing = await client.get(f"{PREFIX}/conversations/does-not-exist/queue-position")

    assert other.json()["status_code"] == UnAuthorizedError.Code
    assert missing.json()["status_code"] == UnAuthorizedError.Code
    assert "position" not in other.text
    assert looked_up == []
