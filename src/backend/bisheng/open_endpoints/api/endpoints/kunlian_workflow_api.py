"""正式昆联 Workflow 接口: 统一 Key 与 Query 用户依赖。"""

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from bisheng.common.schemas.api import resp_200
from bisheng.open_api.application.kunlian_http import KunlianApiRoute, get_kunlian_request_user, kunlian_capability
from bisheng.workflow.application.kunlian_runtime import get_kunlian_runtime_service, run_subject_from_request
from bisheng.workflow.application.kunlian_workflow_api import KunlianWorkflowApi
from bisheng.workflow.application.kunlian_workflow_authorization import GrantChange
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import InteractionAnswer, RunRequest

router = APIRouter(prefix="/api/v2/kunlian", route_class=KunlianApiRoute, tags=["Kunlian Workflow"])
# Internal operation references remain unique per HTTP request, never caller-controlled.


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowCreate(Contract):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    data: dict | None = None
    logo: str | None = None


class WorkflowMetadata(Contract):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    logo: str | None = None


class VersionWrite(Contract):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    data: dict | None = None
    original_version_id: int | None = Field(default=None, gt=0)


class VersionSelection(Contract):
    version_id: int = Field(gt=0)


class GrantBody(Contract):
    expected_resource_version: int = Field(ge=0)
    expected_catalog_release_id: int = Field(gt=0)
    subject_ref: str = Field(min_length=1, max_length=128)
    model_key: str = Field(min_length=1, max_length=128)


class RevokeBody(Contract):
    expected_resource_version: int = Field(ge=0)
    expected_catalog_release_id: int = Field(gt=0)
    expected_assignee_version: int = Field(ge=0)


def management_response(result):
    """Keep Owner codes, normalize raw records, and never report an error as HTTP 200."""
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse

    from bisheng.common.errcode.flow import (
        NotFoundVersionError,
        VersionNameExistsError,
        WorkFlowOnlineEditError,
    )

    if hasattr(result, "status_code") and hasattr(result, "data"):
        code = result.status_code
    elif isinstance(result, dict) and {"status_code", "status_message"} <= result.keys():
        code = result["status_code"]
    else:
        return resp_200(result)
    if code == 200:
        return result
    status = {
        NotFoundVersionError.Code: 404,
        VersionNameExistsError.Code: 409,
        WorkFlowOnlineEditError.Code: 409,
    }.get(code, 400)
    return JSONResponse(status_code=status, content=jsonable_encoder(result))


def grant_response(result):
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse

    status = result.get("status") if isinstance(result, dict) else getattr(result, "status", None)
    return JSONResponse(status_code=202 if status == "PENDING" else 200, content=jsonable_encoder(resp_200(result)))


def management(request: Request):
    return getattr(request.app.state, "kunlian_workflow_api", None) or KunlianWorkflowApi()


@router.get("/workflows")
@kunlian_capability("read")
async def workflows(
    request: Request,
    access=Depends(get_kunlian_request_user),
    name: str | None = None,
    cursor: str | None = None,
    page_size: int = Query(20, ge=1, le=100),
):
    return resp_200(await management(request).list(access.user, name=name, cursor=cursor, page_size=page_size))


@router.post("/workflows", status_code=201)
@kunlian_capability("write")
async def create(request: Request, body: WorkflowCreate, access=Depends(get_kunlian_request_user)):
    from bisheng.workflow.domain.schemas.kunlian_workflow_api import workflow_create_dto

    scoped_key = uuid4().hex
    return resp_200(
        await management(request).create(access.user, request, workflow_create_dto(body.model_dump()), scoped_key)
    )


@router.get("/workflows/{workflow_id}")
@kunlian_capability("read")
async def detail(request: Request, workflow_id: str, for_edit: bool = False, access=Depends(get_kunlian_request_user)):
    return management_response(await management(request).detail(access.user, workflow_id, for_edit=for_edit))


@router.get("/workflows/{workflow_id}/schema")
@kunlian_capability("read")
async def schema(
    request: Request,
    workflow_id: str,
    workflow_version_id: int | None = Query(default=None, gt=0),
    access=Depends(get_kunlian_request_user),
):
    return management_response(
        await management(request).describe(access.user, workflow_id, version_id=workflow_version_id)
    )


@router.patch("/workflows/{workflow_id}")
@kunlian_capability("write")
async def update(request: Request, workflow_id: str, body: WorkflowMetadata, access=Depends(get_kunlian_request_user)):
    return resp_200(
        await management(request).update(access.user, request, workflow_id, body.model_dump(exclude_unset=True))
    )


@router.get("/workflows/{workflow_id}/versions")
@kunlian_capability("read")
async def versions(request: Request, workflow_id: str, access=Depends(get_kunlian_request_user)):
    return management_response(await management(request).versions(access.user, workflow_id))


@router.post("/workflows/{workflow_id}/versions")
@kunlian_capability("write")
async def create_version(
    request: Request, workflow_id: str, body: VersionWrite, access=Depends(get_kunlian_request_user)
):
    from bisheng.workflow.domain.schemas.kunlian_workflow_api import version_dto

    return management_response(
        await management(request).create_version(access.user, workflow_id, version_dto(body.model_dump()))
    )


@router.get("/workflows/{workflow_id}/versions/{version_id}")
@kunlian_capability("read")
async def version(request: Request, workflow_id: str, version_id: int, access=Depends(get_kunlian_request_user)):
    return management_response(await management(request).version(access.user, workflow_id, version_id))


@router.put("/workflows/{workflow_id}/versions/{version_id}")
@kunlian_capability("write")
async def save_version(
    request: Request, workflow_id: str, version_id: int, body: VersionWrite, access=Depends(get_kunlian_request_user)
):
    from bisheng.workflow.domain.schemas.kunlian_workflow_api import version_dto

    return management_response(
        await management(request).save_version(
            access.user, request, workflow_id, version_id, version_dto(body.model_dump())
        )
    )


@router.post("/workflows/{workflow_id}/versions/{version_id}/select")
@kunlian_capability("write")
async def select_version(request: Request, workflow_id: str, version_id: int, access=Depends(get_kunlian_request_user)):
    return management_response(await management(request).select_version(access.user, request, workflow_id, version_id))


@router.post("/workflows/{workflow_id}/publish")
@kunlian_capability("publish")
async def publish(request: Request, workflow_id: str, body: VersionSelection, access=Depends(get_kunlian_request_user)):
    await management(request).publish(access.user, workflow_id, body.version_id, online=True)
    return resp_200()


@router.post("/workflows/{workflow_id}/unpublish")
@kunlian_capability("publish")
async def unpublish(
    request: Request, workflow_id: str, body: VersionSelection, access=Depends(get_kunlian_request_user)
):
    await management(request).publish(access.user, workflow_id, body.version_id, online=False)
    return resp_200()


async def permission_api(request):
    from bisheng.workflow.application.kunlian_permission_api import get_kunlian_permission_api

    return await get_kunlian_permission_api(request.app)


@router.get("/workflows/{workflow_id}/permissions")
@kunlian_capability("grant")
async def permissions(
    request: Request,
    workflow_id: str,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    access=Depends(get_kunlian_request_user),
):
    return resp_200(await (await permission_api(request)).list_grants(access, workflow_id, cursor=cursor, limit=limit))


@router.get("/workflows/{workflow_id}/my-permissions")
@kunlian_capability("read")
async def my_permissions(request: Request, workflow_id: str, access=Depends(get_kunlian_request_user)):
    return resp_200(await (await permission_api(request)).my_permissions(access, workflow_id))


@router.post("/workflows/{workflow_id}/permissions/grants")
@kunlian_capability("grant")
async def grant(request: Request, workflow_id: str, body: GrantBody, access=Depends(get_kunlian_request_user)):
    return grant_response(
        await (await permission_api(request)).change(access, workflow_id, GrantChange(**body.model_dump()), uuid4().hex)
    )


@router.post("/workflows/{workflow_id}/permissions/grants/{assignee_id}/revoke")
@kunlian_capability("grant")
async def revoke(
    request: Request,
    workflow_id: str,
    assignee_id: Annotated[str, Path(pattern=r"^[1-9][0-9]{0,18}$")],
    body: RevokeBody,
    access=Depends(get_kunlian_request_user),
):
    return grant_response(
        await (await permission_api(request)).change(
            access, workflow_id, GrantChange(assignee_id=assignee_id, **body.model_dump()), uuid4().hex
        )
    )


@router.post("/workflow-runs", status_code=202)
@kunlian_capability("invoke")
async def submit(request: Request, body: RunRequest, response: Response, access=Depends(get_kunlian_request_user)):
    row, created = await (await get_kunlian_runtime_service(request.app)).submit(
        run_subject_from_request(access), uuid4().hex, body
    )
    response.status_code = 202 if created else 200
    return resp_200(
        {
            "session_id": row.session_id,
            "workflow_id": row.workflow_id,
            "workflow_version_id": str(row.workflow_version_id),
            "status": row.status,
        }
    )


@router.get("/workflow-runs/{session_id}")
@kunlian_capability("invoke")
async def query(request: Request, session_id: str, access=Depends(get_kunlian_request_user)):
    row = await (await get_kunlian_runtime_service(request.app)).query(run_subject_from_request(access), session_id)
    data = {"session_id": row.session_id, "workflow_version_id": str(row.workflow_version_id), "status": row.status}
    if row.status == "SUCCEEDED":
        data["output"] = row.output
    elif row.status == "FAILED":
        safe_failures = {
            "QUEUE_TIMEOUT",
            "EXECUTION_TIMEOUT",
            "INPUT_TIMEOUT",
            "RESUME_QUEUE_TIMEOUT",
            "RESUME_EXECUTION_TIMEOUT",
            "EXECUTION_FAILED",
            "INVALID_OUTPUT",
            "FORBIDDEN",
            "RESUME_STATE_INVALID",
        }
        data["error"] = row.error if row.error in safe_failures else "EXECUTION_FAILED"
    elif row.status == "WAITING_INPUT":
        data.update(
            interaction_id=row.material["interaction_id"], form=row.material["input_schema"], expires_at=row.deadline_at
        )
    return resp_200(data)


@router.post("/workflow-runs/{session_id}/cancel", status_code=202)
@kunlian_capability("invoke")
async def cancel(request: Request, session_id: str, response: Response, access=Depends(get_kunlian_request_user)):
    row = await (await get_kunlian_runtime_service(request.app)).cancel(run_subject_from_request(access), session_id)
    response.status_code = 202 if row.status == "CANCEL_REQUESTED" else 200
    return resp_200(
        {
            "session_id": row.session_id,
            "status": row.status,
            "cancel_state": {"CANCEL_REQUESTED": "ACCEPTED", "CANCELLED": "CONFIRMED"}.get(
                row.status, "ALREADY_TERMINAL"
            ),
        }
    )


@router.post("/workflow-runs/{session_id}/interactions/{interaction_id}/submit", status_code=202)
@kunlian_capability("invoke")
async def answer(
    request: Request,
    session_id: str,
    interaction_id: str,
    body: InteractionAnswer,
    response: Response,
    access=Depends(get_kunlian_request_user),
):
    receipt, created = await (await get_kunlian_runtime_service(request.app)).answer(
        run_subject_from_request(access), session_id, interaction_id, uuid4().hex, body
    )
    response.status_code = 202 if created else 200
    return resp_200(receipt)
