from typing import Union

from fastapi import APIRouter, Depends, Request

from bisheng.api.services.flow import FlowService
from bisheng.api.v1.schemas import resp_200
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.services import telemetry_service
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import FlowDao
from bisheng.database.models.role_access import AccessType
from bisheng.permission.domain.services.application_permission_service import ApplicationPermissionService
from bisheng.share_link.api.dependencies import header_share_token_parser
from bisheng.share_link.domain.models.share_link import ShareLink

# build router
router = APIRouter(prefix='/flows', tags=['Flows'], dependencies=[Depends(UserPayload.get_login_user)])


@router.get('/{flow_id}')
async def read_flow(*, flow_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user),
                    share_link: Union['ShareLink', None] = Depends(header_share_token_parser)):
    """Read a flow."""
    return await FlowService.get_one_flow(login_user, flow_id, share_link)


@router.delete('/{flow_id}', status_code=200)
def delete_flow(*,
                request: Request,
                flow_id: str,
                login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """Delete a flow."""

    db_flow = FlowDao.get_flow_by_id(flow_id)
    if not db_flow:
        raise NotFoundError()
    if not ApplicationPermissionService.has_any_permission_sync(
        login_user,
        'workflow',
        str(flow_id),
        ['delete_app'],
    ):
        return UnAuthorizedError.return_resp()
    FlowDao.delete_flow(db_flow)
    telemetry_service.log_event_sync(
        user_id=login_user.user_id,
        event_type=BaseTelemetryTypeEnum.DELETE_APPLICATION,
        trace_id=trace_id_var.get()
    )
    FlowService.delete_flow_hook(request, login_user, db_flow)
    return resp_200()
