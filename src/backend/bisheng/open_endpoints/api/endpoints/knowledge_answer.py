"""Independent Open API answer adapter; legacy filelib contracts are frozen."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from bisheng.common.errcode.knowledge import (
    KnowledgeAnswerFormatError,
    KnowledgeAnswerModelError,
    KnowledgeAnswerRetrievalError,
    KnowledgeAnswerTimeoutError,
)
from bisheng.common.errcode.open_api import OpenApiAuthDependencyUnavailableError
from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.common.errcode.tenant_fga import PermissionBackendUnavailableError
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.knowledge.domain.schemas.knowledge_answer_schema import KnowledgeAnswerReq, KnowledgeAnswerResp
from bisheng.knowledge.domain.services.knowledge_space_answer_service import KnowledgeSpaceAnswerService
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.open_endpoints.api.knowledge_answer_dependencies import get_knowledge_answer_service

router = APIRouter(prefix="/filelib", tags=["OpenAPI", "Knowledge"])


@router.post("/answer", response_model=UnifiedResponseModel[KnowledgeAnswerResp])
@open_api_scope("knowledge:read")
async def answer_knowledge(
    request: Request,
    req: KnowledgeAnswerReq,
    service: KnowledgeSpaceAnswerService = Depends(get_knowledge_answer_service),
):
    try:
        return resp_200(data=await service.answer(req))
    except (PermissionBackendUnavailableError, PermissionServiceUnavailableError) as exc:
        raise OpenApiAuthDependencyUnavailableError() from exc
    except (
        KnowledgeAnswerRetrievalError,
        KnowledgeAnswerModelError,
        KnowledgeAnswerTimeoutError,
        KnowledgeAnswerFormatError,
    ) as exc:
        request.scope["open_api_error_code"] = exc.code
        return JSONResponse(
            status_code=504 if isinstance(exc, KnowledgeAnswerTimeoutError) else 502,
            content={"status_code": exc.code, "status_message": exc.message, "data": None},
        )
