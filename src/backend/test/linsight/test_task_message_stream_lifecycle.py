"""A completed task converges even when its terminal notification was missed."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocketDisconnect, WebSocketState

from bisheng.linsight.domain.services import message_stream_handle as stream


@pytest.fixture
def handler(monkeypatch):
    ws = SimpleNamespace(
        accept=AsyncMock(),
        close=AsyncMock(),
        send_json=AsyncMock(),
        client_state=WebSocketState.CONNECTED,
        application_state=WebSocketState.CONNECTED,
    )

    async def receive_text():
        await asyncio.Event().wait()

    ws.receive_text = receive_text
    monkeypatch.setattr(stream, "LinsightStateMessageManager", lambda **_: SimpleNamespace())
    monkeypatch.setattr(stream.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=None))
    return stream.MessageStreamHandle(ws, "version-1"), ws


def attach_stream(handler, frames):
    closed = asyncio.Event()

    @asynccontextmanager
    async def subscription():
        async def messages():
            for frame in frames:
                yield frame
            await asyncio.Event().wait()

        try:
            yield messages()
        finally:
            closed.set()

    handler._state_message_manager.message_stream = subscription
    return closed


@pytest.mark.parametrize(
    "status,event",
    [
        ("completed", "final_result"),
        ("terminated", "task_terminated"),
        ("failed", "error_message"),
        ("sop_generation_failed", "error_message"),
    ],
)
async def test_persisted_terminal_state_completes_a_quiet_socket(handler, monkeypatch, status, event):
    subject, ws = handler
    closed = attach_stream(subject, [None])
    stream.LinsightSessionVersionDao.get_by_id.return_value = SimpleNamespace(
        status=status,
        output_result={"answer": "complete", "final_files": [{"file_name": "report.docx"}]},
    )
    await asyncio.wait_for(subject.connect(), timeout=1)
    assert ws.send_json.call_args.args[0]["event_type"] == event
    ws.close.assert_awaited_once_with(code=1000, reason="Session finished")
    assert closed.is_set()
    if status == "completed":
        assert ws.send_json.call_args.args[0]["data"]["output_result"]["final_files"][0]["file_name"] == "report.docx"


async def test_running_session_preserves_live_events_and_waits_for_completion(handler):
    subject, ws = handler
    closed = attach_stream(
        subject,
        [
            {"event_type": "task_generate", "data": {"tasks": [{"id": "one"}]}},
            {"event_type": "final_result", "data": {"output_result": {"answer": "done"}}},
        ],
    )
    stream.LinsightSessionVersionDao.get_by_id.return_value = SimpleNamespace(status="in_progress")
    await asyncio.wait_for(subject.connect(), timeout=1)
    assert [call.args[0]["event_type"] for call in ws.send_json.call_args_list] == ["task_generate", "final_result"]
    assert closed.is_set()


async def test_completion_during_an_existing_connection_is_reconciled(handler, monkeypatch):
    subject, ws = handler
    attach_stream(subject, [None, None])
    monkeypatch.setattr(subject, "TERMINAL_CHECK_INTERVAL", 0)
    stream.LinsightSessionVersionDao.get_by_id.side_effect = [
        SimpleNamespace(status="in_progress"),
        SimpleNamespace(status="completed", output_result={"answer": "done"}),
    ]
    await asyncio.wait_for(subject.connect(), timeout=1)
    assert ws.send_json.call_args.args[0]["event_type"] == "final_result"


async def test_completed_snapshot_preserves_queued_progress_and_final_order(handler):
    subject, ws = handler
    attach_stream(
        subject,
        [
            {"event_type": "task_end", "data": {"id": "last", "status": "success"}},
            {"event_type": "final_result", "data": {"output_result": {"answer": "done"}}},
        ],
    )
    stream.LinsightSessionVersionDao.get_by_id.return_value = SimpleNamespace(
        status="completed", output_result={"answer": "done"}
    )
    await asyncio.wait_for(subject.connect(), timeout=1)
    assert [call.args[0]["event_type"] for call in ws.send_json.call_args_list] == ["task_end", "final_result"]


async def test_disconnect_cancels_a_quiet_stream(handler):
    subject, ws = handler
    closed = attach_stream(subject, [])
    ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect(code=1006))
    await asyncio.wait_for(subject.connect(), timeout=1)
    assert closed.is_set()
    ws.send_json.assert_not_called()


async def test_transport_failure_closes_for_reconnect(handler):
    subject, ws = handler

    @asynccontextmanager
    async def broken():
        raise ConnectionError("Redis unavailable")
        yield

    subject._state_message_manager.message_stream = broken
    await asyncio.wait_for(subject.connect(), timeout=1)
    ws.close.assert_awaited_once_with(code=1011, reason="Task stream unavailable")
