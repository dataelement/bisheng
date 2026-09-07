from fastapi import APIRouter, Depends
from pydantic import ValidationError

from bisheng.citation.api.dependencies import get_citation_resolve_service
from bisheng.citation.domain.schemas.citation_schema import CitationType, RagCitationPayloadSchema
from bisheng.citation.domain.services.citation_resolve_service import CitationResolveService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.open_endpoints.domain.schemas.citation import OpenCitationResponse
from bisheng.open_endpoints.domain.utils import get_open_api_operator_async
from bisheng.permission.application.business_authorization import (
    check_business_action,
)

router = APIRouter(prefix='/citation', tags=['OpenAPI', 'Citation'])


@router.get('/{citation_id}', response_model=UnifiedResponseModel[OpenCitationResponse])
@open_api_scope("knowledge:read")
async def get_open_citation_detail(
    citation_id: str,
    default_user: UserPayload = Depends(get_open_api_operator_async),
    service: CitationResolveService = Depends(get_citation_resolve_service),
) -> UnifiedResponseModel[OpenCitationResponse]:
    try:
        item = await service.resolve_citation(citation_id, default_user)
    except ValidationError as exc:
        raise NotFoundError() from exc

    if item.type != CitationType.RAG:
        raise NotFoundError()

    try:
        payload = RagCitationPayloadSchema.model_validate(item.sourcePayload)
    except ValidationError as exc:
        raise NotFoundError() from exc

    if payload.knowledgeId is None or payload.documentId is None:
        raise NotFoundError()
    file_info = await KnowledgeFileDao.query_by_id(payload.documentId)
    if file_info is None or file_info.knowledge_id != payload.knowledgeId:
        raise NotFoundError()
    # The response carries a direct original-file URL, so this is a download
    # decision. Preview itself remains action-free in the dedicated endpoint.
    if not await check_business_action(
        default_user,
        resource_type="knowledge_file",
        resource_id=file_info.id,
        action="download",
    ):
        raise NotFoundError()

    first_item = payload.items[0] if payload.items else None
    return resp_200(OpenCitationResponse(
        file_id=payload.documentId,
        file_name=payload.documentName,
        file_type=payload.fileType,
        knowledge_name=payload.knowledgeName,
        download_url=payload.downloadUrl,
        preview_url=payload.previewUrl,
        bbox=first_item.bbox if first_item else None,
    ))
