"""AC-09/AC-10/AC-20/AC-38: asynchronous facts, references and completeness."""

from contextlib import contextmanager
from dataclasses import replace

from sqlmodel import select

from bisheng.dsh.domain.models.model_audit_content import DshModelAuditContent, DshModelAuditOccurrence
from bisheng.dsh.domain.repositories.model_audit_write import DshModelAuditWriteRepository
from bisheng.dsh.domain.services.model_audit_capture import AuditCapture
from bisheng.dsh.domain.services.model_audit_writer import DshModelAuditWriter
from bisheng.dsh.infrastructure.model_audit_keys import AuditKeyRing
from bisheng.dsh.infrastructure.model_audit_storage import EncryptedAuditStorage
from test.dsh.model_audit_fixtures import (
    NOW,
    ControlledAuditQueue,
    FaultAuditObjects,
    audit_database,
    audit_session,
)


def facts(queue, *, request_id="request-a", conversation="会话 A", user=20, mode="CONTENT"):
    capture = AuditCapture(
        {
            "request_id": request_id,
            "tenant_id": 2,
            "user_id": user,
            "session_id": "session",
            "model_id": 42,
            "conversation_id": conversation,
            "effective_mode": mode,
            "started_at": NOW,
        },
        queue,
        now=lambda: NOW,
        chunk_bytes=64,
        digest_key=bytes(range(32)),
        key_version="test-key",
        request_budget_bytes=65536,
    )
    capture.entered([{"role": "user", "content": "你好" * 100}])
    capture.output({"content": "你好"})
    capture.terminal("SUCCEEDED")
    capture.response("COMPLETED")
    capture.usage("SETTLED")
    return capture


def writer_for(engine, objects):
    @contextmanager
    def scope():
        with audit_session(engine) as session, session.begin():
            yield DshModelAuditWriteRepository(session)

    storage = EncryptedAuditStorage(
        objects, AuditKeyRing({"test-key": bytes(range(32))}, active_id="test-key"), max_block_bytes=64
    )
    return DshModelAuditWriter(scope, lambda: storage, attempts=1)


async def test_reordered_replayed_facts_restore_complete_without_body_in_sql():
    with audit_database() as engine:
        queue, objects = ControlledAuditQueue(), FaultAuditObjects()
        facts(queue)
        events = queue.drain()
        writer = writer_for(engine, objects)
        for event in reversed(events):
            assert await writer.write(event)
        for event in events:
            assert await writer.write(event)
        with audit_session(engine) as session:
            repo = DshModelAuditWriteRepository(session)
            row = repo.request("request-a")
            assert (row.model_result, row.response_result, row.usage_settlement, row.content_status) == (
                "SUCCEEDED",
                "COMPLETED",
                "SETTLED",
                "COMPLETE",
            )
            manifest, occurrences, contents = repo.facts(row.request_id)
            assert len(occurrences) == sum(value["count"] for value in manifest.channels.values())
            assert len(contents) <= len(occurrences)
            assert not any("body" in column.name for column in DshModelAuditContent.__table__.columns)
        with audit_session(engine, 3) as session:
            assert DshModelAuditWriteRepository(session).request("request-a") is None


async def test_missing_tail_and_collision_are_not_complete():
    with audit_database() as engine:
        queue, objects = ControlledAuditQueue(), FaultAuditObjects()
        facts(queue)
        events = queue.drain()
        writer = writer_for(engine, objects)
        bodies = [event for event in events if event.kind == "body"]
        for event in events:
            if event is not bodies[-1]:
                assert await writer.write(event)
        with audit_session(engine) as session:
            assert DshModelAuditWriteRepository(session).request("request-a").content_status == "PARTIAL"
        assert await writer.write(bodies[-1])
        assert await writer.write(replace(bodies[0], body=b"x"))
        with audit_session(engine) as session:
            assert DshModelAuditWriteRepository(session).request("request-a").content_status == "PARTIAL"


async def test_storage_fault_does_not_create_ready_reference():
    with audit_database() as engine:
        queue, objects = ControlledAuditQueue(), FaultAuditObjects()
        facts(queue)
        objects.failure = True
        writer = writer_for(engine, objects)
        for event in queue.drain():
            assert await writer.write(event) is (event.kind != "body")
        with audit_session(engine) as session:
            assert DshModelAuditWriteRepository(session).request("request-a").content_status == "PARTIAL"
            assert session.exec(select(DshModelAuditOccurrence)).all() == []


async def test_repeated_input_shares_objects_only_inside_same_user_conversation():
    with audit_database() as engine:
        objects, queue = FaultAuditObjects(), ControlledAuditQueue()
        writer = writer_for(engine, objects)
        for name, user, conversation in (("a", 20, "s"), ("b", 20, "s"), ("c", 21, "s"), ("d", 20, None)):
            facts(queue, request_id=name, user=user, conversation=conversation)
            for event in queue.drain():
                assert await writer.write(event)
        with audit_session(engine) as session:
            repo = DshModelAuditWriteRepository(session)
            sets = [set(repo.facts(name)[2]) for name in ("a", "b", "c", "d")]
            assert sets[0] == sets[1]
            assert sets[0].isdisjoint(sets[2]) and sets[0].isdisjoint(sets[3])
