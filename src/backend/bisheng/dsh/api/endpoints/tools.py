"""Dedicated DSH credentials precede bounded parsing and saved-tool execution."""

import asyncio

from fastapi import APIRouter, Depends, Request
from loguru import logger
from starlette.requests import ClientDisconnect

from bisheng.common.errcode.dsh import DshToolArgumentsInvalidError, DshToolExecutionTimeoutError
from bisheng.dsh.api.dependencies import desktop_principal
from bisheng.dsh.api.responses import ToolInvocationRoute
from bisheng.dsh.api.tool_bodies import read_tool_body
from bisheng.dsh.domain.schemas.tool_invocation import ToolCode, ToolInvocationInput
from bisheng.dsh.domain.services.access import DshPrincipal
from bisheng.dsh.tool_runtime import get_tool_service

router = APIRouter(route_class=ToolInvocationRoute)


async def _wait_disconnect(request):
    # The body has already been consumed; this task is the sole remaining receiver.
    while (await request.receive())["type"] != "http.disconnect":
        pass


async def _run_until_disconnect(request, coro):
    """Return the coroutine's result, or cancel it and raise once the client leaves."""
    execution = asyncio.create_task(coro)
    watcher = asyncio.create_task(_wait_disconnect(request))
    try:
        await asyncio.wait({execution, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if execution.done():
            return execution.result()
        raise ClientDisconnect()
    finally:
        for task in (execution, watcher):
            task.cancel()
        # Await cancellation so the lease release and upstream close complete.
        outcomes = await asyncio.gather(execution, watcher, return_exceptions=True)
        if isinstance(outcomes[1], Exception):
            logger.warning("Tool disconnect watcher failed type={}", type(outcomes[1]).__name__)


@router.post(
    "/dsh/tools/{toolCode}/invoke",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": ToolInvocationInput.model_json_schema()}},
        }
    },
)
async def invoke(
    toolCode: ToolCode,
    request: Request,
    principal: DshPrincipal = Depends(desktop_principal),
    service=Depends(get_tool_service),
):
    if request.query_params:
        raise DshToolArgumentsInvalidError()
    limits = service.limits
    try:
        # One deadline covers body reading, admission and upstream execution.
        async with asyncio.timeout(limits.timeout_seconds):
            body = await read_tool_body(request, limits.max_input_bytes, ToolInvocationInput)
            return await _run_until_disconnect(request, service.invoke(principal, toolCode, body.arguments))
    except TimeoutError:
        raise DshToolExecutionTimeoutError() from None
