from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200

router = APIRouter(prefix='/approval', tags=['approval'])


class ApprovalTaskDecisionReq(BaseModel):
    action: str
    comment: str | None = Field(default=None, max_length=2000)


class ApprovalResubmitReq(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class MenuAccessApplyReq(BaseModel):
    menu_key: str
    menu_name: str
    reason: str | None = Field(default=None, max_length=2000)


@router.get('/my-tasks')
async def list_my_tasks(login_user: UserPayload = Depends(UserPayload.get_login_user)):
    data = await ApprovalCenterService.list_my_tasks(
        tenant_id=login_user.tenant_id,
        approver_user_id=login_user.user_id,
    )
    return resp_200(data)


@router.get('/my-tasks/{task_id}')
async def get_my_task_detail(task_id: int, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    data = await ApprovalCenterService.get_task_detail(task_id=task_id, login_user=login_user)
    return resp_200(data)


@router.post('/tasks/{task_id}/decision')
async def decide_task(
    task_id: int,
    req: ApprovalTaskDecisionReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await ApprovalCenterService.decide_task_api(
        task_id=task_id,
        action=req.action,
        operator_user_id=login_user.user_id,
        operator_user_name=login_user.user_name,
        operator_tenant_id=login_user.tenant_id,
        operator_is_admin=login_user.is_admin(),
        comment=req.comment,
    )
    return resp_200(data)


@router.get('/my-requests')
async def list_my_requests(login_user: UserPayload = Depends(UserPayload.get_login_user)):
    data = await ApprovalCenterService.list_my_requests(
        tenant_id=login_user.tenant_id,
        applicant_user_id=login_user.user_id,
    )
    return resp_200(data)


@router.get('/instances/{instance_id}')
async def get_instance_detail(instance_id: int, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    data = await ApprovalCenterService.get_instance_detail(instance_id=instance_id, login_user=login_user)
    return resp_200(data)


@router.post('/instances/{instance_id}/withdraw')
async def withdraw_instance(
    instance_id: int,
    req: ApprovalResubmitReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await ApprovalCenterService.withdraw_instance(
        instance_id=instance_id,
        operator_user_id=login_user.user_id,
        operator_user_name=login_user.user_name,
        reason=req.reason,
    )
    return resp_200(data)


@router.post('/instances/{instance_id}/resubmit')
async def resubmit_instance(
    instance_id: int,
    req: ApprovalResubmitReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await ApprovalCenterService.resubmit_instance(
        instance_id=instance_id,
        operator_user_id=login_user.user_id,
        reason=req.reason,
    )
    return resp_200(data)


@router.post('/menu-access/apply')
async def apply_menu_access(
    req: MenuAccessApplyReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await ApprovalCenterService.apply_menu_access_request(
        login_user=login_user,
        menu_key=req.menu_key,
        menu_name=req.menu_name,
        reason=req.reason,
    )
    return resp_200(data)


@router.post('/menu-access/{instance_id}/revoke-grant')
async def revoke_menu_grant(
    instance_id: int,
    req: ApprovalResubmitReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await ApprovalCenterService.revoke_menu_grant(
        instance_id=instance_id,
        operator_user_id=login_user.user_id,
        reason=req.reason,
    )
    return resp_200(data)
