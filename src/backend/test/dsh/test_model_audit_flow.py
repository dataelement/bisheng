"""Isolated AC-01/AC-04/AC-08/AC-09/AC-13/AC-17/AC-24/AC-28/AC-38 HTTP acceptance.

Uses real route/service/repository/encryption code; external identity/model are synthetic.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
from bisheng.dsh.domain.repositories.model_audit_write import DshModelAuditWriteRepository
from bisheng.dsh.domain.schemas.model_audit import AuditModeCommand
from bisheng.dsh.domain.services.model_audit_states import derive_audit_states
from bisheng.dsh.infrastructure.model_audit_keys import AuditKeyRing
from bisheng.dsh.infrastructure.model_audit_storage import EncryptedAuditStorage
from test.dsh.model_audit_fixtures import NOW, FaultAuditObjects, audit_database, audit_session
from test.dsh.model_audit_harness import AuditHarness
from test.e2e.helpers.api import assert_resp_200


@asynccontextmanager
async def fixture(mode="CONTENT"):
    with audit_database() as engine:
        objects = FaultAuditObjects()
        storage = EncryptedAuditStorage(
            objects, AuditKeyRing({"fixture": bytes(range(32))}, active_id="fixture"), max_block_bytes=1024
        )
        harness = AuditHarness(
            engine, storage, tokens={"fixture-user": 20, "fixture-global": 1, "fixture-admin": 2, "fixture-other": 30}
        )
        await harness.modes.change_admin(1, 2, AuditModeCommand(operation_id="enable", expected_version=0, mode=mode))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=harness.app), base_url="http://fixture"
        ) as client:
            try:
                yield harness, client, objects
            finally:
                await harness.close()


USER = {"Authorization": "Bearer fixture-user"}
ADMIN = {"Authorization": "Bearer fixture-global"}
LOCAL_ADMIN = {"Authorization": "Bearer fixture-admin"}
BASE = "/api/v1/dsh/admin/model-audit"


async def call(client, **fields):
    return await client.post(
        "/api/v1/dsh/chat/completions",
        headers=USER,
        json={"model": "bisheng:42", "messages": [{"role": "user", "content": "e2e-dsh-audit-question"}], **fields},
    )


async def test_request_metadata_is_not_original_and_body_access_is_explicit():
    async with fixture() as (harness, client, objects):
        response = await call(client, audit_context={"conversation_id": "case sensitive ", "request_kind": "chat"})
        assert response.status_code == 200 and harness.calls == 1
        request_id = response.headers["x-request-id"]
        await harness.drain()
        detail = (await client.get(BASE + "/requests/" + request_id, headers=ADMIN)).json()["data"]
        assert detail["content_status"] == "COMPLETE"
        assert detail["model_result"] == "SUCCEEDED" and detail["response_result"] == "COMPLETED"
        assert detail["usage_settlement"] == "SETTLED" and detail["usage"]["total_tokens"] == 12
        assert "e2e-dsh-audit-question" not in json.dumps(detail)
        body = await client.post(BASE + "/requests/" + request_id + "/body-access", headers=LOCAL_ADMIN)
        assert body.headers["cache-control"] == "no-store"
        frames = [json.loads(line) for line in body.text.splitlines()]
        assert frames[0]["type"] == "meta" and frames[-1]["type"] == "end"
        assert frames[-1]["transfer_status"] == "COMPLETED"
        assert any("e2e-dsh-audit-question" in item.get("fragment", "") for item in frames)
        assert all(b"e2e-dsh-audit-question" not in value for value in objects.data.values())
        assert (await client.get(BASE + "/requests/" + request_id, headers=USER)).status_code == 403
        assert (
            await client.get(BASE + "/requests/" + request_id + "?tenant_id=3", headers=LOCAL_ADMIN)
        ).status_code == 403
        foreign = (await client.get(BASE + "/requests/" + request_id + "?tenant_id=3", headers=ADMIN)).json()["data"]
        assert foreign["audit_record_missing"] and foreign["gap"] == "UNKNOWN"
        denied = await client.put(
            BASE + "/settings/2", headers=LOCAL_ADMIN, json={"operation_id": "no", "expected_version": 1, "mode": "OFF"}
        )
        assert denied.status_code != 200 or denied.json()["status_code"] != 200


@pytest.mark.parametrize("storage_failure", [False, True])
async def test_deferred_body_storage_cannot_gate_sse_or_settlement(storage_failure):
    """AC-17, AC-35, AC-38: defer originals and keep SSE live during blocked/failed storage."""
    async with fixture() as (harness, client, objects):
        model_waiting, finish_model = asyncio.Event(), asyncio.Event()
        storage_started, release_storage = asyncio.Event(), asyncio.Event()
        original_put = objects.put

        async def delayed_put(key, value):
            storage_started.set()
            await release_storage.wait()
            if storage_failure:
                raise OSError("e2e-dsh-audit-storage-fault")
            await original_put(key, value)

        async def model(_messages, **_kwargs):
            harness.calls += 1
            yield AIMessageChunk(content="e2e-dsh-audit-first")
            model_waiting.set()
            await finish_model.wait()
            yield AIMessageChunk(
                content="-last",
                response_metadata={"finish_reason": "stop"},
                usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            )

        objects.put, harness.astream = delayed_put, model
        request = asyncio.create_task(call(client, stream=True))
        try:
            await asyncio.wait_for(model_waiting.wait(), 2)
            # Give both control consumers an opportunity to persist while the model is active.
            for _ in range(200):
                if not harness.queue.used_bytes and not harness.evidence.used_bytes:
                    break
                await asyncio.sleep(0.001)
            assert not storage_started.is_set() and not objects.data
            with audit_session(harness.engine) as session:
                from sqlmodel import select

                from bisheng.dsh.domain.models.model_audit_content import DshModelAuditOccurrence

                assert session.exec(select(DshModelAuditOccurrence)).all() == []
            finish_model.set()
            response = await asyncio.wait_for(asyncio.shield(request), 2)
            await asyncio.wait_for(storage_started.wait(), 2)
            assert response.status_code == 200 and "e2e-dsh-audit-first" in response.text
            assert "-last" in response.text and "[DONE]" in response.text and harness.calls == 1
            request_id = response.headers["x-request-id"]
            assert not release_storage.is_set()
            # Do not await the blocked body queue: the independent control path must finish.
            for _ in range(200):
                if not harness.queue.used_bytes:
                    break
                await asyncio.sleep(0.001)
            metadata = assert_resp_200(await client.get(BASE + "/requests/" + request_id, headers=ADMIN))
            assert metadata["model_result"] == "SUCCEEDED"
            assert metadata["response_result"] == "COMPLETED"
            assert metadata["usage_settlement"] == "SETTLED"
            assert (await client.get(BASE + "/requests/" + request_id, headers=USER)).status_code == 403
            assert (
                await client.get(BASE + "/requests/" + request_id + "?tenant_id=3", headers=LOCAL_ADMIN)
            ).status_code == 403
            release_storage.set()
            await harness.drain()
            final = assert_resp_200(await client.get(BASE + "/requests/" + request_id, headers=ADMIN))
            assert final["content_status"] == ("PARTIAL" if storage_failure else "COMPLETE")
            assert final["model_result"] == "SUCCEEDED" and final["usage"]["total_tokens"] == 12
        finally:
            finish_model.set()
            release_storage.set()
            await asyncio.gather(request, return_exceptions=True)


@pytest.mark.parametrize("stream", [False, True])
async def test_unified_tools_images_reasoning_and_token_like_content_are_lossless(stream):
    async with fixture() as (harness, client, _objects):
        tool_call = {"id": "call-1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}
        additional = {"tool_calls": [tool_call], "reasoning_content": "synthetic-reasoning"}

        async def invoke(_messages, **_kwargs):
            harness.calls += 1
            return AIMessage(
                content="",
                additional_kwargs=additional,
                response_metadata={"finish_reason": "tool_calls"},
                usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            )

        async def streamed(_messages, **_kwargs):
            harness.calls += 1
            yield AIMessageChunk(
                content="",
                additional_kwargs={**additional, "tool_calls": [{**tool_call, "index": 0}]},
                response_metadata={"finish_reason": "tool_calls"},
                usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            )

        harness.ainvoke, harness.astream = invoke, streamed
        image = "data:image/png;base64,iVBORw0KGgo="
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "synthetic-token-like"},
                    {"type": "image_url", "image_url": {"url": image}},
                ],
            },
            {"role": "assistant", "content": None, "tool_calls": [tool_call]},
            {"role": "tool", "tool_call_id": "call-1", "content": "synthetic-tool-result-" + "x" * 2048},
        ]
        tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
        response = await call(
            client,
            stream=stream,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            audit_context={"conversation_id": "tools-image", "request_kind": "chat"},
        )
        assert response.status_code == 200 and harness.calls == 1
        await harness.drain()
        request_id = response.headers["x-request-id"]
        detail = (await client.get(BASE + "/requests/" + request_id, headers=ADMIN)).json()["data"]
        assert detail["content_status"] == "COMPLETE"
        body = await client.post(BASE + "/requests/" + request_id + "/body-access", headers=ADMIN)
        parts = [json.loads(line) for line in body.text.splitlines() if json.loads(line)["type"] == "part"]

        def unit(index):
            return json.loads(
                "".join(
                    frame["fragment"] for frame in parts if frame["channel"] == "input" and frame["unit_index"] == index
                )
            )

        assert unit(0)["tools"] == tools and unit(0)["tool_choice"] == "auto"
        assert unit(1)["content"][1]["image_url"]["url"] == image
        assert unit(2)["tool_calls"] == [tool_call]
        assert unit(2)["content"] is None
        assert unit(3) == messages[2]
        assert "synthetic-reasoning" in body.text and "lookup" in body.text
        assert (
            "synthetic-token-like" in body.text and "fixture-user" not in body.text and "audit_context" not in body.text
        )


async def test_keyset_same_timestamp_and_filter_binding():
    async with fixture() as (harness, client, _objects):
        import secrets

        from sqlmodel import SQLModel

        from bisheng.user.domain.models.user import User

        SQLModel.metadata.create_all(harness.engine, tables=[User.__table__])
        with audit_session(harness.engine) as session, session.begin():
            session.add(
                User(user_id=20, user_name="e2e-dsh-audit-user%_literal", password=secrets.token_hex(32), delete=1)
            )
        for _ in range(3):
            await call(client, audit_context={"conversation_id": "timeline"})
        await harness.drain()
        first = (
            await client.get(
                BASE + "/conversations",
                headers=ADMIN,
                params={"user_id": 20, "conversation_id": "timeline", "limit": 2},
            )
        ).json()["data"]
        second = (
            await client.get(
                BASE + "/conversations",
                headers=ADMIN,
                params={"user_id": 20, "conversation_id": "timeline", "limit": 2, "cursor": first["next_cursor"]},
            )
        ).json()["data"]
        assert len(first["items"]) == 2 and len(second["items"]) == 1
        assert len({row["request_id"] for row in first["items"] + second["items"]}) == 3
        changed = await client.get(
            BASE + "/conversations",
            headers=ADMIN,
            params={"user_id": 20, "conversation_id": "other", "limit": 2, "cursor": first["next_cursor"]},
        )
        assert changed.json()["status_code"] == 26131
        named = (await client.get(BASE + "/requests", headers=ADMIN, params={"user_keyword": "%_literal"})).json()[
            "data"
        ]
        assert len(named["items"]) == 3 and all(row["user_id"] == 20 for row in named["items"])
        assert all(row["usage"]["latency_ms"] is not None for row in named["items"])
        unmatched = (await client.get(BASE + "/requests", headers=ADMIN, params={"user_keyword": "%_absent"})).json()[
            "data"
        ]
        assert unmatched["items"] == []


@pytest.mark.parametrize("mode", ["OFF", "METADATA"])
async def test_off_and_metadata_never_store_original(mode):
    async with fixture(mode) as (harness, client, objects):
        response = await call(client)
        await harness.drain()
        page = (await client.get(BASE + "/requests", headers=ADMIN)).json()["data"]
        assert objects.data == {}
        if mode == "OFF":
            assert page["items"] == [] and harness.writer.written == 0
        else:
            assert page["items"][0]["content_status"] == "NOT_CAPTURED"
            assert page["items"][0]["model_result"] == "SUCCEEDED"
        assert response.status_code == 200 and harness.calls == 1


async def test_slow_or_failed_audit_never_blocks_or_retries_the_model():
    async with fixture() as (harness, client, objects):
        release = asyncio.Event()
        original = objects.put

        async def delayed(key, body):
            await release.wait()
            await original(key, body)

        objects.put = delayed
        response = await asyncio.wait_for(call(client), 1)
        assert response.status_code == 200 and harness.calls == 1
        release.set()
        await harness.drain()
        objects.failure = True
        response = await asyncio.wait_for(call(client), 1)
        await harness.drain()
        row = (await client.get(BASE + "/requests/" + response.headers["x-request-id"], headers=ADMIN)).json()["data"]
        assert response.status_code == 200 and harness.calls == 2
        assert row["model_result"] == "SUCCEEDED" and row["content_status"] == "PARTIAL"


async def test_settlement_and_response_failure_do_not_change_successful_model_fact():
    async with fixture() as (harness, client, _objects):
        harness.billing_failure = True
        response = await call(client, stream=True)
        assert "event: error" in response.text and harness.calls == 1
        await harness.drain()
        row = (await client.get(BASE + "/requests/" + response.headers["x-request-id"], headers=ADMIN)).json()["data"]
        assert row["model_result"] == "SUCCEEDED" and row["response_result"] == "ERROR"
        assert row["usage_settlement"] == "UNCERTAIN" and row["content_status"] == "COMPLETE"


async def test_complete_loss_is_missing_not_no_model_call():
    async with fixture() as (harness, client, _objects):
        harness.queue.closed = True
        harness.evidence.closed = True
        response = await call(client)
        await harness.drain()
        result = (await client.get(BASE + "/requests/" + response.headers["x-request-id"], headers=ADMIN)).json()[
            "data"
        ]
        assert result["gap"] == "MODE_UNKNOWN" and result["audit_record_missing"]
        assert response.status_code == 200 and harness.calls == 1


async def test_independent_entry_is_not_a_gap_until_window_and_activity_allow_it():
    async with fixture() as (harness, client, _objects):
        harness.queue.closed = True
        response = await call(client)
        await harness.drain()
        request_id = response.headers["x-request-id"]
        result = await harness.queries.detail(1, 2, request_id)
        assert result["gap"] == "AWAITING" and result["effective_mode"] == "CONTENT"
        harness.queries.now = lambda: datetime.now(UTC) + timedelta(seconds=400)
        harness.queries.activity = AsyncMock(return_value=True)
        assert (await harness.queries.detail(1, 2, request_id))["gap"] == "AWAITING"
        harness.queries.activity.return_value = False
        assert (await harness.queries.detail(1, 2, request_id))["gap"] == "CONFIRMED"


def test_active_or_late_terminal_facts_are_not_fabricated_failures():
    row = SimpleNamespace(
        started_at=NOW,
        last_write_at=NOW,
        model_result="RUNNING",
        response_result="RUNNING",
        usage_settlement="PENDING",
        content_status="PENDING",
    )
    now = NOW + timedelta(seconds=400)
    assert derive_audit_states(row, now=now, window=300, activity=True, has_fragments=True) == {}
    states = derive_audit_states(row, now=now, window=300, activity=False, has_fragments=True)
    assert states == {
        "model_result": "UNKNOWN",
        "response_result": "UNKNOWN",
        "usage_settlement": "UNCERTAIN",
        "content_status": "PARTIAL",
    }
    row.model_result, row.content_status = "SUCCEEDED", "COMPLETE"
    states = derive_audit_states(row, now=now, window=300, activity=None, has_fragments=True)
    assert "model_result" not in states and "content_status" not in states


async def test_body_access_logging_failure_never_sends_original(monkeypatch):
    async with fixture() as (harness, client, _objects):
        response = await call(client)
        await harness.drain()

        def unavailable(*args, **kwargs):
            raise OSError("Synthetic access-log failure")

        monkeypatch.setattr(DshModelAuditQueryRepository, "access_attempt", unavailable)
        result = await client.post(
            BASE + "/requests/" + response.headers["x-request-id"] + "/body-access", headers=ADMIN
        )
        assert result.json()["status_code"] == 26134
        assert "e2e-dsh-audit-question" not in result.text and "fixture-reply" not in result.text


async def test_closing_at_unsent_end_frame_keeps_access_interrupted():
    from sqlmodel import select

    from bisheng.dsh.domain.models.model_audit_content import DshModelAuditBodyAccess

    async with fixture() as (harness, client, _objects):
        response = await call(client)
        await harness.drain()
        request_id = response.headers["x-request-id"]
        source = await harness.admin.bodies.prepare(1, 2, request_id)
        async for chunk in source:
            if json.loads(chunk)["type"] == "end":
                break
        await source.aclose()
        with audit_session(harness.engine) as session:
            row = session.exec(
                select(DshModelAuditBodyAccess).where(DshModelAuditBodyAccess.request_id == request_id)
            ).one()
            assert row.transfer_status == "INTERRUPTED"


async def test_cancel_after_first_delta_and_before_start_have_distinct_audit_boundary():
    from bisheng.dsh.domain.schemas.chat import DshChatRequest
    from bisheng.dsh.domain.services.access import DshPrincipal

    async with fixture() as (harness, _client, _objects):
        principal = DshPrincipal(tenant_id="2", user_id="20", seat_id="seat", session_id="session", grant_version=1)
        request = DshChatRequest(model="bisheng:42", messages=[{"role": "user", "content": "cancel"}], stream=True)
        stream = await harness.service.complete(principal, request, request_id="before")
        await stream.aclose()
        await harness.drain()
        with audit_session(harness.engine) as session:
            assert DshModelAuditWriteRepository(session).request("before") is None
        stream = await harness.service.complete(principal, request, request_id="after")
        assert "fixture-" in await anext(stream)
        await stream.aclose()
        await harness.drain()
        with audit_session(harness.engine) as session:
            row = DshModelAuditWriteRepository(session).request("after")
            assert row.model_result == "CANCELLED" and row.content_status == "COMPLETE"
            assert row.usage_settlement == "USAGE_UNKNOWN"
        assert harness.calls == 1


async def test_transport_send_failure_keeps_model_and_original_success():
    from fastapi.responses import JSONResponse

    from bisheng.dsh.api.responses import AuditObservedResponse
    from bisheng.dsh.domain.schemas.chat import DshChatRequest
    from bisheng.dsh.domain.services.access import DshPrincipal

    async with fixture() as (harness, _client, _objects):
        captures = []
        result = await harness.service.complete(
            DshPrincipal(tenant_id="2", user_id="20", seat_id="seat", session_id="session", grant_version=1),
            DshChatRequest(model="bisheng:42", messages=[{"role": "user", "content": "send fault"}]),
            request_id="send-fault",
            audit_callback=captures.append,
        )
        response = AuditObservedResponse(JSONResponse(result), captures[0])

        async def failed_send(_message):
            raise OSError("Synthetic send failure")

        with pytest.raises(OSError):
            await response({"type": "http"}, None, failed_send)
        await harness.drain()
        with audit_session(harness.engine) as session:
            row = DshModelAuditWriteRepository(session).request("send-fault")
            assert row.model_result == "SUCCEEDED" and row.content_status == "COMPLETE"
            assert row.response_result == "INTERRUPTED" and row.usage_settlement == "SETTLED"
