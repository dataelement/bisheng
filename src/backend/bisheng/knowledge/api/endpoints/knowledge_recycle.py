"""Knowledge recycle-bin API endpoints (admin only)."""


from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.domain.schemas.knowledge_recycle import (
    RecycleConfigUpdateRequest,
    RecyclePurgeRequest,
    RecycleRestorePreviewRequest,
    RecycleRestoreRequest,
)
from bisheng.knowledge.domain.services.knowledge_recycle_service import KnowledgeRecycleService

router = APIRouter(prefix="/knowledge_recycle", tags=["KnowledgeRecycle"])


@router.get("/config")
async def get_recycle_config(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    service = KnowledgeRecycleService(login_user)
    return resp_200(await service.get_config())


@router.put("/config")
async def update_recycle_config(
    req: RecycleConfigUpdateRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    service = KnowledgeRecycleService(login_user)
    return resp_200(await service.update_config(req))


@router.get("/items")
async def list_recycle_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    knowledge_id: int | None = None,
    space_level: str | None = None,
    file_type: int | None = None,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    service = KnowledgeRecycleService(login_user)
    data = await service.list_items(
        page=page,
        page_size=page_size,
        keyword=keyword,
        knowledge_id=knowledge_id,
        space_level=space_level,
        file_type=file_type,
    )
    return resp_200(data)


@router.post("/restore/preview")
async def preview_restore(
    req: RecycleRestorePreviewRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    service = KnowledgeRecycleService(login_user)
    return resp_200(await service.preview_restore(req))


@router.post("/restore")
async def restore_items(
    req: RecycleRestoreRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    service = KnowledgeRecycleService(login_user)
    return resp_200(await service.restore(req))


@router.post("/purge")
async def purge_items(
    req: RecyclePurgeRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    service = KnowledgeRecycleService(login_user)
    return resp_200(await service.purge(req))
