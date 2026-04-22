from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from bisheng.approval.domain.schemas.approval_schema import (
    ApprovalRequestDecisionReq,
    ApprovalRequestListResp,
    DepartmentKnowledgeSpaceApprovalSettings,
)
from bisheng.approval.domain.services.approval_service import ApprovalService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200

router = APIRouter(prefix='/approval', tags=['approval'])


@router.get('/department-knowledge-space/settings/{space_id}')
async def get_department_knowledge_space_approval_settings(
    space_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        settings = await ApprovalService.get_department_knowledge_space_settings(space_id=space_id)
        return resp_200(settings.model_dump())
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.put('/department-knowledge-space/settings/{space_id}')
async def update_department_knowledge_space_approval_settings(
    space_id: int,
    settings: DepartmentKnowledgeSpaceApprovalSettings,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        result = await ApprovalService.update_department_knowledge_space_settings(
            login_user=login_user,
            space_id=space_id,
            settings=settings,
        )
        return resp_200(result.model_dump())
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.get('/requests')
async def list_approval_requests(
    space_id: Optional[int] = Query(default=None),
    statuses: Optional[List[str]] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        data, total = await ApprovalService.list_requests_for_user(
            login_user=login_user,
            space_id=space_id,
            statuses=statuses,
            page=page,
            page_size=page_size,
        )
        return resp_200(ApprovalRequestListResp(data=data, total=total).model_dump())
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.get('/requests/{request_id}')
async def get_approval_request(
    request_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        row = await ApprovalService.get_request_for_user(
            request_id=request_id,
            login_user=login_user,
        )
        return resp_200(ApprovalService._to_resp(row).model_dump())
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.post('/requests/{request_id}/decision')
async def decide_approval_request(
    request_id: int,
    req: ApprovalRequestDecisionReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        row = await ApprovalService.decide_request(
            request_id=request_id,
            operator_user_id=login_user.user_id,
            action=req.action,
            reason=req.reason,
        )
        return resp_200(ApprovalService._to_resp(row).model_dump())
    except BaseErrorCode as e:
        return e.return_resp_instance()
