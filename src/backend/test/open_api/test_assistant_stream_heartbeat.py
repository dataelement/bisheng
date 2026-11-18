import asyncio

import pytest

from bisheng.open_endpoints.domain.streaming import stream_with_heartbeat


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


async def test_stream_with_heartbeat_emits_ping_while_source_is_idle():
    async def source():
        await asyncio.sleep(0.03)
        yield "data: chunk\n\n"

    stream = stream_with_heartbeat(ConnectedRequest(), source(), heartbeat_seconds=0.01)

    assert await anext(stream) == ": ping\n\n"
    assert await anext(stream) == ": ping\n\n"
    assert await anext(stream) == "data: chunk\n\n"


async def test_stream_with_heartbeat_forwards_source_error():
    async def source():
        yield "data: chunk\n\n"
        raise RuntimeError("stream failed")

    stream = stream_with_heartbeat(ConnectedRequest(), source(), heartbeat_seconds=1)

    assert await anext(stream) == "data: chunk\n\n"
    with pytest.raises(RuntimeError, match="stream failed"):
        await anext(stream)


async def test_stream_with_heartbeat_supports_protocol_compatible_custom_event():
    async def source():
        await asyncio.sleep(0.02)
        yield "data: chunk\n\n"

    heartbeat = 'data: {"choices":[{"delta":{"content":""}}]}\n\n'
    stream = stream_with_heartbeat(ConnectedRequest(), source(), heartbeat_seconds=0.01, heartbeat_event=heartbeat)

    assert await anext(stream) == heartbeat


async def test_stream_with_heartbeat_stops_when_client_disconnects():
    class DisconnectedRequest:
        async def is_disconnected(self) -> bool:
            return True

    async def source():
        await asyncio.sleep(60)
        yield "unreachable"

    events = [event async for event in stream_with_heartbeat(DisconnectedRequest(), source(), 0.01)]

    assert events == []
