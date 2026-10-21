"""v2 wakeup API. The request carries no executable code, paths or application env."""

from __future__ import annotations

import asyncio
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from runtime_manager.config import get_config
from runtime_manager.operations import OperationExecutor
from runtime_manager.platform_protocol import ProtocolRejected, authenticate

router = APIRouter(prefix="/v2", tags=["platform operations"])


@lru_cache(maxsize=1)
def executor():
    return OperationExecutor(get_config())


async def authorized(request: Request):
    config = get_config()
    if config.protocol_version != 2 and not request.url.path.startswith("/v2/upgrade/"):
        raise HTTPException(404)
    # Inbound platform identity is separate from this node's outbound identity.
    keys = {config.inbound_key_id: {"secret": config.inbound_secret, "roles": ["platform"], "node_id": config.node_id}}
    body = await request.body()
    if len(body) > 65536:
        raise HTTPException(413)

    async def consume(key, ttl):
        return await asyncio.to_thread(executor().platform.nonce, key, ttl)

    try:
        return await authenticate(
            request.method, str(request.url), body, request.headers, keys, consume, required_role="platform"
        )
    except ProtocolRejected as exc:
        raise HTTPException(403, detail={"reason": str(exc)}) from None


class Wakeup(BaseModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,36}$")


@router.post("/operations", status_code=202, dependencies=[Depends(authorized)])
async def wakeup(body: Wakeup):
    operation = await asyncio.to_thread(executor().submit, body.operation_id)
    return {"operation_id": operation["operation_id"], "status": operation["status"]}
