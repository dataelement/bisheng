"""Cross-worker invalidation with a database-version repair path."""

import asyncio
import json

from loguru import logger
from redis import RedisError

from bisheng.chat_session.domain.schemas.projects import ProjectActor
from bisheng.common.schemas.api import SSEResponse
from bisheng.core.cache.redis_manager import get_redis_client, get_redis_client_sync


def project_topic(actor: ProjectActor) -> str:
    return f"chat-projects:{actor.tenant_id}:{actor.user_id}"


async def publish_project_change(actor: ProjectActor, revision: str, reason="project") -> str:
    try:
        client = await get_redis_client()
        async with asyncio.timeout(5):
            await client.apublish(project_topic(actor), json.dumps({"revision": revision, "reason": reason}))
        return "live"
    except (RedisError, OSError, TimeoutError, RuntimeError):
        # SQL already committed. Report transport degradation; every subscriber
        # repairs from SQL on its heartbeat, without replaying the mutation.
        logger.opt(exception=True).warning("project-sync publish failed after commit; revision={}", revision)
        return "degraded"


def publish_project_change_sync(actor: ProjectActor, revision: str, reason="conversation") -> str:
    try:
        get_redis_client_sync().publish(project_topic(actor), json.dumps({"revision": revision, "reason": reason}))
        return "live"
    except (RedisError, OSError, TimeoutError, RuntimeError):
        logger.opt(exception=True).warning("project-sync title publish failed after commit; revision={}", revision)
        return "degraded"


def event_frame(event: str, revision: str, notification="live", reason=None):
    data = {"protocol_version": 1, "revision": revision, "notification": notification}
    if reason in ("project", "membership", "conversation"):
        data["reason"] = reason
    return f"id: {revision}\n" + SSEResponse(event=event, data=data).to_string()


async def project_event_stream(actor, read_version, authenticate, disconnected, *, heartbeat_seconds=15):
    """Callbacks isolate HTTP/auth adapters from the event transport lifecycle."""
    loop = asyncio.get_running_loop()
    revision = "0"
    while not await disconnected():
        if not await authenticate():
            yield event_frame("auth_required", revision)
            return
        try:
            client = await get_redis_client()
            async with client.async_connection.pubsub() as subscription:
                await subscription.subscribe(project_topic(actor))
                async with asyncio.timeout(5):
                    while True:
                        ack = await subscription.get_message(timeout=1)
                        if ack and ack["type"] == "subscribe":
                            break
                # Redis acknowledgement, then SQL: a commit in between is
                # present in either the version read or the queued notification.
                revision = await read_version()
                yield event_frame("ready", revision)
                next_heartbeat = loop.time() + heartbeat_seconds
                while not await disconnected():
                    if loop.time() >= next_heartbeat:
                        if not await authenticate():
                            yield event_frame("auth_required", revision)
                            return
                        revision = await read_version()
                        yield event_frame("heartbeat", revision)
                        next_heartbeat = loop.time() + heartbeat_seconds
                    message = await subscription.get_message(
                        ignore_subscribe_messages=True, timeout=min(1, heartbeat_seconds)
                    )
                    if message and message.get("type") == "message":
                        raw = message.get("data")
                        if not isinstance(raw, (str, bytes)) or len(raw) > 16384:
                            logger.warning("project-sync ignored invalid notification frame")
                            continue
                        try:
                            data = json.loads(raw)
                            incoming = data.get("revision") if isinstance(data, dict) else None
                            if (
                                not isinstance(incoming, str)
                                or not incoming.isascii()
                                or not incoming.isdecimal()
                                or len(incoming) > 20
                            ):
                                raise ValueError("invalid revision")
                        except (ValueError, UnicodeError):
                            logger.warning("project-sync ignored malformed notification")
                            continue
                        if int(incoming) > int(revision):
                            revision = incoming
                            yield event_frame("changed", revision, reason=data.get("reason"))
        except (RedisError, OSError, TimeoutError, RuntimeError):
            logger.opt(exception=True).warning("project-sync subscription unavailable; repairing from SQL")
            if await disconnected():
                return
            if not await authenticate():
                yield event_frame("auth_required", revision)
                return
            revision = await read_version()
            yield event_frame("heartbeat", revision, notification="degraded")
            await asyncio.sleep(heartbeat_seconds)
