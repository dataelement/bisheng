"""Deferred originals stay bounded and never gate model output (AC-17, AC-38)."""

import asyncio
import json
from contextlib import contextmanager
from threading import RLock

import pytest

from bisheng.dsh.domain.services.model_audit_capture import AuditCapture
from bisheng.dsh.infrastructure.model_audit_queue import BoundedAuditQueue
from test.dsh.model_audit_fixtures import NOW, ControlledAuditQueue, FaultAuditObjects, audit_database, audit_session
from test.dsh.test_model_audit_capture import capture
from test.dsh.test_model_audit_writer import facts, writer_for


async def drain(queue):
    async with asyncio.timeout(5):
        while queue.used_bytes or queue.bodies.used_bytes:
            await asyncio.sleep(0.001)


async def test_5000_fragments_take_one_job_and_no_storage_before_terminal():
    controls, bodies = [], []
    release = asyncio.Event()

    async def control(event):
        controls.append(event)

    async def body(buffer):
        bodies.append(buffer)
        await release.wait()
        events = list(buffer.events())
        assert len(events) == 5001
        assert [e.unit_index for e in events[1:]] == list(range(5000))
        assert [e.sequence for e in events[1:]] == list(range(5000))
        assert all(json.loads(e.body)["delta"]["content"] == "x" for e in events[1:])

    queue = BoundedAuditQueue(max_events=4, max_bytes=8 * 1024 * 1024, consumer=control, body_consumer=body)
    try:
        cap, _ = capture("CONTENT", queue, budget=1024 * 1024)
        cap.entered([{"content": "question"}])
        for _ in range(5000):
            cap.output({"delta": {"content": "x"}})
        await asyncio.sleep(0)
        assert bodies == [] and [e.kind for e in controls] == ["entered"]
        assert len(queue.bodies.buffers) == 1 and queue.bodies.used_bytes <= queue.bodies.max_bytes
        cap.terminal("SUCCEEDED")
        cap.terminal("FAILED")
        cap.response("COMPLETED")
        cap.usage("SETTLED")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(bodies) == 1 and not cap.capture_failed and not queue.rejected
        assert [e.kind for e in controls] == ["entered", "terminal", "response", "usage"]
        assert queue.bodies.used_bytes > 0
        assert cap.body_buffer is None
        release.set()
        await drain(queue)
        assert not queue.bodies.buffers
    finally:
        release.set()
        await queue.close(1)


@pytest.mark.parametrize("model_result", ["SUCCEEDED", "FAILED", "CANCELLED"])
async def test_termination_submits_once_and_storage_failure_is_isolated(model_result):
    calls = []

    async def fail(buffer):
        calls.append(buffer.template.request_id)
        raise OSError("synthetic storage unavailable")

    async def control(_event):
        return True

    queue = BoundedAuditQueue(max_events=10, max_bytes=65536, consumer=control, body_consumer=fail)
    try:
        cap, _ = capture("CONTENT", queue)
        cap.entered([{"content": "question"}])
        cap.output({"delta": {"content": "answer"}})
        cap.terminal(model_result)
        cap.terminal(model_result)
        await drain(queue)
        assert calls == ["request"] and not queue.bodies.buffers
        assert queue.bodies.used_bytes == 0
    finally:
        await queue.close(1)


async def test_global_budget_covers_active_queued_and_inflight_requests():
    release = asyncio.Event()
    started = asyncio.Event()
    seen = []

    async def control(event):
        seen.append(event)

    async def body(_buffer):
        started.set()
        await release.wait()

    queue = BoundedAuditQueue(max_events=2, max_bytes=12000, consumer=control, body_consumer=body)
    try:
        first, _ = capture("CONTENT", queue)
        first.entered([{"content": "a"}])
        first.terminal("SUCCEEDED")
        await started.wait()
        first_cost = queue.bodies.used_bytes
        second, _ = capture("CONTENT", queue)
        second.entered([{"content": "b"}])
        await asyncio.sleep(0)
        assert queue.bodies.used_bytes > first_cost
        third, _ = capture("CONTENT", queue)
        third.entered([{"content": "c"}])
        assert third.capture_failed
        second.output({"delta": {"content": "x" * 5000}})
        assert second.capture_failed and queue.bodies.used_bytes <= 12000
        # A full body budget must not consume the independently bounded control slots.
        second.terminal("SUCCEEDED")
        await asyncio.sleep(0)
        third.terminal("SUCCEEDED")
        await asyncio.sleep(0)
        assert any(e.kind == "terminal" and e.metadata["capture_failed"] for e in seen)
        release.set()
        await drain(queue)
        assert queue.bodies.used_bytes == 0
    finally:
        release.set()
        await queue.close(1)


async def test_shutdown_releases_active_queued_and_writing_buffers_with_deadline():
    started = asyncio.Event()

    async def control(_event):
        pass

    async def blocked(_buffer):
        started.set()
        await asyncio.Event().wait()

    queue = BoundedAuditQueue(max_events=10, max_bytes=65536, consumer=control, body_consumer=blocked)
    cap, _ = capture("CONTENT", queue)
    cap.entered([{"content": "writing"}])
    cap.terminal("SUCCEEDED")
    await started.wait()
    queued, _ = capture("CONTENT", queue)
    queued.entered([{"content": "queued"}])
    queued.terminal("SUCCEEDED")
    active, _ = capture("CONTENT", queue)
    active.entered([{"content": "active"}])
    await asyncio.wait_for(queue.close(0.01), 1)
    assert queue.bodies.used_bytes == 0 and not queue.bodies.buffers and not queue.bodies.pending
    active.output({"content": "still a business response"})
    active.terminal("CANCELLED")
    assert active.capture_failed and queue.bodies.used_bytes == 0


async def test_real_batched_writer_is_replay_safe_and_preserves_original_encoding():
    from bisheng.dsh.domain.repositories.model_audit_write import DshModelAuditWriteRepository

    with audit_database() as engine:
        objects = FaultAuditObjects()
        writer = writer_for(engine, objects)
        original_scope, lock = writer.repository_scope, RLock()

        @contextmanager
        def serialized_sqlite_scope():
            # SQLite StaticPool has one connection; production has independent DB connections.
            with lock, original_scope() as repository:
                yield repository

        writer.repository_scope = serialized_sqlite_scope
        batches = []

        async def retain(buffer):
            # Replay while the queue still owns the reserved fragments.
            await writer.write_body_batch(buffer)
            await writer.write_body_batch(buffer)
            batches.append(len(buffer.fragments))

        queue = BoundedAuditQueue(max_events=10, max_bytes=65536, consumer=writer.write, body_consumer=retain)
        try:
            facts(queue)
            await drain(queue)
            with audit_session(engine) as session:
                repo = DshModelAuditWriteRepository(session)
                row = repo.request("request-a")
                assert row.content_status == "COMPLETE" and row.audit_status == "NORMAL"
                manifest, occurrences, contents = repo.facts(row.request_id)
                assert len(occurrences) == sum(c["count"] for c in manifest.channels.values()) == batches[0]
                assert contents and writer.failed == 0
                assert objects.data and all(b'"content"' not in value for value in objects.data.values())
        finally:
            await queue.close(1)


async def test_background_writer_bounds_object_concurrency_and_transaction_size():
    from bisheng.dsh.domain.services.model_audit_writer import DshModelAuditWriter

    active = maximum = 0
    transactions = []

    class Storage:
        async def put_verified_block(self, _scope, _body, **_kwargs):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            try:
                await asyncio.sleep(0)
                return object()
            finally:
                active -= 1

    writer = DshModelAuditWriter(None, Storage, attempts=1)
    writer._persist_bodies = lambda verified: transactions.append(len(verified))

    async def control(_event):
        pass

    queue = BoundedAuditQueue(max_events=4, max_bytes=65536, consumer=control, body_consumer=writer.write_body_batch)
    try:
        cap, _ = capture("CONTENT", queue)
        cap.entered([{"content": "e2e-dsh-audit-question"}])
        for _ in range(100):
            cap.output({"delta": {"content": "x"}})
        cap.terminal("SUCCEEDED")
        await drain(queue)
        assert maximum == 4 and active == 0
        assert transactions == [32, 32, 32, 5] and writer.written == 101
    finally:
        await queue.close(1)


def test_deterministic_capture_has_no_body_events_until_terminal():
    queue = ControlledAuditQueue()
    cap = AuditCapture(
        {"request_id": "deferred", "tenant_id": 2, "user_id": 20, "effective_mode": "CONTENT"},
        queue,
        now=lambda: NOW,
        chunk_bytes=1024,
        request_budget_bytes=65536,
        digest_key=bytes(range(32)),
    )
    cap.entered([{"content": "question"}])
    cap.output({"content": "answer"})
    assert [e.kind for e in queue.events] == ["entered"]
    cap.terminal("SUCCEEDED")
    assert [e.kind for e in queue.events] == ["entered", "body", "body", "terminal"]
