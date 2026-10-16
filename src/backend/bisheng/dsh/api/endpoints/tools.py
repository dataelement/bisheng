"""Dedicated DSH credentials precede bounded parsing and saved-tool execution."""

import asyncio

from fastapi import APIRouter, Depends, Request
from loguru import logger
from starlette.requests import ClientDisconnect

from bisheng.common.errcode.dsh import (
    DshToolArgumentsInvalidError,
    DshToolExecutionTimeoutError,
)
from bisheng.dsh.api.dependencies import desktop_principal
from bisheng.dsh.api.responses import ToolInvocationRoute
from bisheng.dsh.api.tool_bodies import read_tool_body
from bisheng.dsh.domain.schemas.tool_invocation import ToolCode, ToolInvocationInput
from bisheng.dsh.domain.services.access import DshPrincipal
from bisheng.dsh.tool_runtime import get_tool_service

router = APIRouter(route_class=ToolInvocationRoute)


async def read_invocation(request, limit=65536):
    if request.query_params:
        raise DshToolArgumentsInvalidError()
    return await read_tool_body(request, limit, ToolInvocationInput)


async def disconnect(request):
    # Body has already been consumed; this task is the sole remaining receiver.
    while True:
        if (await request.receive())["type"] == "http.disconnect":
            return


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
    execution = watcher = None
    observed_execution = False
    started_at = getattr(request.state, "dsh_verified_at", asyncio.get_running_loop().time())
    try:
        async with asyncio.timeout_at(started_at + 60) as deadline:
            limits = service.limits
            deadline.reschedule(started_at + limits.timeout_seconds)
            body, size = await read_invocation(request, limits.max_input_bytes)
            execution = asyncio.create_task(
                service.invoke(principal, toolCode, body.arguments, size, started_at=started_at)
            )
            watcher = asyncio.create_task(disconnect(request))
            done, _ = await asyncio.wait({execution, watcher}, return_when=asyncio.FIRST_COMPLETED)
            if execution in done:
                observed_execution = True
                return await execution
            raise ClientDisconnect()
    except TimeoutError:
        raise DshToolExecutionTimeoutError() from None
    finally:
        for task in (execution, watcher):
            if task is not None and not task.done():
                task.cancel()
        if execution is not None or watcher is not None:
            tasks = [task for task in (execution, watcher) if task is not None]
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            for task, outcome in zip(tasks, outcomes, strict=True):
                if not isinstance(outcome, BaseException) or isinstance(outcome, asyncio.CancelledError):
                    continue
                if task is watcher:
                    raise outcome
                if not observed_execution:
                    # The client has left or timed out; retain safe failure evidence.
                    logger.warning("Tool cancelled execution ended type={}", type(outcome).__name__)
