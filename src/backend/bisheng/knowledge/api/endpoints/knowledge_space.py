from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from loguru import logger
from starlette.responses import StreamingResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import ServerError
from bisheng.common.schemas.api import SSEResponse, resp_200
from bisheng.knowledge.api.dependencies import (
    get_knowledge_space_chat_service,
    get_knowledge_space_service,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    BatchDeleteReq,
    BatchDownloadReq,
    ChatFolderReq,
    ChatReq,
    DepartmentKnowledgeSpaceBatchCreateReq,
    DepartmentKnowledgeSpaceVisibilityReq,
    FileCreateReq,
    FileEncodingUpdateReq,
    FileMoveReq,
    FileRenameReq,
    FolderCreateReq,
    FolderRenameReq,
    FolderUploadReq,
    KnowledgeSpaceCreateReq,
    KnowledgeSpaceUpdateReq,
    RemoveSpaceMemberRequest,
    UpdateSpaceMemberRoleRequest,
)
from bisheng.knowledge.domain.services.department_knowledge_space_service import (
    DepartmentKnowledgeSpaceService,
)
from bisheng.knowledge.domain.services.knowledge_space_chat_service import (
    KnowledgeSpaceChatService,
)
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
)
from bisheng.role.domain.services.quota_service import QuotaResourceType, require_quota
from bisheng.workstation.domain.services.workstation_service import WorkStationService

router = APIRouter(prefix="/knowledge/space", tags=["knowledge_space"])


# ──────────────────────────── Space CRUD ──────────────────────────────────────


@router.post("")
@require_quota(QuotaResourceType.KNOWLEDGE_SPACE)
async def create_space(
    req: KnowledgeSpaceCreateReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    space = await svc.create_knowledge_space(
        name=req.name,
        description=req.description,
        icon=req.icon,
        auth_type=req.auth_type,
        is_released=req.is_released,
        auto_tag_enabled=req.auto_tag_enabled,
        auto_tag_library_id=req.auto_tag_library_id,
        auto_tag_custom_tags=req.auto_tag_custom_tags,
    )
    return resp_200(space)


@router.get("/auto-tag-visibility")
async def get_auto_tag_visibility(
    _: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    """Whether the knowledge-space auto-tag UI is enabled for the current tenant.

    Read-only for any logged-in user; respects the same root→tenant inheritance
    as the rest of the workstation knowledge-space config.
    """
    (
        cfg,
        _inherited,
        _src,
        _has_override,
    ) = await WorkStationService.get_knowledge_space_config_with_meta()
    visible = bool(getattr(cfg, "auto_tag_visible", False)) if cfg else False
    return resp_200({"visible": visible})


@router.get("/{space_id}/info")
async def get_space_info(
    space_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    space_info = await svc.get_space_info(space_id)
    return resp_200(space_info)


@router.put("/{space_id}")
async def update_space(
    space_id: int,
    req: KnowledgeSpaceUpdateReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    space = await svc.update_knowledge_space(
        space_id=space_id,
        name=req.name,
        description=req.description,
        icon=req.icon,
        auth_type=req.auth_type,
        is_released=req.is_released,
        auto_tag_enabled=req.auto_tag_enabled,
        auto_tag_library_id=req.auto_tag_library_id,
        auto_tag_custom_tags=req.auto_tag_custom_tags,
    )
    return resp_200(space)


@router.post("/{space_id}/set-pin")
async def set_channel_pin(
    space_id: int,
    is_pined: bool = Body(default=True, embed=True),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    """Set channel pin status."""
    await svc.pin_space(space_id, is_pined)
    return resp_200(data=True)


@router.delete("/{space_id}")
async def delete_space(
    space_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    await svc.delete_space(space_id)
    return resp_200()


# ──────────────────────────── Space Listings ───────────────────────────────────


@router.get("/uploadable")
async def list_uploadable_spaces(
    keyword: str | None = Query(default=None, description="substring filter on space name"),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    """F028: list knowledge spaces where the user has ``upload_file`` permission.

    Powers the ``AddToKnowledgeModal`` data source for the workstation
    conversation-export flow. Returns a flat list (no cursor pagination —
    INV-6 豁免, see spec §3): per-user uploadable spaces typically number
    in the dozens. Body returns ``{"data": [{"id", "name", "icon", "description"}]}``.
    """
    spaces = await svc.list_uploadable_spaces(keyword=keyword)
    return resp_200(
        {
            "data": [
                {
                    "id": s.id,
                    "name": s.name or "",
                    "icon": None,
                    "description": s.description,
                }
                for s in spaces
            ]
        }
    )


@router.get("/mine")
async def get_my_created_spaces(
    order_by: str = "update_time",
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    spaces = await svc.get_my_created_spaces(order_by)
    return resp_200(spaces)


@router.get("/managed")
async def get_my_managed_spaces(
    order_by: str = "name",
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    spaces = await svc.get_my_managed_spaces(order_by)
    return resp_200(spaces)


@router.get("/joined")
async def get_my_followed_spaces(
    order_by: str = "update_time",
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    spaces = await svc.get_my_followed_spaces(order_by)
    return resp_200(spaces)


@router.get("/department")
async def get_my_department_spaces(
    request: Request,
    order_by: str = "update_time",
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    spaces = await DepartmentKnowledgeSpaceService.get_user_department_spaces(
        request=request,
        login_user=login_user,
        order_by=order_by,
    )
    return resp_200(spaces)


@router.get("/department/all")
async def get_all_department_spaces(
    request: Request,
    order_by: str = "update_time",
    include_hidden: bool = False,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    try:
        spaces = await DepartmentKnowledgeSpaceService.get_all_department_spaces(
            request=request,
            login_user=login_user,
            order_by=order_by,
            include_hidden=include_hidden,
        )
        return resp_200(spaces)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.post("/department/visibility")
async def set_department_spaces_visibility(
    req: DepartmentKnowledgeSpaceVisibilityReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    try:
        changed = await DepartmentKnowledgeSpaceService.set_spaces_hidden(
            login_user=login_user,
            req=req,
        )
        return resp_200({"changed": changed})
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.post("/department/batch-create")
async def batch_create_department_spaces(
    req: DepartmentKnowledgeSpaceBatchCreateReq,
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    try:
        spaces = await DepartmentKnowledgeSpaceService.batch_create_spaces(
            request=request,
            login_user=login_user,
            req=req,
        )
        return resp_200(spaces)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.get("/square")
async def get_knowledge_square(
    page: int = 1,
    page_size: int = 20,
    keyword: str = None,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_knowledge_square(keyword, page, page_size)
    return resp_200(result)


# ──────────────────────────── Members ─────────────────────────────────────────


@router.get("/{space_id}/members")
async def get_space_members(
    space_id: int,
    page: int = Query(1, description="Page number"),
    page_size: int = Query(20, description="Page size"),
    keyword: str | None = Query(None, description="Search keyword"),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_space_members(space_id, page, page_size, keyword)
    return resp_200(result)


@router.put("/{space_id}/members/role")
async def update_member_role(
    space_id: int,
    req: UpdateSpaceMemberRoleRequest,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    req.space_id = space_id
    result = await svc.update_member_role(req)
    return resp_200(result)


@router.delete("/{space_id}/members")
async def remove_member(
    space_id: int,
    req: RemoveSpaceMemberRequest,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    req.space_id = space_id
    result = await svc.remove_member(req)
    return resp_200(result)


@router.get("/{space_id}/children")
async def list_space_children(
    space_id: int,
    parent_id: int | None = None,
    file_ids: list[int] = Query(default=None, description="精确文件ID列表"),
    order_field: str = "file_type",
    order_sort: str = "asc",
    file_status: list[int] = Query(default=None, description="文件状态列表"),
    page_size: int = 20,
    cursor: str | None = Query(
        default=None,
        description="F027 cursor-based pagination token from the previous response's "
        "`next_cursor`. Omit (or pass empty) to fetch the first page.",
    ),
    file_type: int | None = Query(default=None, description="0=DIR only, 1=FILE only, empty=both"),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    """List space children (F027 cursor-based pagination).

    Response shape (PageInfiniteCursorData): ``{data, page_size, has_more, next_cursor}``.
    The legacy ``total`` / ``page`` fields have been removed (AC-03).
    """
    result = await svc.list_space_children(
        space_id,
        parent_id,
        file_ids,
        order_field,
        order_sort,
        file_status=file_status,
        cursor=cursor,
        page_size=page_size,
        file_type=file_type,
    )
    return resp_200(result)


@router.get("/{space_id}/search")
async def search_space_children(
    space_id: int,
    parent_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
    order_field: str = "file_type",
    order_sort: str = "asc",
    tag_ids: list[int] = Query(default=None, description="标签ID列表"),
    file_status: list[int] = Query(default=None, description="文件状态列表"),
    keyword: str | None = None,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.search_space_children(
        space_id,
        parent_id,
        tag_ids=tag_ids,
        keyword=keyword,
        page=page,
        page_size=page_size,
        file_status=file_status,
        order_field=order_field,
        order_sort=order_sort,
    )
    return resp_200(result)


@router.get("/{space_id}/tag")
async def get_space_tag(
    space_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    result = await svc.get_space_tags(space_id)
    return resp_200(result)


@router.post("/{space_id}/tag")
async def add_space_tags(
    space_id: int,
    tag_name: str = Body(..., embed=True, description="标签名称"),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    result = await svc.add_space_tag(space_id, tag_name)
    return resp_200(result)


@router.delete("/{space_id}/tag")
async def delete_space_tags(
    space_id: int,
    tag_id: int = Body(..., embed=True, description="标签ID"),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    result = await svc.delete_space_tag(space_id, tag_id)
    return resp_200(result)


# ──────────────────────────── Folders ─────────────────────────────────────────


@router.post("/{space_id}/folders")
async def add_folder(
    space_id: int,
    req: FolderCreateReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    folder = await svc.add_folder(
        knowledge_id=space_id,
        folder_name=req.name,
        parent_id=req.parent_id,
    )
    return resp_200(folder)


@router.post("/{space_id}/folders/upload")
async def upload_folder(
    space_id: int,
    req: FolderUploadReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    """F034 §5.5: register a whole client-side folder (nested) in one batch."""
    files = await svc.upload_folder_items(
        knowledge_id=space_id,
        items=req.items,
        parent_id=req.parent_id,
    )
    return resp_200(files)


@router.put("/{space_id}/folders/{folder_id}")
async def rename_folder(
    space_id: int,
    folder_id: int,
    req: FolderRenameReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    folder = await svc.rename_folder(folder_id, req.name)
    return resp_200(folder)


@router.delete("/{space_id}/folders/{folder_id}")
async def delete_folder(
    space_id: int,
    folder_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    await svc.delete_folder(space_id, folder_id)
    return resp_200()


@router.get("/{space_id}/folders/{folder_id}/parent")
async def get_folder_parent(
    space_id: int,
    folder_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_folder_file_parent(space_id, folder_id)
    return resp_200(result)


# ──────────────────────────── Files ───────────────────────────────────────────


@router.post("/{space_id}/files")
async def add_file(
    space_id: int,
    req: FileCreateReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    file_record = await svc.add_file(
        knowledge_id=space_id,
        file_path=req.file_path,
        parent_id=req.parent_id,
    )
    return resp_200(file_record)


@router.put("/{space_id}/files/{file_id}")
async def rename_file(
    space_id: int,
    file_id: int,
    req: FileRenameReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    file_record = await svc.rename_file(file_id, req.name)
    return resp_200(file_record)


@router.put("/{space_id}/files/{file_id}/encoding")
async def update_file_encoding(
    space_id: int,
    file_id: int,
    req: FileEncodingUpdateReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    file_record = await svc.update_file_encoding(file_id, req.encoding)
    return resp_200(file_record)


@router.delete("/{space_id}/files/{file_id}")
async def delete_file(
    space_id: int,
    file_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    await svc.delete_file(file_id)
    return resp_200()


@router.post("/{space_id}/files/move")
async def move_file_folder(
    space_id: int,
    req: FileMoveReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    """F034: move files/folders within or across spaces (same-space when
    target_space_id == space_id). Returns {moved, invalid}; see design §4.2."""
    result = await svc.move_items(
        space_id,
        [item.model_dump() for item in req.items],
        target_space_id=req.target_space_id,
        target_folder_id=req.target_folder_id,
        skip_invalid=req.skip_invalid,
    )
    return resp_200(result)


@router.get("/{space_id}/files/{file_id}/preview")
async def get_file_preview(
    space_id: int,
    file_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    urls = await svc.get_file_preview(file_id)
    return resp_200(urls)


@router.get("/{space_id}/files/{file_id}/download")
async def get_file_download(
    space_id: int,
    file_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    urls = await svc.get_file_download(file_id, space_id=space_id)
    return resp_200(urls)


@router.post("/{space_id}/files/{file_id}/tag")
async def update_file_tags(
    space_id: int,
    file_id: int,
    tag_ids: list[int] = Body(..., embed=True, description="标签ID列表"),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    result = await svc.update_file_tags(space_id, file_id, tag_ids)
    return resp_200(result)


# ──────────────────────────── Batch Ops ───────────────────────────────────────


@router.post("/{space_id}/files/batch-download")
async def batch_download(
    space_id: int,
    req: BatchDownloadReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    url = await svc.batch_download(space_id, req.file_ids, req.folder_ids)
    return resp_200({"url": url})


@router.post("/{space_id}/files/batch-delete")
async def batch_delete(
    space_id: int,
    req: BatchDeleteReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    await svc.batch_delete(space_id, req.file_ids, req.folder_ids)
    return resp_200()


@router.post("/{space_id}/files/batch-tag")
async def batch_update_tags(
    space_id: int,
    file_ids: list[int] = Body(..., embed=True, description="文件ID列表"),
    tag_ids: list[int] = Body(..., embed=True, description="标签ID列表"),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.batch_add_file_tags(space_id, file_ids, tag_ids)
    return resp_200(result)


@router.post("/{space_id}/files/batch-retry")
async def batch_retry_failed_files(
    space_id: int,
    file_ids: list[int] = Body(..., embed=True, description="file or folder ids"),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    result = await svc.batch_retry_failed_files(space_id, file_ids)
    return resp_200(result)


@router.post("/{space_id}/files/retry")
async def retry_space_files(
    space_id: int,
    req_data: dict = Body(...),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    """Retry files in a knowledge space with potentially new split rules"""
    result = await svc.retry_space_files(space_id, req_data)
    return resp_200(result)


# ──────────────────────────── Subscribe ───────────────────────────────────────


@router.post("/{space_id}/subscribe", response_model=None)
async def subscribe_space(
    space_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.subscribe_space(space_id)
    return resp_200(result)


@router.post("/{space_id}/unsubscribe", response_model=None)
async def subscribe_space(
    space_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.unsubscribe_space(space_id)
    return resp_200(result)


# ──────────────────────────── Chat ────────────────────────────────────────────


@router.post("/{space_id}/chat/file/{file_id}")
async def chat_single_file(
    space_id: int,
    file_id: int,
    req: ChatReq,
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
) -> Any:
    async def event_stream():
        try:
            async for one in svc.chat_single_file(space_id, file_id, req.query, req.model_id):
                yield SSEResponse(data=one).to_string()
        except BaseErrorCode as e:
            yield e.to_sse_event_instance_str()
        except Exception as e:
            logger.exception("chat_file error")
            yield ServerError(exception=e).to_sse_event_instance_str()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{space_id}/chat/file/{file_id}/history")
async def chat_single_file_history(
    space_id: int,
    file_id: int,
    page_size: int = 20,
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
) -> Any:
    response = await svc.single_file_history(space_id, file_id, page_size)
    return resp_200(response)


@router.delete("/{space_id}/chat/file/{file_id}/history")
async def clear_single_file_history(
    space_id: int,
    file_id: int,
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    response = await svc.clear_file_history(space_id, file_id)
    return resp_200(response)


@router.get("/{space_id}/chat/folder/session")
async def get_chat_folder_session(
    space_id: int,
    folder_id: int = Query(default=0, description="folder id"),
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    result = await svc.get_chat_folder_session(space_id, folder_id)
    return resp_200(result)


@router.post("/{space_id}/chat/folder/session")
async def create_chat_folder_session(
    space_id: int,
    folder_id: int = Body(default=0, embed=True, description="folder id"),
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    result = await svc.create_chat_folder_session(space_id, folder_id)
    return resp_200(result)


@router.delete("/{space_id}/chat/folder/session")
async def create_chat_folder_session(
    space_id: int,
    folder_id: int = Body(default=0, description="folder id"),
    chat_id: str = Body(..., description="Chat ID"),
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    result = await svc.delete_chat_folder_session(space_id, folder_id, chat_id)
    return resp_200(result)


@router.get("/{space_id}/chat/folder/history")
async def get_chat_folder_history(
    space_id: int,
    folder_id: int = Query(default=0, description="folder id"),
    chat_id: str = Query(..., description="Chat ID"),
    page_size: int = 20,
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    result = await svc.get_chat_folder_history(space_id, folder_id, chat_id, page_size)
    return resp_200(result)


@router.delete("/{space_id}/chat/folder/history")
async def get_chat_folder_history(
    space_id: int,
    folder_id: int = Query(default=0, description="folder id"),
    chat_id: str = Query(..., description="Chat ID"),
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    result = await svc.delete_chat_folder_history(space_id, folder_id, chat_id)
    return resp_200(result)


@router.post("/{space_id}/chat/folder")
async def chat_folder(
    space_id: int,
    req: ChatFolderReq,
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
) -> Any:
    async def event_stream():
        try:
            async for one in svc.chat_folder(space_id, req.folder_id, req.chat_id, req.query, req.model_id, req.tags):
                yield SSEResponse(data=one).to_string()
        except BaseErrorCode as e:
            yield e.to_sse_event_instance_str()
        except Exception as e:
            logger.exception("chat_folder error")
            yield ServerError(exception=e).to_sse_event_instance_str()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
