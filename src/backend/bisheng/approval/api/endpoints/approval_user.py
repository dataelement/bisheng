from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.schemas.approval_center_schema import (
    DepartmentFileViewApplyRequest,
)
from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService
from bisheng.approval.domain.services.department_file_view_approval_service import (
    DepartmentFileViewApprovalService,
)
from bisheng.approval.domain.services.fixed_scenario_provisioner import (
    FixedScenarioProvisioner,
)
from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.domain.repositories.implementations.department_file_view_grant_repository_impl import (
    DepartmentFileViewGrantRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileViewAccessService,
)
from bisheng.utils import get_request_ip

router = APIRouter(prefix='/approval', tags=['approval'])


class ApprovalTaskDecisionReq(BaseModel):
    action: str
    comment: str | None = Field(default=None, max_length=2000)


class ApprovalResubmitReq(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class ApprovalRevokeReq(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class MenuAccessApplyReq(BaseModel):
    menu_key: str
    menu_name: str
    reason: str | None = Field(default=None, max_length=2000)


def _build_department_file_view_service(
    session: AsyncSession,
) -> DepartmentFileViewApprovalService:
    file_repository = KnowledgeFileRepositoryImpl(session)
    grant_repository = DepartmentFileViewGrantRepositoryImpl(session)
    access_service = DepartmentFileViewAccessService(
        session=session,
        grant_repository=grant_repository,
    )
    return DepartmentFileViewApprovalService(
        session=session,
        file_repository=file_repository,
        access_service=access_service,
        provisioner=FixedScenarioProvisioner(session),
    )


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
    request: Request,
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
        ip_address=get_request_ip(request),
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
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await ApprovalCenterService.withdraw_instance(
        instance_id=instance_id,
        operator_user_id=login_user.user_id,
        operator_user_name=login_user.user_name,
        reason=req.reason,
        ip_address=get_request_ip(request),
    )
    return resp_200(data)


@router.get('/menu-access/pending-check')
async def check_menu_access_pending(
    menu_key: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
    business_key = f'menu:{menu_key}:user:{login_user.user_id}'
    duplicate = await ApprovalInstanceRepository.find_duplicate_active_instance(
        tenant_id=login_user.tenant_id,
        scenario_code='menu_access_request',
        business_key=business_key,
        applicant_user_id=login_user.user_id,
    )
    return resp_200({
        'has_pending': duplicate is not None,
        'instance_id': duplicate.id if duplicate else None,
        'status': duplicate.status if duplicate else None,
    })


@router.post('/menu-access/apply')
async def apply_menu_access(
    req: MenuAccessApplyReq,
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await ApprovalCenterService.apply_menu_access_request(
        login_user=login_user,
        menu_key=req.menu_key,
        menu_name=req.menu_name,
        reason=req.reason,
        ip_address=get_request_ip(request),
    )
    return resp_200(data)


@router.post('/menu-access/{instance_id}/revoke-grant')
async def revoke_menu_grant(
    instance_id: int,
    req: ApprovalRevokeReq,
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await ApprovalCenterService.revoke_menu_grant(
        instance_id=instance_id,
        operator_user_id=login_user.user_id,
        operator_user_name=login_user.user_name,
        reason=req.reason,
        ip_address=get_request_ip(request),
    )
    return resp_200(data)


@router.get('/department-file-view/status')
async def get_department_file_view_status(
    space_id: int,
    file_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    session: AsyncSession = Depends(get_db_session),
):
    data = await _build_department_file_view_service(session).status(
        login_user=login_user,
        space_id=space_id,
        file_id=file_id,
    )
    return resp_200(data)


@router.post('/department-file-view/apply')
async def apply_department_file_view(
    req: DepartmentFileViewApplyRequest,
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    session: AsyncSession = Depends(get_db_session),
):
    data = await _build_department_file_view_service(session).apply(
        login_user=login_user,
        space_id=req.space_id,
        file_id=req.file_id,
        reason=req.reason,
        ip_address=get_request_ip(request),
    )
    return resp_200(data)


@router.post('/department-file-view/{instance_id}/revoke-grant')
async def revoke_department_file_view_grant(
    instance_id: int,
    req: ApprovalRevokeReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    session: AsyncSession = Depends(get_db_session),
):
    data = await _build_department_file_view_service(session).revoke(
        login_user=login_user,
        instance_id=instance_id,
        reason=req.reason,
    )
    return resp_200(data)
