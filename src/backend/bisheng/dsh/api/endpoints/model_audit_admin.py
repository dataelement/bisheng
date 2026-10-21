"""Metadata queries and explicit original access within fixed administrator tenant scope."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.dsh_audit import DshAuditQueryInvalidError
from bisheng.common.schemas.api import resp_200
from bisheng.dsh.api.dependencies import get_settings
from bisheng.dsh.audit_admin_runtime import build_audit_administration
from bisheng.dsh.domain.schemas.model_audit import (
    AuditModeCommand,
    ContentStatus,
    ModelResult,
    ResponseResult,
    UsageSettlement,
)
from bisheng.dsh.domain.schemas.model_audit_group import AuditGroupQuery, AuditTreeQuery

router = APIRouter(prefix="/dsh/admin/model-audit")
audit_admin = UserPayload.get_tenant_admin_user
Tenant = Annotated[int | None, Query(gt=0, le=9223372036854775807)]
Cursor = Annotated[str | None, Query(max_length=2048)]
Limit = Annotated[int, Query(ge=1, le=100)]


def get_audit_management(settings=Depends(get_settings)):
    return build_audit_administration(settings)


@router.get("/users")
async def users(
    response: Response,
    tenant_id: Tenant = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Limit = 20,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
    user=Depends(audit_admin),
    service=Depends(get_audit_management),
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data=await service.queries.users(user, tenant_id, page=page, page_size=page_size, keyword=keyword))


@router.get("/models")
async def models(
    response: Response,
    tenant_id: Tenant = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Limit = 20,
    keyword: Annotated[str | None, Query(max_length=2048)] = None,
    user=Depends(audit_admin),
    service=Depends(get_audit_management),
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(
        data=await service.queries.models(user.user_id, tenant_id, page=page, page_size=page_size, keyword=keyword)
    )


@router.get("/requests")
async def requests(
    response: Response,
    user=Depends(audit_admin),
    service=Depends(get_audit_management),
    tenant_id: Tenant = None,
    cursor: Cursor = None,
    limit: Limit = 20,
    user_id: Annotated[int | None, Query(gt=0)] = None,
    request_id: Annotated[str | None, Query(max_length=36)] = None,
    conversation_id: Annotated[str | None, Query(min_length=1, max_length=256)] = None,
    user_keyword: Annotated[str | None, Query(max_length=128)] = None,
    model_id: Annotated[int | None, Query(gt=0, le=9223372036854775807)] = None,
    model_name: Annotated[str | None, Query(max_length=2048)] = None,
    provider_name: Annotated[str | None, Query(max_length=128)] = None,
    model_result: ModelResult | None = None,
    response_result: ResponseResult | None = None,
    usage_settlement: UsageSettlement | None = None,
    content_status: ContentStatus | None = None,
    association_status: Literal["ASSOCIATED", "UNASSOCIATED"] | None = None,
    audit_status: Literal["NORMAL", "ABNORMAL"] | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(
        data=await service.queries.page(
            user.user_id,
            tenant_id,
            cursor=cursor,
            limit=limit,
            user_id=user_id,
            request_id=request_id,
            conversation_id=conversation_id,
            user_keyword=user_keyword,
            model_id=model_id,
            model_name=model_name,
            provider_name=provider_name,
            model_result=model_result,
            response_result=response_result,
            usage_settlement=usage_settlement,
            content_status=content_status,
            association_status=association_status,
            audit_status=audit_status,
            start_at=start_at,
            end_at=end_at,
        )
    )


def strict_group_query(request):
    try:
        if len(request.query_params) != len(list(request.query_params.multi_items())):
            raise ValueError("Duplicate query field")
        return AuditGroupQuery.model_validate(dict(request.query_params))
    except (ValueError, ValidationError):
        raise DshAuditQueryInvalidError() from None


@router.get("/query-readiness")
async def query_readiness(
    response: Response, tenant_id: Tenant = None, user=Depends(audit_admin), service=Depends(get_audit_management)
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data=await service.queries.readiness(user.user_id, tenant_id))


@router.get("/conversation-groups")
async def conversation_groups(
    request: Request, response: Response, user=Depends(audit_admin), service=Depends(get_audit_management)
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data=await service.queries.groups(user.user_id, strict_group_query(request)))


def strict_tree_query(request):
    try:
        if len(request.query_params) != len(list(request.query_params.multi_items())):
            raise ValueError("Duplicate tree query field")
        return AuditTreeQuery.model_validate(dict(request.query_params))
    except (ValueError, ValidationError):
        raise DshAuditQueryInvalidError() from None


@router.get("/conversation-tree")
async def conversation_tree(
    request: Request, response: Response, user=Depends(audit_admin), service=Depends(get_audit_management)
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data=await service.queries.tree(user.user_id, strict_tree_query(request)))


@router.get("/conversation-tree/{key}/children")
async def tree_children(
    key: Annotated[str, Path(pattern="^[0-9a-f]{64}$")],
    request: Request,
    response: Response,
    user=Depends(audit_admin),
    service=Depends(get_audit_management),
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data=await service.queries.tree(user.user_id, strict_tree_query(request), parent_key=key))


@router.get("/conversation-tree/{key}/location")
async def tree_location(
    key: Annotated[str, Path(pattern="^[0-9a-f]{64}$")],
    request: Request,
    response: Response,
    user=Depends(audit_admin),
    service=Depends(get_audit_management),
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data=await service.queries.tree(user.user_id, strict_tree_query(request), location_key=key))


@router.get("/conversation-groups/{key}/requests")
async def group_requests(
    key: Annotated[str, Path(pattern="^[0-9a-f]{64}$")],
    request: Request,
    response: Response,
    user=Depends(audit_admin),
    service=Depends(get_audit_management),
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data=await service.queries.groups(user.user_id, strict_group_query(request), key=key))


@router.get("/conversations")
async def conversations(
    response: Response,
    user_id: Annotated[int, Query(gt=0)],
    conversation_id: Annotated[str, Query(min_length=1, max_length=256)],
    tenant_id: Tenant = None,
    cursor: Cursor = None,
    limit: Limit = 20,
    user=Depends(audit_admin),
    service=Depends(get_audit_management),
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(
        data=await service.queries.page(
            user.user_id, tenant_id, user_id=user_id, conversation_id=conversation_id, cursor=cursor, limit=limit
        )
    )


@router.get("/requests/{request_id}")
async def request_detail(
    request_id: Annotated[str, Path(min_length=1, max_length=36)],
    response: Response,
    tenant_id: Tenant = None,
    user=Depends(audit_admin),
    service=Depends(get_audit_management),
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data=await service.queries.detail(user.user_id, tenant_id, request_id))


@router.get("/requests/{request_id}/parent-conversation")
async def parent_conversation(
    request_id: Annotated[str, Path(min_length=1, max_length=36)],
    response: Response,
    tenant_id: Tenant = None,
    user=Depends(audit_admin),
    service=Depends(get_audit_management),
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data=await service.queries.parent_conversation(user.user_id, tenant_id, request_id))


@router.post("/requests/{request_id}/body-access")
async def body_access(
    request_id: Annotated[str, Path(min_length=1, max_length=36)],
    tenant_id: Tenant = None,
    include_message_sources: bool = False,
    user=Depends(audit_admin),
    service=Depends(get_audit_management),
):
    source = await service.bodies.prepare(
        user.user_id, tenant_id, request_id, include_message_sources=include_message_sources
    )
    return StreamingResponse(
        source,
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Accel-Buffering": "no"},
    )


@router.get("/settings")
async def read_mode(
    response: Response, tenant_id: Tenant = None, user=Depends(audit_admin), service=Depends(get_audit_management)
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data=await service.modes.read_admin(user.user_id, tenant_id))


@router.put("/settings/{tenant_id}")
async def change_mode(
    tenant_id: Annotated[int, Path(gt=0, le=9223372036854775807)],
    body: AuditModeCommand,
    response: Response,
    user=Depends(audit_admin),
    service=Depends(get_audit_management),
):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data=await service.modes.change_admin(user.user_id, tenant_id, body))
