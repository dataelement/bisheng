from typing import Union

from fastapi import APIRouter, Depends, Request

from bisheng.api.services.flow import FlowService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.share_link.api.dependencies import header_share_token_parser
from bisheng.share_link.domain.models.share_link import ShareLink

# build router
router = APIRouter(prefix="/flows", tags=["Flows"], dependencies=[Depends(UserPayload.get_login_user)])


@router.get("/{flow_id}")
async def read_flow(
    *,
    flow_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    share_link: Union["ShareLink", None] = Depends(header_share_token_parser),
):
    """Read a flow."""
    return await FlowService.get_one_flow(login_user, flow_id, share_link)


@router.delete("/{flow_id}", status_code=200)
async def delete_flow(
    *,
    request: Request,
    flow_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Delete a flow."""

    return await FlowService.delete_workflow(request, login_user, flow_id)
