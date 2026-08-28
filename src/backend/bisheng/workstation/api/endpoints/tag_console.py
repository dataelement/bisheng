"""F079 tag management console endpoints.

Two modes, two independent listings: ``/search`` reads approved tags, and
``/review/*`` reads and acts on pending / rejected ones.
"""

from fastapi import APIRouter, Depends, Path, Query

from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.workstation.api.dependencies import get_tag_console_service
from bisheng.workstation.domain.schemas.tag_console_schema import (
    TagConsoleBatchApproveReq,
    TagConsoleBatchDeleteReq,
    TagConsoleBatchMoveReq,
    TagConsoleBatchRejectReq,
    TagConsoleBlacklistCreateReq,
    TagConsoleBlacklistPreviewReq,
    TagConsoleBlacklistSearchReq,
    TagConsoleCreateReq,
    TagConsoleReviewRef,
    TagConsoleReviewSearchReq,
    TagConsoleSearchReq,
)
from bisheng.workstation.domain.services.tag_console_service import TagConsoleService

from ..dependencies import LoginUserDep

router = APIRouter(prefix="/tags/console", tags=["TagConsole"])


@router.post("/search", summary="List approved tags", response_model=UnifiedResponseModel)
async def search_tags(
    req: TagConsoleSearchReq,
    service: TagConsoleService = Depends(get_tag_console_service),
    login_user=LoginUserDep,
):
    return resp_200(await service.search(req, login_user.tenant_id))


@router.post("/create", summary="Add a tag to a library", response_model=UnifiedResponseModel)
async def create_tag(
    req: TagConsoleCreateReq,
    service: TagConsoleService = Depends(get_tag_console_service),
    login_user=LoginUserDep,
):
    return resp_200(await service.create_tag(req, login_user.tenant_id))


@router.post("/batch-delete", summary="Delete approved tags", response_model=UnifiedResponseModel)
async def batch_delete(
    req: TagConsoleBatchDeleteReq,
    service: TagConsoleService = Depends(get_tag_console_service),
    login_user=LoginUserDep,
):
    return resp_200(await service.batch_delete(req.ids, login_user.tenant_id))


@router.post("/batch-move", summary="Move approved tags to another library", response_model=UnifiedResponseModel)
async def batch_move(
    req: TagConsoleBatchMoveReq,
    service: TagConsoleService = Depends(get_tag_console_service),
    login_user=LoginUserDep,
):
    return resp_200(await service.batch_move(req.ids, req.target_library_id, login_user.tenant_id))


@router.post("/review/search", summary="List pending / rejected tags", response_model=UnifiedResponseModel)
async def search_review_tags(
    req: TagConsoleReviewSearchReq,
    service: TagConsoleService = Depends(get_tag_console_service),
    login_user=LoginUserDep,
):
    return resp_200(await service.review_search(req, login_user.tenant_id))


@router.post("/review/detail", summary="Review dialog context", response_model=UnifiedResponseModel)
async def review_detail(
    ref: TagConsoleReviewRef,
    service: TagConsoleService = Depends(get_tag_console_service),
    login_user=LoginUserDep,
):
    return resp_200(await service.review_detail(ref, login_user.tenant_id))


@router.post("/review/batch-approve", summary="Approve pending tags", response_model=UnifiedResponseModel)
async def batch_approve(
    req: TagConsoleBatchApproveReq,
    service: TagConsoleService = Depends(get_tag_console_service),
    login_user=LoginUserDep,
):
    return resp_200(await service.batch_approve(req.items, req.target_library_id, login_user.tenant_id, ack_similar=req.ack_similar))


@router.post("/review/batch-reject", summary="Reject pending tags", response_model=UnifiedResponseModel)
async def batch_reject(
    req: TagConsoleBatchRejectReq,
    service: TagConsoleService = Depends(get_tag_console_service),
    login_user=LoginUserDep,
):
    return resp_200(await service.batch_reject(
        req.items,
        req.reject_reason,
        login_user.tenant_id,
        skip_blacklist=req.skip_blacklist,
    ))


@router.get("/review/pending-count", summary="Badge count for the pending entry", response_model=UnifiedResponseModel)
async def pending_count(
    service: TagConsoleService = Depends(get_tag_console_service),
    login_user=LoginUserDep,
):
    return resp_200({"pending_count": await service.pending_count(login_user.tenant_id)})


@router.get(
    "/source-knowledges", summary="Options for the source-knowledge filter", response_model=UnifiedResponseModel
)
async def list_source_knowledges(
    keyword: str | None = Query(default=None),
    service: TagConsoleService = Depends(get_tag_console_service),
    login_user=LoginUserDep,
):
    return resp_200(await service.list_source_knowledges(login_user.tenant_id, keyword))


@router.get("/blacklist", summary="List tag blacklist", response_model=UnifiedResponseModel)
async def list_blacklist(
    keyword: str | None = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    service: TagConsoleService = Depends(get_tag_console_service),
):
    return resp_200(
        await service.list_blacklist(
            TagConsoleBlacklistSearchReq(keyword=keyword, page=page, page_size=page_size)
        )
    )


@router.post("/blacklist/preview", summary="Preview blacklist insert capacity", response_model=UnifiedResponseModel)
async def preview_blacklist(
    req: TagConsoleBlacklistPreviewReq,
    service: TagConsoleService = Depends(get_tag_console_service),
):
    return resp_200(await service.preview_blacklist(req.names))


@router.post("/blacklist", summary="Add a tag blacklist entry", response_model=UnifiedResponseModel)
async def add_blacklist(
    req: TagConsoleBlacklistCreateReq,
    service: TagConsoleService = Depends(get_tag_console_service),
):
    return resp_200(await service.add_blacklist(req))


@router.delete("/blacklist/{blacklist_id}", summary="Remove a blacklist entry", response_model=UnifiedResponseModel)
async def delete_blacklist(
    blacklist_id: int = Path(..., ge=1),
    service: TagConsoleService = Depends(get_tag_console_service),
):
    return resp_200(await service.delete_blacklist(blacklist_id))
