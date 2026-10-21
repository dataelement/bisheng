"""覆盖 AC: AC-12, AC-15, AC-17, AC-24, AC-30, AC-31, AC-36, AC-37, AC-38."""

import asyncio
from threading import Event
from unittest.mock import AsyncMock

import pytest

from bisheng.core.context.tenant import get_current_tenant_id, set_current_tenant_id
from bisheng.dsh.config import DshSettings
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditEvidence
from bisheng.dsh.domain.repositories.model_audit_write import DshModelAuditWriteRepository
from bisheng.dsh.domain.schemas.model_audit_events import AuditEvent
from bisheng.dsh.domain.services.model_audit_states import DshModelAuditStateService
from bisheng.dsh.infrastructure.model_audit_blocking import run_audit_blocking
from bisheng.dsh.infrastructure.model_audit_queue import BoundedAuditQueue
from test.dsh.model_audit_fixtures import NOW, AuditTestClock, audit_session
from test.dsh.test_model_audit_flow import ADMIN, BASE, call, fixture


async def test_cancelled_audit_io_cannot_exhaust_business_executor():
    release = Event()
    entered = Event()

    def blocked():
        entered.set()
        release.wait(5)
        return get_current_tenant_id()

    token = set_current_tenant_id(2)
    tasks = []
    try:
        tasks = [asyncio.create_task(run_audit_blocking(blocked)) for _ in range(12)]
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.001)
        with pytest.raises(RuntimeError, match="capacity"):
            await run_audit_blocking(lambda: None)
        assert await asyncio.wait_for(asyncio.to_thread(lambda: "business"), 1) == "business"
        for task in tasks:
            task.cancel()
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        token.var.reset(token)
    assert await run_audit_blocking(lambda: get_current_tenant_id()) == get_current_tenant_id()


async def test_queue_is_bounded_including_inflight_and_shutdown_has_deadline():
    release = asyncio.Event()

    async def consumer(_event):
        await release.wait()

    queue = BoundedAuditQueue(max_events=2, max_bytes=8192, consumer=consumer)
    event = AuditEvent("request", 2, "entered", NOW)
    assert queue.put(event)
    await asyncio.sleep(0)
    assert queue.put(event)
    assert not queue.put(event)
    await asyncio.wait_for(queue.close(0.01), 1)
    assert queue.closed and not queue.events and queue.used_bytes == 0


@pytest.mark.parametrize("native", [False, True])
async def test_production_mode_failure_creates_only_minimal_diagnostic(monkeypatch, native):
    from bisheng.dsh.audit_runtime import ModelAuditRuntime
    from bisheng.dsh.domain.schemas.chat import DshChatRequest
    from bisheng.dsh.domain.schemas.responses import DshResponsesRequest
    from bisheng.dsh.domain.services.access import DshPrincipal, principal_scope

    async with fixture() as (harness, _client, _objects):
        import bisheng.dsh.audit_runtime as composition

        monkeypatch.setattr(composition, "repository_scope", harness.scope)
        runtime = ModelAuditRuntime(DshSettings(), AsyncMock())

        async def unavailable():
            raise TimeoutError("synthetic")

        runtime.modes.read_snapshot = unavailable
        principal = DshPrincipal(tenant_id="2", user_id="20", session_id="session", seat_id="seat", grant_version=1)
        with principal_scope(principal):
            capture = await runtime.capture(
                principal,
                DshResponsesRequest(model="bisheng:42", input=[{"role": "user", "content": "must-not-retain"}])
                if native
                else DshChatRequest(model="bisheng:42", messages=[{"role": "user", "content": "must-not-retain"}]),
                "mode-failed",
                NOW,
                harness.model,
                harness.server,
            )
            capture.entered([{"content": "must-not-retain"}])
            capture.terminal("SUCCEEDED")
        await runtime.close()
        assert capture.mode == "OFF" and runtime.writer.written == 1
        with audit_session(harness.engine) as session:
            repo = DshModelAuditWriteRepository(session)
            assert repo.request("mode-failed") is None
            row = repo.one(DshModelAuditEvidence, DshModelAuditEvidence.request_id == "mode-failed")
            assert row.event_type == "MODE_READ_FAILED" and row.user_id is None and row.effective_mode is None
        result = await harness.queries.detail(1, 2, "mode-failed")
        assert result["gap"] == "DEGRADED_OFF" and result["effective_mode"] == "OFF"


async def test_activity_and_late_observations_restore_unknown_state():
    async with fixture() as (harness, client, _objects):
        response = await call(client)
        await harness.drain()
        request_id = response.headers["x-request-id"]
        with audit_session(harness.engine) as session, session.begin():
            repository = DshModelAuditWriteRepository(session)
            row = repository.request(request_id)
            manifest = repository.manifest(request_id)
            metadata = {
                key: getattr(row, key)
                for key in (
                    "user_id",
                    "session_id",
                    "model_id",
                    "conversation_id",
                    "effective_mode",
                    "started_at",
                    "input_units",
                )
            }
            metadata.update(
                {
                    key: getattr(manifest, key)
                    for key in ("input_complete", "capture_failed", "model_result", "channels")
                }
            )
            row.model_result, row.response_result = "RUNNING", "RUNNING"
            row.usage_settlement, row.content_status = "PENDING", "PENDING"
            row.started_at = row.last_write_at = NOW
            session.add(row)
        clock = AuditTestClock()
        clock.advance(400)
        activity = AsyncMock()
        activity.confirmed.return_value = True
        state = DshModelAuditStateService(harness.queries, activity, window=300, now=clock)
        assert (await state.inspect(2))[1] == 0
        activity.confirmed.return_value = False
        assert (await state.inspect(2))[1] == 1
        row = (await client.get(BASE + "/requests/" + request_id, headers=ADMIN)).json()["data"]
        assert row["model_result"] == "UNKNOWN" and row["content_status"] == "PARTIAL"
        for kind, extra in (
            ("terminal", {}),
            ("response", {"response_result": "COMPLETED"}),
            ("usage", {"usage_settlement": "SETTLED"}),
        ):
            assert await harness.writer.write(AuditEvent(request_id, 2, kind, clock(), {**metadata, **extra}))
        row = (await client.get(BASE + "/requests/" + request_id, headers=ADMIN)).json()["data"]
        assert (row["model_result"], row["response_result"], row["usage_settlement"], row["content_status"]) == (
            "SUCCEEDED",
            "COMPLETED",
            "SETTLED",
            "COMPLETE",
        )


async def test_missing_digest_key_is_partial_without_plaintext_fallback():
    from bisheng.dsh.domain.services.model_audit_capture import AuditCapture
    from test.dsh.model_audit_fixtures import ControlledAuditQueue

    queue = ControlledAuditQueue()
    capture = AuditCapture(
        {"request_id": "missing", "tenant_id": 2, "user_id": 20, "effective_mode": "CONTENT"},
        queue,
        now=AuditTestClock(),
        chunk_bytes=1024,
        request_budget_bytes=65536,
    )
    capture.entered([{"content": "never write clear"}])
    capture.terminal("SUCCEEDED")
    assert all(event.body is None for event in queue.events)
    assert queue.events[-1].metadata["capture_failed"]
