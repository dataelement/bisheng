"""供 Workflow 编辑器调用的昆联知识库资源接口。"""

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse

from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.flow import (
    PlatformKnowledgeConfigurationError,
    PlatformKnowledgeError,
    PlatformKnowledgeNotReadyError,
    PlatformKnowledgePermissionError,
)
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.workflow.application import platform_knowledge
from bisheng.workflow.domain.schemas.platform_knowledge import KnowledgeContract

router = APIRouter(prefix="/platform-knowledge")


class ValidateRequest(KnowledgeContract):
    workflow_id: str
    graph: dict
    node_id: str | None = None


async def respond(operation):
    try:
        return resp_200(data=await operation())
    except PlatformKnowledgeError as exc:
        error = type(exc)()
    except UnAuthorizedError:
        error = PlatformKnowledgePermissionError()
    except Exception:
        error = PlatformKnowledgeNotReadyError()
    return JSONResponse(error.to_dict(), status_code=error.http_status)


@router.get("")
async def list_knowledge(
    workflow_id: str,
    cursor: str | None = Query(None, max_length=256),
    name: str | None = Query(None, max_length=128),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return await respond(lambda: platform_knowledge.get_service().list_knowledge(login_user, workflow_id, cursor, name))


@router.get("/{resource_id}")
async def get_knowledge(
    resource_id: str, workflow_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user)
):
    return await respond(lambda: platform_knowledge.get_service().get_knowledge(login_user, workflow_id, resource_id))


@router.post("/validate")
async def validate_graph(payload: object = Body(...), login_user: UserPayload = Depends(UserPayload.get_login_user)):
    async def operation():
        try:
            request = ValidateRequest.model_validate(payload)
        except ValueError:
            raise PlatformKnowledgeConfigurationError() from None
        result = await platform_knowledge.get_service().validate_graph(
            login_user,
            request.workflow_id,
            request.graph,
            request.node_id,
        )
        return {"valid": result["valid"], "issues": result["issues"]}

    return await respond(operation)
