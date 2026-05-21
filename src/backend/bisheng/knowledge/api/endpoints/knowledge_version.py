"""Version management endpoints, mounted at /api/v1/knowledge/space."""
from typing import Any

from fastapi import APIRouter, Depends, Query

from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.api.dependencies import get_knowledge_version_service
from bisheng.knowledge.domain.schemas.knowledge_version_schema import LinkRequest
from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService

router = APIRouter(prefix='/knowledge/space', tags=['knowledge_version'])


@router.get('/file/{knowledge_file_id}/versions')
async def list_file_versions(
    knowledge_file_id: int,
    svc: KnowledgeVersionService = Depends(get_knowledge_version_service),
) -> Any:
    data = await svc.list_versions_for_file(knowledge_file_id)
    return resp_200(data)


@router.post('/document/link')
async def link_document(
    req: LinkRequest,
    svc: KnowledgeVersionService = Depends(get_knowledge_version_service),
) -> Any:
    data = await svc.link_file_to_document(
        knowledge_file_id=req.knowledge_file_id,
        target_document_id=req.target_document_id,
    )
    return resp_200(data)


@router.post('/version/{version_id}/set-primary')
async def set_primary(
    version_id: int,
    svc: KnowledgeVersionService = Depends(get_knowledge_version_service),
) -> Any:
    data = await svc.set_primary_version(version_id)
    return resp_200(data)


@router.delete('/version/{version_id}')
async def delete_version(
    version_id: int,
    svc: KnowledgeVersionService = Depends(get_knowledge_version_service),
) -> Any:
    data = await svc.delete_version(version_id)
    return resp_200(data)


@router.get('/{space_id}/document/search')
async def search_documents(
    space_id: int,
    keyword: str = Query(""),
    current_file_id: int = Query(...),
    svc: KnowledgeVersionService = Depends(get_knowledge_version_service),
) -> Any:
    data = await svc.search_associable_documents(
        knowledge_id=space_id, keyword=keyword, current_file_id=current_file_id,
    )
    return resp_200(data)


@router.get('/file/{knowledge_file_id}/similar')
async def get_similar_candidates(
    knowledge_file_id: int,
    svc: KnowledgeVersionService = Depends(get_knowledge_version_service),
) -> Any:
    data = await svc.get_similar_candidates_for_file(knowledge_file_id)
    return resp_200(data)


@router.get('/{space_id}/similar-pending')
async def list_similar_pending(
    space_id: int,
    svc: KnowledgeVersionService = Depends(get_knowledge_version_service),
) -> Any:
    data = await svc.list_pending_similar_files(space_id)
    return resp_200(data)


@router.post('/file/{knowledge_file_id}/dismiss-similar')
async def dismiss_similar(
    knowledge_file_id: int,
    svc: KnowledgeVersionService = Depends(get_knowledge_version_service),
) -> Any:
    data = await svc.dismiss_similar(knowledge_file_id)
    return resp_200(data)
