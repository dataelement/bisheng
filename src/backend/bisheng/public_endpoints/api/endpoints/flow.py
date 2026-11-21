"""Published workflow detail adapter."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from bisheng.api.services.flow import FlowService
from bisheng.public_endpoints.domain.services.guest_policy import public_execution
from bisheng.public_endpoints.domain.services.public_projection import public_workflow_view

router = APIRouter(prefix="/flows", tags=["PublicAPI", "Workflow"])


@router.get("/{flow_id}", status_code=200)
async def get_flow(request: Request, flow_id: UUID):
    del request
    normalized_id = flow_id.hex
    async with public_execution("workflow", normalized_id) as execution:
        response = await FlowService.get_one_flow(execution.operator, normalized_id)
        # See the note in the assistant adapter: no share endpoint exists here,
        # and a super-admin operator would otherwise report can_share=True.
        return response.model_copy(update={"data": public_workflow_view(response.data)})
