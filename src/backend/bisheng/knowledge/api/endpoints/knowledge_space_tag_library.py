from typing import Any

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.domain.schemas.knowledge_space_tag_library_schema import (
    KnowledgeSpaceTagLibraryCreateReq,
    KnowledgeSpaceTagLibraryUpdateReq,
)
from bisheng.knowledge.domain.services.knowledge_space_tag_library_service import (
    KnowledgeSpaceTagLibraryService,
)

router = APIRouter(prefix="/knowledge/space/tag-libraries", tags=["knowledge_space_tag_library"])


def get_service(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> KnowledgeSpaceTagLibraryService:
    return KnowledgeSpaceTagLibraryService(login_user)


@router.get("")
async def list_tag_libraries(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
    keyword: str | None = Query(default=None),
    svc: KnowledgeSpaceTagLibraryService = Depends(get_service),
) -> Any:
    return resp_200(await svc.list_libraries(page=page, page_size=page_size, keyword=keyword))


@router.post("")
async def create_tag_library(
    req: KnowledgeSpaceTagLibraryCreateReq,
    svc: KnowledgeSpaceTagLibraryService = Depends(get_service),
) -> Any:
    return resp_200(await svc.create_library(req.name, req.description, req.tags, is_builtin=req.is_builtin))


@router.get("/by-knowledge/{knowledge_id}")
async def list_tag_libraries_by_knowledge(
    knowledge_id: int,
    svc: KnowledgeSpaceTagLibraryService = Depends(get_service),
) -> Any:
    """List tag libraries bound to the given knowledge space."""
    return resp_200(await svc.list_bound_libraries_for_knowledge(knowledge_id))


@router.get("/{library_id}/usage")
async def get_tag_library_usage(
    library_id: int,
    svc: KnowledgeSpaceTagLibraryService = Depends(get_service),
) -> Any:
    """How many knowledge spaces currently bind this library.

    Deletion is blocked while this count is greater than zero.
    """
    count = await svc.get_library_usage(library_id)
    return resp_200({"count": count})


@router.get("/{library_id}")
async def get_tag_library(
    library_id: int,
    svc: KnowledgeSpaceTagLibraryService = Depends(get_service),
) -> Any:
    return resp_200(await svc.get_library(library_id))


@router.put("/{library_id}")
async def update_tag_library(
    library_id: int,
    req: KnowledgeSpaceTagLibraryUpdateReq,
    svc: KnowledgeSpaceTagLibraryService = Depends(get_service),
) -> Any:
    return resp_200(
        await svc.update_library(
            library_id=library_id,
            name=req.name,
            description=req.description,
            tags=req.tags,
            ai_tags=req.ai_tags,
        )
    )


@router.delete("/{library_id}")
async def delete_tag_library(
    library_id: int,
    svc: KnowledgeSpaceTagLibraryService = Depends(get_service),
) -> Any:
    await svc.delete_library(library_id)
    return resp_200(True)
