"""AC-02, AC-07, AC-08, AC-09: subscription barriers and durable repair."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from bisheng.chat_session.domain.schemas.projects import ProjectActor
from bisheng.chat_session.domain.services import project_events as events


class Subscription:
    def __init__(self):
        self.acknowledged = False
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def subscribe(self, topic):
        self.topic = topic

    async def get_message(self, **kwargs):
        if not self.acknowledged:
            self.acknowledged = True
            return {"type": "subscribe"}
        await asyncio.sleep(0.002)
        return None


def client_with(subscription):
    return type("Client", (), {"async_connection": type("Redis", (), {"pubsub": lambda self: subscription})()})()


async def test_ack_precedes_ready_and_database_heartbeat_repairs_lost_publish(monkeypatch):
    subscription = Subscription()
    monkeypatch.setattr(events, "get_redis_client", AsyncMock(return_value=client_with(subscription)))
    version = "1"

    async def read():
        assert subscription.acknowledged
        return version

    stream = events.project_event_stream(
        ProjectActor(1, 7), read, AsyncMock(return_value=True), AsyncMock(return_value=False), heartbeat_seconds=0.005
    )
    first = await anext(stream)
    assert "event: ready" in first and '"revision": "1"' in first
    version = "3"
    next_frame = await anext(stream)
    assert '"revision": "3"' in next_frame
    assert "event: heartbeat" in next_frame
    await stream.aclose()
    assert subscription.closed


async def test_auth_expiry_closes_subscription(monkeypatch):
    subscription = Subscription()
    monkeypatch.setattr(events, "get_redis_client", AsyncMock(return_value=client_with(subscription)))
    stream = events.project_event_stream(
        ProjectActor(1, 7),
        AsyncMock(return_value="1"),
        AsyncMock(side_effect=[True, False]),
        AsyncMock(return_value=False),
        heartbeat_seconds=0.005,
    )
    assert "event: ready" in await anext(stream)
    assert "event: auth_required" in await anext(stream)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert subscription.closed


async def test_publish_failure_is_visible_and_topic_is_actor_scoped(monkeypatch):
    client = type("Client", (), {"apublish": AsyncMock(side_effect=OSError("offline"))})()
    monkeypatch.setattr(events, "get_redis_client", AsyncMock(return_value=client))
    assert await events.publish_project_change(ProjectActor(2, 7), "9") == "degraded"
    topic, payload = client.apublish.call_args.args
    assert topic != events.project_topic(ProjectActor(1, 7))
    assert json.loads(payload) == {"revision": "9", "reason": "project"}
