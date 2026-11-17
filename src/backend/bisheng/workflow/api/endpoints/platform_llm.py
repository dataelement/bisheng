"""供 Workflow 编辑器调用的昆联平台大模型资源接口。"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.flow import (
    PlatformLLMError,
    PlatformLLMNotReadyError,
    PlatformLLMPermissionError,
)
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.workflow.application import platform_llm

router = APIRouter(prefix="/platform-models")


async def respond(operation):
    try:
        return resp_200(data=await operation())
    except PlatformLLMError as exc:
        error = type(exc)()
    except UnAuthorizedError:
        error = PlatformLLMPermissionError()
    except Exception:
        error = PlatformLLMNotReadyError()
    return JSONResponse(error.to_dict(), status_code=error.http_status)


@router.get("")
async def list_platform_models(
    workflow_id: str,
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=256),
    cursor: str | None = Query(None, max_length=8192),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return await respond(
        lambda: platform_llm.get_service().list_models(
            login_user,
            workflow_id,
            page_size=page_size,
            search=search,
            cursor=cursor,
        )
    )


@router.get("/{resource_id}/versions/{version_id}")
async def get_platform_model_version(
    resource_id: str,
    version_id: str,
    workflow_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return await respond(
        lambda: platform_llm.get_service().get_model_version(
            login_user,
            workflow_id,
            resource_id=resource_id,
            version_id=version_id,
        )
    )
