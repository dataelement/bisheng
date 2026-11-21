"""E2E tests for F004 unified agent runtime (features/v3.1.0-beta2/004-unified-agent-runtime).

Prerequisites:
- A deployed backend with every middleware and at least one workbench model.
- ``E2E_API_BASE`` points at it (``http://<host>/api/v1``).
- ``E2E_ADMIN_TOKEN`` or ``E2E_ADMIN_PASSWORD`` for the admin account.
- ``E2E_F004_MODEL``: id of a workbench model the admin may use (default "9").
- ``E2E_F004_TENANT``: the admin's management tenant (default "1"); a global
  super admin gets 19703 on tenant-specific requests without it.

The owner of the conversations is the admin account; the paired "denied" tests
use a normal user created with the ``e2e-f004rt-`` prefix. Conversations are
deleted at teardown.

Covers (API behaviour only; the UI items are in e2e-checklist.md):
- AC-02: a direct message starts a run and is answered.
- AC-13 / AC-19: a message sent during a run is accepted into the run.
- AC-28: a non-owner cannot read events, stop, or resolve a file of a conversation.
- AC-29: stop ends the run within 5 seconds; unread messages come back.
- AC-30: a message after a stop starts a new run in the same conversation.
- AC-31: a reader that reconnects with Last-Event-ID receives only later events.
- AC-35: deep research gives its first event within 3 seconds when a slot is free.
- Design decision 13: the config response carries no ``unified_runtime_enabled``.
- Design §4.3: a request without ``X-BS-Run-Protocol`` is answered with SSE frames.
- AC-39 / design decision 14 (only with ``E2E_F004_OPEN_API_KEY``): Open API
  daily chat keeps its SSE contract, a second message on a busy conversation
  gets its own answer, and an unknown conversation is HTTP 404. The key is an
  Open API key with scope ``chat:invoke`` that may act on behalf of the admin
  (``X-On-Behalf-Of``, user id from ``E2E_F004_ON_BEHALF_OF``, default "1").
  A personal access token from "AI 助手接入" does not work: its scope is fixed
  to ``knowledge:read``.
"""

import asyncio
import json
import os
import time
from datetime import UTC, datetime

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, create_test_user, get_admin_token, get_user_token

PREFIX = "e2e-f004rt-"
OTHER_USER = f"{PREFIX}other"
OTHER_PASSWORD = "E2e_f004rt_Pass#1"
MODEL = os.environ.get("E2E_F004_MODEL", "9")
TENANT = os.environ.get("E2E_F004_TENANT", "1")
UNAUTHORIZED = 403
TERMINAL = {"run_finished", "run_failed", "run_stopped"}
LONG_QUESTION = "详细介绍量子计算的发展历史，写 3000 字，不要联网搜索"

pytestmark = pytest.mark.e2e


def _owner_headers(token: str, protocol: bool = False) -> dict:
    headers = {**auth_headers(token), "X-Management-Tenant": TENANT}
    if protocol:
        headers["X-BS-Run-Protocol"] = "2"
    return headers


def _body(text: str, conversation_id: str | None = None, task_mode: bool = False) -> dict:
    body = {"clientTimestamp": datetime.now(UTC).isoformat(), "model": MODEL, "text": text}
    if conversation_id:
        body["conversationId"] = conversation_id
    if task_mode:
        body["task_mode"] = True
    return body


async def _send(client, token, text, conversation_id=None, task_mode=False) -> dict:
    resp = await client.post(
        f"{API_BASE}/workstation/chat/completions",
        json=_body(text, conversation_id, task_mode),
        headers=_owner_headers(token, protocol=True),
    )
    data = assert_resp_200(resp)
    assert set(data) >= {"run_id", "disposition", "message_id", "conversation_id"}
    return data


async def _events(client, token, conversation_id, last_event_id=None, until=None, timeout=120.0) -> list[dict]:
    """Read the conversation's event stream until it ends, or until ``until(events)`` is true."""
    headers = _owner_headers(token)
    if last_event_id:
        headers["Last-Event-ID"] = last_event_id
    events: list[dict] = []
    deadline = time.monotonic() + timeout
    async with client.stream(
        "GET", f"{API_BASE}/workstation/conversations/{conversation_id}/events", headers=headers, timeout=timeout
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        event_id = None
        async for line in resp.aiter_lines():
            assert time.monotonic() < deadline, f"event stream did not end; got {[e['type'] for e in events]}"
            if line.startswith("id:"):
                event_id = line[3:].strip()
            elif line.startswith("data:"):
                event = json.loads(line[5:])
                if event.get("type") == "heartbeat":
                    continue
                event.setdefault("id", event_id)
                events.append(event)
                if until is not None and until(events):
                    break
    return events


async def _stop(client, token, conversation_id) -> dict:
    resp = await client.post(
        f"{API_BASE}/workstation/conversations/{conversation_id}/stop", headers=_owner_headers(token)
    )
    return assert_resp_200(resp)


class TestE2EF004UnifiedAgentRuntime:
    """E2E: F004 unified agent runtime."""

    conversations: list[str] = []

    @pytest.fixture(autouse=True, scope="class")
    async def setup_and_teardown(self):
        cls = type(self)
        cls.conversations = []
        yield
        async with httpx.AsyncClient(timeout=30.0) as client:
            token = await get_admin_token(client)
            for conversation_id in cls.conversations:
                # A run still holding the conversation is stopped first; then the row goes.
                await _stop(client, token, conversation_id)
                resp = await client.delete(f"{API_BASE}/chat/{conversation_id}", headers=_owner_headers(token))
                assert resp.status_code == 200, f"cleanup of {conversation_id} failed: {resp.text[:200]}"

    @pytest.fixture
    async def client(self):
        async with httpx.AsyncClient(timeout=180.0) as client:
            yield client

    @pytest.fixture
    async def owner(self, client):
        return await get_admin_token(client)

    @pytest.fixture
    async def other(self, client, owner):
        """Token of a normal user who owns none of the conversations."""
        try:
            return await get_user_token(client, OTHER_USER, OTHER_PASSWORD)
        except AssertionError:
            # First run on this environment: the user does not exist yet.
            await create_test_user(client, owner, username=OTHER_USER, role_id=2, password=OTHER_PASSWORD)
            return await get_user_token(client, OTHER_USER, OTHER_PASSWORD)

    async def _new_conversation(self, client, owner, text="只回复两个字：收到") -> tuple[dict, list[dict]]:
        sent = await _send(client, owner, text)
        type(self).conversations.append(sent["conversation_id"])
        events = await _events(client, owner, sent["conversation_id"])
        return sent, events

    # ──────── Contract ────────

    async def test_decision13_config_has_no_runtime_switch(self, client, owner):
        """Design decision 13: the config response carries no unified_runtime_enabled key."""
        resp = await client.get(f"{API_BASE}/workstation/config", headers=_owner_headers(owner))
        data = assert_resp_200(resp)
        assert "unified_runtime_enabled" not in data

    async def test_ac02_direct_message_starts_a_run_and_is_answered(self, client, owner):
        """AC-02: a direct message starts a run; its events end with run_finished and the answer is stored."""
        sent, events = await self._new_conversation(client, owner)
        assert sent["disposition"] == "started"
        types = [event["type"] for event in events]
        assert types[0] == "run_started" and types[-1] == "run_finished"
        assert "text" in types
        assert all(event.get("run_id") in (None, sent["run_id"]) for event in events)

        resp = await client.get(
            f"{API_BASE}/workstation/messages/{sent['conversation_id']}", headers=_owner_headers(owner)
        )
        rows = assert_resp_200(resp)
        assert len(rows) == 2, "one question row and one answer row"

    async def test_ac31_reconnect_with_last_event_id_gets_only_later_events(self, client, owner):
        """AC-31: a reader that reconnects with Last-Event-ID receives the events after that one."""
        sent, events = await self._new_conversation(client, owner)
        first = events[0]
        later = await _events(client, owner, sent["conversation_id"], last_event_id=first["id"], timeout=30.0)
        assert later, "an ended run is kept for replay"
        assert first["id"] not in [event["id"] for event in later]
        assert [event["type"] for event in later] == [event["type"] for event in events[1:]]

    async def test_ac13_ac29_message_during_a_run_is_queued_and_stop_returns_it(self, client, owner):
        """AC-13/AC-19/AC-29: a message sent during a run joins it; stop ends the run in 5s and returns it unread."""
        first, _ = await self._new_conversation(client, owner)
        conversation_id = first["conversation_id"]
        run = await _send(client, owner, LONG_QUESTION, conversation_id)
        assert run["disposition"] == "started"

        reader = asyncio.create_task(_events(client, owner, conversation_id, timeout=60.0))
        await asyncio.sleep(4)
        steer_text = f"{PREFIX}steer 再加上中国的进展"
        steer = await _send(client, owner, steer_text, conversation_id)
        assert steer["disposition"] == "queued"
        assert steer["run_id"] == run["run_id"]
        assert steer["message_id"]

        started = time.monotonic()
        stopped = await _stop(client, owner, conversation_id)
        assert stopped["status"] in ("stopping", "stopped")
        events = await reader
        assert time.monotonic() - started < 5, "AC-29: the run ends within 5 seconds"
        types = [event["type"] for event in events]
        assert "steer_accepted" in types
        assert types[-1] == "run_stopped"
        unread = stopped["unread_messages"] or events[-1]["data"]["unread_messages"]
        assert [message["text"] for message in unread] == [steer_text]

        again = await _stop(client, owner, conversation_id)
        assert again["status"] == "idle"

    async def test_ac30_message_after_a_stop_starts_a_new_run(self, client, owner):
        """AC-30: after a stop, the next message starts a new run in the same conversation."""
        first, _ = await self._new_conversation(client, owner)
        conversation_id = first["conversation_id"]
        run = await _send(client, owner, LONG_QUESTION, conversation_id)
        await asyncio.sleep(2)
        await _stop(client, owner, conversation_id)
        await _events(client, owner, conversation_id, timeout=30.0)

        nxt = await _send(client, owner, "只回复两个字：继续", conversation_id)
        assert nxt["disposition"] == "started"
        assert nxt["run_id"] != run["run_id"]
        events = await _events(client, owner, conversation_id)
        assert events[-1]["type"] == "run_finished"

    async def test_ac35_deep_research_gives_feedback_within_3_seconds(self, client, owner):
        """AC-35: with a free slot, deep research writes its first event within 3 seconds."""
        started = time.monotonic()
        sent = await _send(
            client, owner, f"{PREFIX}列出三个常见的排序算法并各用一句话说明，不要联网搜索，不要生成文件", task_mode=True
        )
        type(self).conversations.append(sent["conversation_id"])
        assert sent["disposition"] == "started"
        events = await _events(client, owner, sent["conversation_id"], until=lambda seen: len(seen) >= 1, timeout=30.0)
        assert time.monotonic() - started < 3
        assert events[0]["type"] == "run_started"
        stopped = await _stop(client, owner, sent["conversation_id"])
        assert stopped["status"] in ("stopping", "stopped")

    async def test_protocol_header_absent_is_answered_with_sse_frames(self, client, owner):
        """Design §4.3: without X-BS-Run-Protocol the answer is the earlier SSE frame format."""
        first, _ = await self._new_conversation(client, owner)
        resp = await client.post(
            f"{API_BASE}/workstation/chat/completions",
            json=_body("只回复两个字：兼容", first["conversation_id"]),
            headers=_owner_headers(owner),
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert '"final": true' in resp.text

    # ──────── Denied ────────

    async def test_ac28_non_owner_cannot_read_events(self, client, owner, other):
        """AC-28 (paired with AC-31): a non-owner gets the same refusal as for an unknown conversation."""
        sent, _ = await self._new_conversation(client, owner)
        resp = await client.get(
            f"{API_BASE}/workstation/conversations/{sent['conversation_id']}/events", headers=auth_headers(other)
        )
        assert_resp_error(resp, UNAUTHORIZED)
        resp = await client.get(f"{API_BASE}/workstation/conversations/{'0' * 32}/events", headers=auth_headers(other))
        assert_resp_error(resp, UNAUTHORIZED)

    async def test_ac28_non_owner_cannot_stop(self, client, owner, other):
        """AC-28 (paired with AC-29): a non-owner cannot stop the run, and the run goes on."""
        first, _ = await self._new_conversation(client, owner)
        conversation_id = first["conversation_id"]
        await _send(client, owner, LONG_QUESTION, conversation_id)
        resp = await client.post(
            f"{API_BASE}/workstation/conversations/{conversation_id}/stop", headers=auth_headers(other)
        )
        assert_resp_error(resp, UNAUTHORIZED)
        stopped = await _stop(client, owner, conversation_id)
        assert stopped["status"] in ("stopping", "stopped"), "the owner still finds the run in progress"

    async def test_ac28_non_owner_cannot_resolve_a_file(self, client, owner, other):
        """AC-28: a non-owner cannot get a file link of the conversation."""
        sent, _ = await self._new_conversation(client, owner)
        resp = await client.get(
            f"{API_BASE}/workstation/conversations/{sent['conversation_id']}/files/any/url", headers=auth_headers(other)
        )
        assert_resp_error(resp, UNAUTHORIZED)


# ──────── Open API daily chat (AC-39, design decision 14) ────────

# An Open API key with scope chat:invoke that may act on behalf of the admin.
# On behalf of the admin, its daily conversations belong to the admin account,
# so the class teardown can delete them through the login-state API.
OPEN_API_KEY = os.environ.get("E2E_F004_OPEN_API_KEY", "")
ON_BEHALF_OF = os.environ.get("E2E_F004_ON_BEHALF_OF", "1")
OPEN_API_BASE = API_BASE.replace("/api/v1", "/api/v2")
OPEN_API_FRAMES = [
    ("processing", "begin"),
    ("question", "over"),
    ("agent_answer", "end"),
    ("processing", "close"),
]


def _sse_datas(text: str) -> list[dict]:
    datas = []
    for block in text.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                datas.append(json.loads(line[len("data: ") :]))
    return datas


@pytest.mark.skipif(not OPEN_API_KEY, reason="E2E_F004_OPEN_API_KEY is not set")
class TestE2EF004OpenApiDailyChat:
    """E2E: Open API daily chat on the unified runtime keeps its contract."""

    conversations: list[str] = []

    @pytest.fixture(autouse=True, scope="class")
    async def setup_and_teardown(self):
        cls = type(self)
        cls.conversations = []
        yield
        async with httpx.AsyncClient(timeout=30.0) as client:
            token = await get_admin_token(client)
            for conversation_id in cls.conversations:
                await _stop(client, token, conversation_id)
                resp = await client.delete(f"{API_BASE}/chat/{conversation_id}", headers=_owner_headers(token))
                assert resp.status_code == 200, f"cleanup of {conversation_id} failed: {resp.text[:200]}"

    @pytest.fixture
    async def client(self):
        async with httpx.AsyncClient(timeout=180.0) as client:
            yield client

    async def _ask(self, client, text: str, conversation_id: str | None = None) -> tuple[httpx.Response, list[dict]]:
        resp = await client.post(
            f"{OPEN_API_BASE}/workstation/chat/completions",
            json=_body(text, conversation_id),
            # An Open API caller cannot switch protocols: the header changes nothing.
            headers={
                "Authorization": f"Bearer {OPEN_API_KEY}",
                "X-On-Behalf-Of": ON_BEHALF_OF,
                "X-BS-Run-Protocol": "2",
            },
        )
        datas = _sse_datas(resp.text) if resp.status_code == 200 else []
        final = next((d for d in datas if d.get("final")), None)
        if final:
            cid = final["conversation"]["conversationId"]
            if cid not in type(self).conversations:
                type(self).conversations.append(cid)
        return resp, datas

    async def test_ac39_daily_chat_answers_in_the_sse_contract(self, client):
        """AC-39: the request format and the SSE frame sequence are unchanged."""
        resp, datas = await self._ask(client, "只回复两个字：收到")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        shape = [(d.get("category"), d.get("type")) for d in datas if d.get("category")]
        assert [s for s in shape if s in OPEN_API_FRAMES] == OPEN_API_FRAMES
        assert ("agent_answer", "stream") in shape
        assert datas[-1]["final"] is True and datas[-1]["conversation"]["conversationId"]
        end = next(d for d in datas if (d.get("category"), d.get("type")) == ("agent_answer", "end"))
        assert end["message"]["msg"]

    async def test_ac39_second_message_on_a_busy_conversation_gets_its_own_answer(self, client):
        """AC-39 / decision 14: a message sent while the conversation answers waits and is answered itself."""
        _, first = await self._ask(client, "只回复两个字：开始")
        conversation_id = first[-1]["conversation"]["conversationId"]

        long_answer = asyncio.create_task(self._ask(client, LONG_QUESTION, conversation_id))
        await asyncio.sleep(3)
        resp, datas = await self._ask(client, "只回复两个字：第二", conversation_id)
        (_, long_datas) = await long_answer

        for frames in (long_datas, datas):
            assert frames[-1]["final"] is True
            assert any((d.get("category"), d.get("type")) == ("agent_answer", "end") for d in frames)
        question = next(d for d in datas if (d.get("category"), d.get("type")) == ("question", "over"))
        assert question["message"]["query"] == "只回复两个字：第二"

    async def test_ac39_unknown_conversation_is_404(self, client):
        """AC-39 (paired): a conversation the caller cannot see is HTTP 404, as before.

        The foreign-owner case is covered by test_unified_run_api.py.
        """
        resp, _ = await self._ask(client, "你好", "0" * 32)

        assert resp.status_code == 404
