"""Opt-in diagnostic routes. Never mount this router in the production API."""

import asyncio
import json
from contextlib import suppress

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.eplus.domain.schemas.debug import DebugRunRequest
from bisheng.eplus.infrastructure.debug_trace import DebugTrace

RUN_TIMEOUT_SECONDS = 180


def create_debug_router(service_provider, runtime, admission_gate) -> APIRouter:
    router = APIRouter(prefix="/robot-debug/api", tags=["Robot Debug"])

    @router.get("/status")
    async def status(operator=Depends(UserPayload.get_login_user), service=Depends(service_provider)):
        await service.authorization.require_admin(operator)
        return resp_200({"enabled": True})

    @router.get("/assistants/{assistant_id}/context")
    async def context(
        assistant_id: str,
        test_user_id: int | None = Query(default=None, gt=0),
        operator=Depends(UserPayload.get_login_user),
        service=Depends(service_provider),
    ):
        value = await service.context(operator, assistant_id, test_user_id or operator.user_id)
        return resp_200(value.public_view())

    @router.post("/assistants/{assistant_id}/run")
    async def run(
        assistant_id: str,
        body: DebugRunRequest,
        request: Request,
        operator=Depends(UserPayload.get_login_user),
        service=Depends(service_provider),
    ):
        origin = request.headers.get("origin")
        expected_origin = f"{request.url.scheme}://{request.url.netloc}"
        if (origin and origin.rstrip("/") != expected_origin) or request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "debug requires a same-origin request")
        value = await service.context(operator, assistant_id, body.test_user_id)
        trace = DebugTrace()

        async def produce():
            try:
                async with asyncio.timeout(RUN_TIMEOUT_SECONDS):
                    async with admission_gate.acquire():
                        count = 0
                        async for text in runtime.run(value, body, trace):
                            count += len(text)
                            if count > 16000:
                                raise ValueError("debug answer capacity exceeded")
                            trace.emit("answer_delta", {"text": text})
                trace.emit("completed", {"tool_call_count": trace.tool_call_count}, terminal=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Preserve stack locations without provider payloads or local values.
                logger.bind(robot_debug_safe=True).opt(
                    exception=(RuntimeError, RuntimeError(type(exc).__name__), exc.__traceback__)
                ).error("robot debug failed run_id={} error_type={}", trace.run_id, type(exc).__name__)
                trace.emit(
                    "failed",
                    {"error_type": type(exc).__name__, "tool_call_count": trace.tool_call_count},
                    terminal=True,
                )

        async def events():
            producer = asyncio.create_task(produce())
            try:
                while True:
                    event = await trace.queue.get()
                    yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                    if event["type"] in {"completed", "failed"}:
                        break
            finally:
                # Starlette cancels the surrounding AnyIO scope on disconnect.
                # Shield the wait so a second cancellation cannot interrupt Redis release.
                with anyio.move_on_after(5, shield=True) as cleanup:
                    producer.cancel()
                    with suppress(asyncio.CancelledError):
                        await producer
                if cleanup.cancel_called:
                    logger.bind(robot_debug_safe=True).warning(
                        "robot debug cleanup timed out run_id={}; slot expires via TTL", trace.run_id
                    )

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        )

    return router
