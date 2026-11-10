"""覆盖 AC: AC-44, AC-45, AC-46, AC-47, AC-48."""

import json

from bisheng.dsh.domain.repositories.model_audit_write import DshModelAuditWriteRepository
from bisheng.dsh.domain.services.model_audit_capture import AuditCapture
from test.dsh.model_audit_fixtures import NOW, ControlledAuditQueue, FaultAuditObjects, audit_database, audit_session
from test.dsh.test_model_audit_writer import writer_for

SOURCES = {"items": [{"message_index": 0, "sources": [{"kind": "skill-catalog"}]}], "truncated": False}


def capture(queue, annotations, mode="CONTENT"):
    result = AuditCapture(
        {
            "request_id": "source-request",
            "tenant_id": 2,
            "user_id": 20,
            "session_id": "s",
            "model_id": 42,
            "conversation_id": "child",
            "session_origin": "subagent",
            "parent_conversation_id": "parent",
            "effective_mode": mode,
            "started_at": NOW,
        },
        queue,
        now=lambda: NOW,
        chunk_bytes=64,
        request_budget_bytes=65536,
        digest_key=bytes(range(32)),
        key_version="test-key",
        annotation_queue=annotations,
        message_sources=SOURCES,
        message_sources_status="AVAILABLE",
    )
    result.entered([{"role": "user", "content": "hello"}])
    result.terminal("SUCCEEDED")
    return result


async def test_annotations_are_encrypted_separate_and_never_change_body_integrity():
    with audit_database() as engine:
        queue, annotations, objects = ControlledAuditQueue(), ControlledAuditQueue(), FaultAuditObjects()
        capture(queue, annotations)
        writer = writer_for(engine, objects)
        events = queue.drain()
        assert all("message_sources" not in event.metadata for event in events)
        for event in events:
            assert await writer.write(event)
        with audit_session(engine) as session:
            row = DshModelAuditWriteRepository(session).request("source-request")
            assert row.content_status == "COMPLETE" and row.message_sources_status == "PENDING"
        for event in annotations.drain():
            assert await writer.write(event)
        with audit_session(engine) as session:
            row = DshModelAuditWriteRepository(session).request("source-request")
            assert row.content_status == "COMPLETE" and row.message_sources_status == "AVAILABLE"
            assert row.message_sources_ref and "skill-catalog" not in json.dumps(row.message_sources_ref)
            assert row.parent_conversation_id == "parent"


async def test_http_child_compaction_parent_scope_and_authorized_sources():
    """AC-40, AC-43, AC-44, AC-45, AC-47, AC-48: full route/storage/read chain."""
    from test.dsh.test_model_audit_flow import ADMIN, BASE, LOCAL_ADMIN, USER, call, fixture

    async with fixture() as (harness, client, objects):
        await call(
            client, audit_context={"conversation_id": "parent", "request_kind": "chat", "session_origin": "main"}
        )
        response = await call(
            client,
            audit_context={
                "conversation_id": "child",
                "request_kind": "compaction",
                "session_origin": "subagent",
                "parent_conversation_id": "parent",
                "message_sources": SOURCES,
            },
        )
        assert harness.calls == 2
        request_id = response.headers["x-request-id"]
        await harness.drain()
        detail = (await client.get(BASE + "/requests/" + request_id, headers=ADMIN)).json()["data"]
        assert detail["request_kind"] == "compaction" and detail["session_origin"] == "subagent"
        assert detail["parent_conversation_id"] == "parent" and detail["content_status"] == "COMPLETE"
        assert "skill-catalog" not in json.dumps(detail)
        parent = (
            await client.get(BASE + "/requests/" + request_id + "/parent-conversation", headers=LOCAL_ADMIN)
        ).json()["data"]
        assert parent == {"status": "AVAILABLE", "user_id": 20, "conversation_id": "parent"}
        path = BASE + "/requests/" + request_id + "/body-access"
        original = await client.post(path, headers=ADMIN)
        assert all(json.loads(line)["type"] != "annotations" for line in original.text.splitlines())
        result = await client.post(path + "?include_message_sources=true", headers=LOCAL_ADMIN)
        frames = [json.loads(line) for line in result.text.splitlines()]
        assert frames[1] == {"type": "annotations", "message_sources_status": "AVAILABLE", "items": SOURCES["items"]}
        assert frames[-1]["content_state"] == "COMPLETE"
        assert "audit_context" not in "".join(frame.get("fragment", "") for frame in frames)
        assert all(b"skill-catalog" not in data for data in objects.data.values())
        assert (await client.post(path + "?include_message_sources=true", headers=USER)).status_code == 403
        assert (
            await client.get(BASE + "/requests/" + request_id + "/parent-conversation?tenant_id=3", headers=LOCAL_ADMIN)
        ).status_code == 403
        with audit_session(harness.engine) as session:
            row = DshModelAuditWriteRepository(session).request(request_id)
            key = row.message_sources_ref["object_key"]
        objects.data[key] = b"corrupt annotation"
        result = await client.post(path + "?include_message_sources=true", headers=ADMIN)
        frames = [json.loads(line) for line in result.text.splitlines()]
        assert frames[1]["message_sources_status"] == "UNAVAILABLE"
        assert frames[-1]["content_state"] == "COMPLETE" and frames[-1]["transfer_status"] == "COMPLETED"


async def test_parent_cannot_resolve_other_historical_user():
    """AC-45: an administrator's broad scope must not widen a declared edge."""
    from test.dsh.test_model_audit_flow import ADMIN, BASE, call, fixture

    async with fixture() as (harness, client, _objects):
        harness.tokens["fixture-peer"] = 21
        await client.post(
            "/api/v1/dsh/chat/completions",
            headers={"Authorization": "Bearer fixture-peer"},
            json={
                "model": "bisheng:42",
                "messages": [{"role": "user", "content": "e2e-peer"}],
                "audit_context": {"conversation_id": "peer-parent"},
            },
        )
        child = await call(
            client,
            audit_context={
                "conversation_id": "child",
                "session_origin": "subagent",
                "parent_conversation_id": "peer-parent",
            },
        )
        await harness.drain()
        target = await client.get(
            BASE + "/requests/" + child.headers["x-request-id"] + "/parent-conversation", headers=ADMIN
        )
        assert target.json()["data"] == {"status": "UNAVAILABLE"}


def test_metadata_never_enqueues_source_array():
    queue, annotations = ControlledAuditQueue(), ControlledAuditQueue()
    capture(queue, annotations, mode="METADATA")
    assert annotations.drain() == []
    assert all(event.metadata["message_sources_status"] == "NOT_CAPTURED" for event in queue.drain())


async def test_source_pending_scan_is_fair_after_complete_body():
    """AC-46: active annotations must not starve later requests in the next page."""
    from contextlib import contextmanager
    from datetime import timedelta
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
    from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
    from bisheng.dsh.domain.services.model_audit_queries import DshModelAuditQueryService
    from bisheng.dsh.domain.services.model_audit_states import DshModelAuditStateService

    with audit_database() as engine:
        with audit_session(engine) as session, session.begin():
            session.add_all(
                [
                    DshModelAuditRequest(
                        request_id="source-" + str(index).zfill(3),
                        user_id=20,
                        effective_mode="CONTENT",
                        started_at=NOW,
                        last_write_at=NOW,
                        model_result="SUCCEEDED",
                        response_result="COMPLETED",
                        usage_settlement="SETTLED",
                        content_status="COMPLETE",
                        message_sources_status="PENDING",
                    )
                    for index in range(101)
                ]
            )

        @contextmanager
        def scope():
            with audit_session(engine) as session, session.begin():
                yield DshModelAuditQueryRepository(session)

        activity = SimpleNamespace(confirmed=AsyncMock(return_value=True))
        queries = DshModelAuditQueryService(None, scope)
        service = DshModelAuditStateService(queries, activity, window=30, now=lambda: NOW + timedelta(hours=1))
        cursor, _changed = await service.inspect(2)
        assert cursor.startswith("annotations:")
        next_cursor, _changed = await service.inspect(2, cursor)
        assert next_cursor is None
        assert activity.confirmed.await_count == 101
