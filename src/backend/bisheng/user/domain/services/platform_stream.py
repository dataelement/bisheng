"""Bounded revalidation for established HTTP streams and WebSockets."""

import asyncio
import json
from contextlib import suppress
from time import monotonic

from bisheng.common.errcode.platform_auth import PlatformAuthError


async def run_platform_guarded(app, scope, receive, send, *, service, reference, interval=3.0, budget=2.0):
    """No output follows a failed authoritative check; idle streams also stop."""
    checked_at = monotonic()
    failure = None
    started = False
    completed = False
    event_stream = False
    gate = asyncio.Lock()

    async def validate():
        nonlocal checked_at, failure
        async with gate:
            if failure:
                raise failure
            try:
                await asyncio.wait_for(service.validate_reference(reference), timeout=budget)
                checked_at = monotonic()
            except TimeoutError as exc:
                failure = PlatformAuthError("auth_service_unavailable")
                raise failure from exc
            except PlatformAuthError as exc:
                failure = exc
                raise

    async def guarded_send(message):
        nonlocal started, completed, event_stream
        if failure:
            raise failure
        if (
            message["type"] in {"http.response.start", "http.response.body", "websocket.accept", "websocket.send"}
            and monotonic() - checked_at >= interval
        ):
            await validate()
        if message["type"] == "http.response.start":
            started = True
            event_stream = any(
                k.lower() == b"content-type" and b"text/event-stream" in v for k, v in message.get("headers", [])
            )
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            completed = True
        if message["type"] == "websocket.close":
            completed = True
        await send(message)

    async def watch():
        while True:
            await asyncio.sleep(interval)
            await validate()

    async def guarded_receive():
        message = await receive()
        if message["type"] == "websocket.receive":
            await validate()  # New messages never spend a cached identity grant.
        return message

    application = asyncio.create_task(app(scope, guarded_receive, guarded_send))
    watcher = asyncio.create_task(watch())
    try:
        done, _ = await asyncio.wait({application, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if application in done:
            return await application
        await watcher
    except PlatformAuthError as exc:
        application.cancel()
        with suppress(asyncio.CancelledError, PlatformAuthError):
            await application
        if not completed:
            if scope["type"] == "websocket":
                await send(
                    {"type": "websocket.close", "code": 1013 if exc.http_status == 503 else 1008, "reason": exc.reason}
                )
            elif started:
                body = ("event: error\ndata: " + json.dumps(exc.payload()) + "\n\n").encode() if event_stream else b""
                await send({"type": "http.response.body", "body": body, "more_body": False})
            else:
                from starlette.responses import JSONResponse

                await JSONResponse(exc.payload(), status_code=exc.http_status, headers={"Cache-Control": "no-store"})(
                    scope, receive, send
                )
    finally:
        watcher.cancel()
        if not application.done():
            application.cancel()
        with suppress(asyncio.CancelledError, PlatformAuthError):
            await watcher
        with suppress(asyncio.CancelledError, PlatformAuthError):
            await application
