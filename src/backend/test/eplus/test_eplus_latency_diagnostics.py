from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from loguru import logger

from bisheng.eplus.infrastructure import connection_client
from bisheng.eplus.infrastructure.connection_client import EPlusConnectionClient, EPlusConnectionConfig
from bisheng.eplus.infrastructure.protocol import build_stream_frame


@pytest.fixture
def log_records():
    records = []
    sink_id = logger.add(lambda message: records.append(message.record))
    try:
        yield records
    finally:
        logger.remove(sink_id)


async def test_frame_timing_separates_write_from_ack_and_is_visible_in_plain_logs(monkeypatch, log_records):
    clock = SimpleNamespace(value=10.0)
    monkeypatch.setattr(connection_client, "time", SimpleNamespace(monotonic=lambda: clock.value, time=lambda: 100.0))
    events = []
    client = EPlusConnectionClient(
        EPlusConnectionConfig(url="ws://localhost/socket", bot_id="bot", secret="secret-private"),
        event_sink=lambda event, fields: events.append((event, fields)),
    )
    written = asyncio.Event()
    release_ack = asyncio.Event()
    payloads = []

    class WebSocket:
        async def send(self, payload):
            payloads.append(json.loads(payload))
            clock.value = 10.02
            written.set()

        async def __aiter__(self):
            await release_ack.wait()
            clock.value = 10.12
            yield json.dumps({"headers": {"req_id": "request"}, "errcode": 0})

    websocket = WebSocket()
    client._websocket = websocket
    receiving = asyncio.create_task(client._receive_loop(websocket))
    frame = build_stream_frame("request", "stream", "private message body", finish=False)
    sending = asyncio.create_task(client.send_with_ack(frame))
    await written.wait()
    release_ack.set()
    assert (await sending)["errcode"] == 0
    await receiving

    by_event = dict(events)
    assert "frame.written" in by_event, "Missing WebSocket write completion timing"
    assert "frame.acknowledged" in by_event, "Missing platform ACK timing"
    assert by_event["frame.written"]["write_ms"] == pytest.approx(20)
    assert by_event["frame.acknowledged"]["ack_wait_ms"] == pytest.approx(100)
    assert by_event["frame.acknowledged"]["elapsed_ms"] == pytest.approx(120)
    assert by_event["frame.acknowledged"]["server_unix_ms"] == 100000
    assert by_event["frame.written"]["send_seq"] == by_event["frame.acknowledged"]["send_seq"]
    assert by_event["frame.written"]["stream_hash"] == by_event["frame.acknowledged"]["stream_hash"]
    assert payloads == [frame], "Diagnostics must not change protocol frames"
    messages = "\n".join(record["message"] for record in log_records)
    assert "frame.written" in messages and "ack_wait_ms" in messages
    assert "private message body" not in messages
    assert "secret-private" not in messages


async def test_inbound_log_correlates_callback_without_exposing_message_body(log_records):
    events = []
    handled = []
    client = EPlusConnectionClient(
        EPlusConnectionConfig(url="ws://localhost/socket", bot_id="bot", secret="secret-private"),
        on_message=lambda frame: handled.append(frame),
        event_sink=lambda event, fields: events.append((event, fields)),
    )
    frame = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "request"},
        "body": {"msgid": "private-msg-id", "text": {"content": "private user text"}},
    }

    class WebSocket:
        async def __aiter__(self):
            yield json.dumps(frame)

    await client._receive_loop(WebSocket())
    await client._finish_message_tasks()
    inbound = dict(events)["frame.inbound"]
    assert "msgid_hash" in inbound, "Missing callback correlation key"
    assert inbound["msgid_hash"] != "private-msg-id"
    assert inbound["read_mono_ms"] <= inbound["mono_ms"]
    assert inbound["server_unix_ms"] > 0
    assert handled == [frame]
    messages = "\n".join(record["message"] for record in log_records)
    assert "private user text" not in messages and "private-msg-id" not in messages


async def test_loop_monitor_detects_starvation_and_recovers_without_repeated_warning(log_records):
    from bisheng.eplus.infrastructure.latency_diagnostics import EPlusLoopLagMonitor

    clock = SimpleNamespace(value=10.0)
    observed = asyncio.Event()
    calls = 0

    async def sleep(delay):
        nonlocal calls
        calls += 1
        if calls == 1:
            clock.value += delay + 26.0
        elif calls == 2:
            clock.value += delay
        else:
            observed.set()
            await asyncio.Future()

    monitor = EPlusLoopLagMonitor(clock=lambda: clock.value, sleep=sleep)
    monitor.start()
    await observed.wait()
    await monitor.stop()
    lag_records = [r for r in log_records if r["extra"].get("eplus_event") == "event_loop.lag"]
    assert len(lag_records) == 1
    assert lag_records[0]["extra"]["lag_ms"] == pytest.approx(26000)
    assert lag_records[0]["extra"]["window_start_mono_ms"] == 10000
    assert lag_records[0]["extra"]["window_end_mono_ms"] == 37000
    assert all(task.get_name() != "eplus-loop-lag" for task in asyncio.all_tasks())


async def test_loop_monitor_reports_healthy_windows_despite_wall_clock_jump(monkeypatch, log_records):
    from bisheng.eplus.infrastructure import latency_diagnostics

    clock = SimpleNamespace(value=10.0, wall=100.0)
    monkeypatch.setattr(latency_diagnostics, "time", SimpleNamespace(time=lambda: clock.wall))
    observed = asyncio.Event()
    samples = 0

    async def sleep(delay):
        nonlocal samples
        samples += 1
        if samples > 60:
            observed.set()
            await asyncio.Future()
        clock.value += delay
        clock.wall += 1000

    monitor = latency_diagnostics.EPlusLoopLagMonitor(clock=lambda: clock.value, sleep=sleep)
    monitor.start()
    await observed.wait()
    await monitor.stop()
    assert not any(r["extra"].get("eplus_event") == "event_loop.lag" for r in log_records)
    summaries = [r for r in log_records if r["extra"].get("eplus_event") == "event_loop.summary"]
    assert len(summaries) == 1
    assert summaries[0]["extra"]["max_lag_ms"] == 0
    assert summaries[0]["extra"]["samples"] == 60


async def test_send_timeout_has_correlated_failure_diagnostics_and_cleans_pending_ack(log_records):
    events = []
    client = EPlusConnectionClient(
        EPlusConnectionConfig(
            url="ws://localhost/socket", bot_id="bot", secret="secret-private", ack_timeout_seconds=0.01
        ),
        event_sink=lambda event, fields: events.append((event, fields)),
    )

    class WebSocket:
        async def send(self, payload):
            pass

    client._websocket = WebSocket()
    with pytest.raises(TimeoutError):
        await client.send_with_ack(build_stream_frame("request", "stream", "private body", finish=False))
    by_event = dict(events)
    assert by_event["frame.send_failed"]["error_type"] == "TimeoutError"
    assert by_event["frame.send_failed"]["elapsed_ms"] >= 10
    assert by_event["frame.send_failed"]["send_seq"] == by_event["frame.written"]["send_seq"]
    assert "frame.acknowledged" not in by_event
    assert not client._pending_acks and not client._request_gates
