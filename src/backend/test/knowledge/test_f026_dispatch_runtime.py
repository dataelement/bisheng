"""T018 local integration: production scan/claim/apply against a temporary SQLite file."""

from contextlib import asynccontextmanager
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderInstance, KnowledgeProviderOperation
from bisheng.worker.knowledge import provider_dispatch as dispatch
from bisheng.worker.knowledge import provider_operations as operations


async def test_scan_proof_admission_and_crash_recovery(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ledger.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    open_sessions = 0

    @asynccontextmanager
    async def session_scope():
        nonlocal open_sessions
        async with factory() as session:
            open_sessions += 1
            try:
                yield session
            finally:
                open_sessions -= 1

    try:
        async with engine.begin() as conn:
            for model in (KnowledgeProviderInstance, KnowledgeProviderOperation):
                await conn.run_sync(model.__table__.create)
        now = operations.utcnow()
        async with factory.begin() as session:
            session.add(
                KnowledgeProviderInstance(
                    id=2,
                    tenant_id=17,
                    provider_key="test",
                    endpoint="fixture",
                    credential_ref="ref",
                    remote_scope_id="org",
                )
            )
            for oid, kind, state, offset in [
                ("live", "create", "pending", -2),
                ("unsupported", "copy", "pending", -3),
                ("later", "create", "pending", 60),
                ("done", "create", "succeeded", -5),
                ("busy", "create", "sending", -1),
            ]:
                session.add(
                    KnowledgeProviderOperation(
                        operation_id=oid,
                        tenant_id=17,
                        provider_instance_id=2,
                        actor_user_id=3,
                        kind=kind,
                        state=state,
                        phase="create",
                        request_hash="d" * 64,
                        request_key=oid,
                        remote_scope_id="org",
                        remote_kb_id="frozen",
                        generation=1,
                        operation_epoch=3,
                        capability_revision=1,
                        next_attempt_at=now + timedelta(seconds=offset),
                        lease_token="other-worker" if oid == "busy" else None,
                        lease_until=now + timedelta(seconds=30) if oid == "busy" else None,
                    )
                )
        monkeypatch.setattr(dispatch, "get_async_db_session", session_scope)
        monkeypatch.setattr(operations, "get_async_db_session", session_scope)
        monkeypatch.setattr(operations, "INSTANCE_CONCURRENCY", 1)
        monkeypatch.setattr(dispatch, "_active_tenant_ids", AsyncMock(return_value=[17, 18]))
        monkeypatch.setattr(operations, "utcnow", lambda: now)
        sent = []

        async def publish(**message):
            assert get_current_tenant_id() == 17 and open_sessions == 0
            sent.append(message)

        monkeypatch.setattr(dispatch, "_publish", publish)

        async def confirmed(row):
            assert get_current_tenant_id() == 17 and open_sessions == 0
            assert row.remote_kb_id == "frozen" and row.operation_epoch == 3
            # Verify lease committed before remote or projection I/O.
            async with factory() as session:
                current = await session.get(KnowledgeProviderOperation, row.operation_id)
                assert current.lease_token == row.lease_token and current.revision == row.revision
            return "confirmed"

        send, reconcile, project = (
            AsyncMock(side_effect=confirmed),
            AsyncMock(side_effect=confirmed),
            AsyncMock(side_effect=confirmed),
        )
        monkeypatch.setitem(
            operations.PROVIDER_HANDLERS, "create", operations.ProviderHandlers(send, reconcile, project)
        )
        with tenant_execution_scope(99):
            assert await dispatch._scan() == 1
            assert sent == [{"operation_id": "live", "expected_revision": 1, "headers": {"tenant_id": 17}}]
            assert not await operations._execute(18, "live", 1)
            assert not await operations._execute(17, "unsupported", 1)
            assert not await operations._execute(17, "live", 2)
            assert not await operations._execute(17, "live", 1)  # slot is leased by busy
            send.assert_not_awaited()
            now += timedelta(seconds=31)
            assert await operations._execute(17, "busy", 1)  # crashed sender only reconciles
            send.assert_not_awaited()
            reconcile.assert_awaited_once()
            assert not await operations._execute(17, "busy", 1)
            assert await operations._execute(17, "busy", 3)
            project.assert_awaited_once()
            assert await operations._execute(17, "live", 1)
            send.assert_awaited_once()
            assert get_current_tenant_id() == 99
        async with factory() as session:
            unsupported = await session.get(KnowledgeProviderOperation, "unsupported")
            assert (unsupported.state, unsupported.attempt, unsupported.revision) == ("pending", 0, 1)
            assert (await session.get(KnowledgeProviderOperation, "busy")).state == "succeeded"
    finally:
        await engine.dispose()


def test_beat_route_and_task_body_rejects_missing_header():
    from types import SimpleNamespace

    from bisheng.worker import config

    schedule = config.beat_schedule["knowledge-provider-operation-recovery"]
    assert schedule["task"] == "bisheng.worker.knowledge.provider_dispatch.dispatch_due_provider_operations"
    assert schedule["options"]["queue"] == "knowledge_celery"
    # The shared pytest fixture exposes undecorated task bodies, not a live app.
    body = operations.advance_provider_operation.run
    with pytest.raises(ValueError, match="explicit tenant header"):
        getattr(body, "__func__", body)(SimpleNamespace(request=SimpleNamespace(headers={})), "fake", 1)
