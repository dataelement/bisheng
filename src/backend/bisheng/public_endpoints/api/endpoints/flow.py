"""Published workflow detail adapter."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from bisheng.api.services.flow import FlowService
from bisheng.public_endpoints.domain.services.guest_policy import public_execution

router = APIRouter(prefix="/flows", tags=["PublicAPI", "Workflow"])


@router.get("/{flow_id}", status_code=200)
async def get_flow(request: Request, flow_id: UUID):
    del request
    normalized_id = flow_id.hex
    async with public_execution("workflow", normalized_id) as execution:
        return await FlowService.get_one_flow(execution.operator, normalized_id)
