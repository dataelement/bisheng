from typing import Union

from fastapi import APIRouter, Depends, Request

from bisheng.api.services.flow import FlowService
from bisheng.api.v1.schemas import resp_200
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.services import telemetry_service
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import FlowDao
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
async def delete_flow(
    *,
    request: Request,
    flow_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Delete a flow."""

    db_flow = FlowDao.get_flow_by_id(flow_id)
    if not db_flow:
        raise NotFoundError()
    from bisheng.workflow.application.kunlian_workflow_management import workflow_scope

    if scope := workflow_scope(db_flow.tenant_id, flow_id, user=login_user):
        from bisheng.common.errcode.flow import WorkflowRegistrationConflict
        from bisheng.database.models.flow import FlowStatus

        if db_flow.status == FlowStatus.ONLINE.value:
            raise WorkflowRegistrationConflict()
    await FlowService.project_flow_delete(login_user, db_flow)
    if scope:
        from bisheng.workflow.domain.repositories.kunlian_registration import RegistrationRepository

        RegistrationRepository().delete_offline(scope, flow_id)
    else:
        FlowDao.delete_flow(db_flow)
    telemetry_service.log_event_sync(
        user_id=login_user.user_id,
        event_type=BaseTelemetryTypeEnum.DELETE_APPLICATION,
        trace_id=trace_id_var.get()
    )
    FlowService.delete_flow_hook(request, login_user, db_flow)
    return resp_200()
