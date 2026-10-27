"""AC-07, AC-08, AC-09, AC-11, AC-12: leased protocol observations."""

import asyncio
from unittest.mock import Mock, patch

from bisheng.eplus.infrastructure.metric_events import ConnectionMetricObserver


def test_only_authenticated_and_successful_heartbeats_extend_liveness():
    lease = Mock()
    observer = ConnectionMetricObserver(tenant_id=1, bot_id="bot", bot_config_id=3, lease=lease)
    fields = {"server_unix_ms": 1000, "connection_id": "c"}
    with patch("bisheng.eplus.infrastructure.metric_events.emit_metric") as emit:
        observer("connection.opening", fields)
        assert emit.call_args.kwargs["expires_at_ms"] is None
        observer("subscription.authenticated", fields)
        assert emit.call_args.kwargs["expires_at_ms"] == 91000
        observer("heartbeat.failed", fields)
        assert emit.call_args.kwargs["expires_at_ms"] is None
        observer("heartbeat.ok", fields)
        assert emit.call_args.kwargs["event_seq"] == 4
        observer("connection.ended", fields | {"reason": "stop"})
        assert emit.call_args.kwargs["event"] == "closed"
        assert emit.call_args.kwargs["expires_at_ms"] is None
        assert lease.ensure_owned.call_count == 2
        before = emit.call_count
        observer("heartbeat.ok", fields)
        assert emit.call_count == before


def test_lost_lease_never_reports_alive():
    lease = Mock()
    lease.ensure_owned.side_effect = RuntimeError("lost")
    observer = ConnectionMetricObserver(tenant_id=1, bot_id="bot", bot_config_id=3, lease=lease)
    with patch("bisheng.eplus.infrastructure.metric_events.emit_metric") as emit:
        observer("heartbeat.ok", {"server_unix_ms": 1000, "connection_id": "c"})
        emit.assert_not_called()


async def test_diagnostic_setup_and_retry_failure_cannot_stop_reconnection():
    from bisheng.eplus.domain.models.eplus import EPlusConnectionStatus
    from bisheng.eplus.infrastructure.connection_client import EPlusConnectionExitReason
    from test.eplus.test_eplus_connection_supervisor import (
        FakeClientFactory,
        FakeLeaseRegistry,
        FakeTargetProvider,
        _eventually,
        _supervisor,
        _target,
    )

    provider = FakeTargetProvider(_target())
    factory = FakeClientFactory([EPlusConnectionExitReason.DISCONNECTED])
    supervisor = _supervisor(
        provider,
        factory,
        FakeLeaseRegistry(),
        connection_observer_factory=lambda target, lease: object(),
        backoff_waiter=lambda delay, wake: asyncio.sleep(0),
    )
    try:
        await supervisor.start()
        await _eventually(lambda: len(factory.clients) >= 2)
        await _eventually(lambda: EPlusConnectionStatus.AUTHENTICATED in provider.statuses)
        assert EPlusConnectionStatus.ERROR not in provider.statuses
    finally:
        await supervisor.stop()


async def test_rejected_protocol_authentication_reports_closed_without_alive():
    import json

    import pytest
    from websockets.asyncio.server import serve

    from bisheng.eplus.infrastructure.connection_client import (
        EPlusConnectionClient,
        EPlusConnectionConfig,
        EPlusSubscriptionError,
    )

    async def reject(websocket):
        subscribe = json.loads(await websocket.recv())
        await websocket.send(json.dumps({"headers": subscribe["headers"], "errcode": 40013}))
        await websocket.wait_closed()

    observer = ConnectionMetricObserver(tenant_id=1, bot_id="bot", bot_config_id=3, lease=Mock())
    with patch("bisheng.eplus.infrastructure.metric_events.emit_metric") as emit:
        async with serve(reject, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = EPlusConnectionClient(
                EPlusConnectionConfig(url=f"ws://127.0.0.1:{port}", bot_id="bot", secret="fixture"),
                event_sink=observer,
            )
            with pytest.raises(EPlusSubscriptionError):
                await client.run_connection_once()
        events = [call.kwargs for call in emit.call_args_list]
        assert [value["event"] for value in events] == ["opening", "auth_failed", "closed"]
        assert all(value["expires_at_ms"] is None for value in events)
        assert len({value["connection_id"] for value in events}) == 1
