import asyncio

import pytest

from bisheng.workstation.domain.services.portal_qa_stream import bounded_qa_stream


async def test_heartbeat_does_not_cancel_slow_producer():
    async def source():
        await asyncio.sleep(0.025)
        yield "answer"

    chunks = [c async for c in bounded_qa_stream(source(), timeout=1, heartbeat=0.005)]
    assert chunks[-1] == "answer"
    assert ": keep-alive\n\n" in chunks


async def test_deadline_cancels_child_and_closes_source():
    closed = asyncio.Event()

    async def source():
        try:
            await asyncio.Event().wait()
            yield "never"
        finally:
            closed.set()

    with pytest.raises(asyncio.TimeoutError):
        async for _ in bounded_qa_stream(source(), timeout=0.025, heartbeat=0.005):
            pass
    assert closed.is_set()


async def test_consumer_cancellation_closes_source():
    closed = asyncio.Event()

    async def source():
        try:
            await asyncio.Event().wait()
            yield "never"
        finally:
            closed.set()

    async def consume():
        async for _ in bounded_qa_stream(source(), timeout=10, heartbeat=0.005):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


@pytest.mark.parametrize("cancel", [False, True])
async def test_real_chat_response_heartbeats_during_setup_and_releases_slot(monkeypatch, cancel):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from bisheng.common.services.config_service import settings
    from bisheng.workstation.domain.services import chat_service
    from bisheng.api.v1.schema.chat_schema import APIChatCompletion

    config = SimpleNamespace(
        portal_unified_qa_enabled=True,
        portal_unified_qa_tenant_ids=[7],
        portal_unified_qa_user_ids=[],
        portal_qa_request_timeout_seconds=0.045,
        portal_qa_heartbeat_seconds=0.005,
    )
    monkeypatch.setattr(settings, "async_get_knowledge", AsyncMock(return_value=SimpleNamespace(retrieval=config)))
    monkeypatch.setattr(chat_service.DepartmentFlowService, "resolve_limit_and_dept", AsyncMock(return_value=(1, 99)))
    monkeypatch.setattr(chat_service.DepartmentFlowService, "try_acquire_daily_chat_slot", AsyncMock(return_value=True))
    release = AsyncMock()
    monkeypatch.setattr(chat_service.DepartmentFlowService, "release_daily_chat_slot", release)
    closed = asyncio.Event()

    async def slow_setup(*args):
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    monkeypatch.setattr(chat_service, "_agent_initialize_chat", slow_setup)
    response = await chat_service._agent_stream_chat_completion(
        None,
        APIChatCompletion(clientTimestamp="2026-09-16T12:00:00", model="1", text="q"),
        SimpleNamespace(user_id=42, tenant_id=7),
        portal_context=True,
    )
    chunks = []

    async def consume():
        async for chunk in response.body_iterator:
            chunks.append(chunk)

    task = asyncio.create_task(consume())
    if cancel:
        while not chunks:
            await asyncio.sleep(0.002)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert all("event: error" not in chunk for chunk in chunks)
    else:
        await task
        assert "event: error" in chunks[-1]
    assert ": keep-alive\n\n" in chunks
    assert closed.is_set()
    release.assert_awaited_once_with(99, 42)


async def test_phase_deadline_cancels_work_before_total_deadline():
    import time
    closed = asyncio.Event()
    async def source():
        try:
            await asyncio.Event().wait()
            yield 'never'
        finally:
            closed.set()
    deadline = time.monotonic() + .025
    with pytest.raises(asyncio.TimeoutError):
        async for _ in bounded_qa_stream(source(), timeout=10, heartbeat=.005,
                                        phase_deadline=lambda: deadline):
            pass
    assert closed.is_set()


async def test_asgi_disconnect_cancels_setup_source_and_releases_slot(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from bisheng.common.services.config_service import settings
    from bisheng.workstation.domain.services import chat_service
    from bisheng.api.v1.schema.chat_schema import APIChatCompletion

    config = SimpleNamespace(portal_unified_qa_enabled=True, portal_unified_qa_tenant_ids=[7],
        portal_unified_qa_user_ids=[], portal_qa_request_timeout_seconds=1,
        portal_qa_heartbeat_seconds=.005)
    monkeypatch.setattr(settings, 'async_get_knowledge', AsyncMock(return_value=SimpleNamespace(retrieval=config)))
    monkeypatch.setattr(chat_service.DepartmentFlowService, 'resolve_limit_and_dept', AsyncMock(return_value=(1, 99)))
    monkeypatch.setattr(chat_service.DepartmentFlowService, 'try_acquire_daily_chat_slot', AsyncMock(return_value=True))
    release = AsyncMock()
    monkeypatch.setattr(chat_service.DepartmentFlowService, 'release_daily_chat_slot', release)
    source_closed = asyncio.Event()
    async def slow_setup(*args):
        try:
            await asyncio.Event().wait()
        finally:
            source_closed.set()
    monkeypatch.setattr(chat_service, '_agent_initialize_chat', slow_setup)
    response = await chat_service._agent_stream_chat_completion(None,
        APIChatCompletion(clientTimestamp='2026-09-16T12:00:00', model='1', text='q'),
        SimpleNamespace(user_id=42, tenant_id=7), portal_context=True)
    disconnected = asyncio.Event()
    async def send(message):
        if message.get('type') == 'http.response.body' and message.get('body'):
            disconnected.set()
    async def receive():
        await disconnected.wait()
        return {'type': 'http.disconnect'}
    await asyncio.wait_for(response({'type': 'http', 'asgi': {'spec_version': '2.3'}}, receive, send), 1)
    assert source_closed.is_set()
    release.assert_awaited_once_with(99, 42)
