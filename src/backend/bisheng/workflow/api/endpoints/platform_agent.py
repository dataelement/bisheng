"""资源接口只接受业务目标与配置。不接受身份、凭据或模式覆盖。"""

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.flow import PlatformAgentConfigurationError, PlatformAgentError, PlatformAgentNotReadyError
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.workflow.application import platform_agent
from bisheng.workflow.domain.schemas.platform_agent import AgentContract

router = APIRouter(prefix="/platform-agents")


class ValidateRequest(AgentContract):
    workflow_id: str
    graph: dict
    node_id: str | None = None


async def _respond(operation):
    try:
        return resp_200(data=await operation())
    except (PlatformAgentError, UnAuthorizedError) as error:
        return JSONResponse(
            error.to_dict(data=None), status_code=403 if isinstance(error, UnAuthorizedError) else error.http_status
        )
    except Exception:
        error = PlatformAgentNotReadyError()
        return JSONResponse(error.to_dict(), status_code=error.http_status)


@router.get("")
async def list_agents(
    workflow_id: str, cursor: str | None = None, login_user: UserPayload = Depends(UserPayload.get_login_user)
):
    return await _respond(lambda: platform_agent.get_service().list_agents(login_user, workflow_id, cursor))


@router.get("/{agent_id}/versions/{version_id}")
async def get_version(
    workflow_id: str, agent_id: str, version_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user)
):
    return await _respond(
        lambda: platform_agent.get_service().get_version(login_user, workflow_id, agent_id, version_id)
    )


@router.post("/validate")
async def validate_graph(payload: object = Body(...), login_user: UserPayload = Depends(UserPayload.get_login_user)):
    async def operation():
        try:
            request = ValidateRequest.model_validate(payload)
        except ValueError:
            raise PlatformAgentConfigurationError() from None
        return await platform_agent.get_service().validate_graph(
            login_user, request.workflow_id, request.graph, request.node_id
        )

    return await _respond(operation)
