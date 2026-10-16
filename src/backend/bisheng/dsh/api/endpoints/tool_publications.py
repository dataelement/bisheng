"""Browser tenant administrators manage saved-tool publications."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.dsh import DshToolArgumentsInvalidError
from bisheng.common.schemas.api import resp_200
from bisheng.dsh.api.dependencies import get_runtime
from bisheng.dsh.api.responses import PublishedToolRoute
from bisheng.dsh.api.tool_bodies import read_tool_body
from bisheng.dsh.domain.schemas.tool_publications import ToolCode, ToolLimits, ToolPublicationInput
from bisheng.dsh.tool_runtime import get_tool_service

router = APIRouter(
    prefix="/dsh/admin/tool-publications", route_class=PublishedToolRoute, dependencies=[Depends(get_runtime)]
)
admin_user = UserPayload.get_tenant_admin_user
publication_schema = ToolPublicationInput.model_json_schema()
publication_schema["properties"]["limits"] = ToolLimits.model_json_schema()
publication_schema.pop("$defs", None)


@router.get("")
async def list_publications(
    request: Request,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    user=Depends(admin_user),
    service=Depends(get_tool_service),
):
    if set(request.query_params) - {"offset", "limit"}:
        raise DshToolArgumentsInvalidError()
    return resp_200(data=await service.list(user, offset, limit))


@router.get("/{toolCode}")
async def get_publication(
    toolCode: ToolCode, request: Request, user=Depends(admin_user), service=Depends(get_tool_service)
):
    if request.query_params:
        raise DshToolArgumentsInvalidError()
    return resp_200(data=await service.get(user, toolCode))


@router.put(
    "/{toolCode}",
    openapi_extra={"requestBody": {"required": True, "content": {"application/json": {"schema": publication_schema}}}},
)
async def put_publication(
    toolCode: ToolCode,
    request: Request,
    user=Depends(admin_user),
    service=Depends(get_tool_service),
):
    if request.query_params:
        raise DshToolArgumentsInvalidError()
    body, _ = await read_tool_body(request, 16384, ToolPublicationInput)
    return resp_200(data=await service.put(user, toolCode, body))
