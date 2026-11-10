"""仅供隔离测试装配的昆联 Workflow 授权入口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from bisheng.common.errcode.permission import (
    PermissionCheckFailedError,
    PermissionDeniedError,
    PermissionInvalidResourceError,
    PermissionPublishNotReadyError,
    PermissionServiceUnavailableError,
    PermissionVersionConflictError,
)
from bisheng.common.schemas.api import resp_200, resp_500
from bisheng.workflow.application.kunlian_workflow_authorization import AuthorizationError, GrantChange

_STATUS = {
    "UNAUTHENTICATED": 401,
    "NOT_FOUND": 404,
    "REVISION_CONFLICT": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "INVALID_INPUT": 422,
    "UNAVAILABLE": 503,
}
_NO_STORE = {"Cache-Control": "no-store"}


def _error(category):
    status = _STATUS[category]
    return JSONResponse(resp_500(code=status, message=category).model_dump(), status_code=status, headers=_NO_STORE)


class _CandidateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                response = await handler(request)
            except RequestValidationError:
                return _error("INVALID_INPUT")
            except AuthorizationError as error:
                return _error(str(error))
            except (PermissionDeniedError, PermissionInvalidResourceError):
                return _error("NOT_FOUND")
            except PermissionVersionConflictError:
                return _error("REVISION_CONFLICT")
            except (
                PermissionCheckFailedError,
                PermissionPublishNotReadyError,
                PermissionServiceUnavailableError,
                SQLAlchemyError,
            ):
                return _error("UNAVAILABLE")
            response.headers.update(_NO_STORE)
            return response

        return safe_handler


router = APIRouter(prefix="/__mock__/kunlian/workflows", route_class=_CandidateRoute)
WorkflowId = Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")]
AssigneeId = Annotated[str, Path(pattern=r"^[1-9][0-9]{0,19}$")]
ClientKey = Annotated[str, Header(alias="Idempotency-Key", pattern=r"^[!-~]{1,64}$")]


class _RevisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_resource_version: int = Field(ge=0, le=2**63 - 1)
    expected_catalog_release_id: int = Field(gt=0, le=2**63 - 1)


class _GrantBody(_RevisionBody):
    subject_ref: str = Field(min_length=1, max_length=128)
    model_key: str = Field(min_length=1, max_length=64)


class _RevokeBody(_RevisionBody):
    expected_assignee_version: int = Field(ge=0, le=2**63 - 1)


def authorization_subject():
    # TODO [F128][EXT-01] 正式开放平台准入及实际用户委托。
    raise AuthorizationError("UNAUTHENTICATED")


def authorization_service():
    raise AuthorizationError("UNAVAILABLE")


@router.get("/{workflow_id}/permissions")
async def list_grants(
    workflow_id: WorkflowId,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    subject=Depends(authorization_subject),
    service=Depends(authorization_service),
):
    return resp_200(data=await service.list_grants(subject, workflow_id, cursor=cursor, limit=limit))


@router.get("/{workflow_id}/my-permissions")
async def my_permissions(
    workflow_id: WorkflowId, subject=Depends(authorization_subject), service=Depends(authorization_service)
):
    return resp_200(data=await service.my_permissions(subject, workflow_id))


def _change_response(response, data):
    response.status_code = 202 if data["status"] == "PENDING" else 200
    return resp_200(data=data)


@router.post("/{workflow_id}/permissions/grants")
async def grant(
    workflow_id: WorkflowId,
    body: _GrantBody,
    response: Response,
    key: ClientKey,
    subject=Depends(authorization_subject),
    service=Depends(authorization_service),
):
    # TODO [F128][EXT-02] 使用已确认的昆联自然人与角色模型映射。
    # TODO [F128][EXT-04] 根据正式 OpenAPI 和测试身份完成联调。
    data = await service.change(subject, workflow_id, GrantChange(**body.model_dump()), key)
    return _change_response(response, data)


@router.post("/{workflow_id}/permissions/grants/{assignee_id}/revoke")
async def revoke(
    workflow_id: WorkflowId,
    assignee_id: AssigneeId,
    body: _RevokeBody,
    response: Response,
    key: ClientKey,
    subject=Depends(authorization_subject),
    service=Depends(authorization_service),
):
    data = await service.change(subject, workflow_id, GrantChange(assignee_id=assignee_id, **body.model_dump()), key)
    return _change_response(response, data)
