from typing import Any, Optional, List

from fastapi import APIRouter, Depends, Body, Query
from starlette.responses import StreamingResponse

from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import ServerError
from bisheng.common.schemas.api import resp_200, SSEResponse
from bisheng.knowledge.api.dependencies import get_knowledge_space_service, get_knowledge_space_chat_service
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    KnowledgeSpaceCreateReq, KnowledgeSpaceUpdateReq,
    FolderCreateReq, FolderRenameReq,
    FileCreateReq, FileRenameReq,
    BatchDeleteReq, BatchDownloadReq,
    UpdateSpaceMemberRoleRequest, RemoveSpaceMemberRequest,
    ChatReq, ChatFolderReq, )
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

router = APIRouter(prefix='/knowledge/space', tags=['knowledge_space'])


# ──────────────────────────── Space CRUD ──────────────────────────────────────

@router.post('')
async def create_space(
        req: KnowledgeSpaceCreateReq,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    space = await svc.create_knowledge_space(
        name=req.name,
        description=req.description,
        icon=req.icon,
        auth_type=req.auth_type,
        is_released=req.is_released,
    )
    return resp_200(space)


@router.get('/{space_id}/info')
async def get_space_info(
        space_id: int,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    space_info = await svc.get_space_info(space_id)
    return resp_200(space_info)


@router.put('/{space_id}')
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
        is_released=req.is_released
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


@router.delete('/{space_id}')
async def delete_space(
        space_id: int,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    await svc.delete_space(space_id)
    return resp_200()


# ──────────────────────────── Space Listings ───────────────────────────────────

@router.get('/mine')
async def get_my_created_spaces(
        order_by: str = 'update_time',
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    spaces = await svc.get_my_created_spaces(order_by)
    return resp_200(spaces)


@router.get('/joined')
async def get_my_followed_spaces(
        order_by: str = 'update_time',
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    spaces = await svc.get_my_followed_spaces(order_by)
    return resp_200(spaces)


@router.get('/square')
async def get_knowledge_square(
        order_by: str = 'update_time',
        page: int = 1,
        page_size: int = 20,
        keyword: str = None,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_knowledge_square(keyword, order_by, page, page_size)
    return resp_200(result)


# ──────────────────────────── Members ─────────────────────────────────────────

@router.get('/{space_id}/members')
async def get_space_members(
        space_id: int,
        page: int = Query(1, description="Page number"),
        page_size: int = Query(20, description="Page size"),
        keyword: Optional[str] = Query(None, description="Search keyword"),
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_space_members(space_id, page, page_size, keyword)
    return resp_200(result)


@router.put('/{space_id}/members/role')
async def update_member_role(
        space_id: int,
        req: UpdateSpaceMemberRoleRequest,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    req.space_id = space_id
    result = await svc.update_member_role(req)
    return resp_200(result)


@router.delete('/{space_id}/members')
async def remove_member(
        space_id: int,
        req: RemoveSpaceMemberRequest,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    req.space_id = space_id
    result = await svc.remove_member(req)
    return resp_200(result)


@router.get('/{space_id}/children')
async def list_space_children(
        space_id: int,
        parent_id: Optional[int] = None,
        order_field: str = 'file_type',
        order_sort: str = 'asc',
        file_status: Optional[KnowledgeFileStatus] = None,
        page: int = 1,
        page_size: int = 20,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.list_space_children(space_id, parent_id, order_field, order_sort,
                                           file_status=file_status, page=page, page_size=page_size)
    return resp_200(result)


@router.get('/{space_id}/search')
async def list_space_children(
        space_id: int,
        parent_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
        tag_ids: List[int] = Query(default=None, description='标签ID列表'),
        keyword: Optional[str] = None,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.search_space_children(space_id, parent_id, tag_ids=tag_ids, keyword=keyword, page=page,
                                             page_size=page_size)
    return resp_200(result)


@router.get("/{space_id}/tag")
async def get_space_tag(
        space_id: int,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    result = await svc.get_space_tags(space_id)
    return resp_200(result)


@router.post('/{space_id}/tag')
async def add_space_tags(
        space_id: int,
        tag_name: str = Body(..., embed=True, description='标签名称'),
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    result = await svc.add_space_tag(space_id, tag_name)
    return resp_200(result)


@router.delete('/{space_id}/tag')
async def delete_space_tags(
        space_id: int,
        tag_id: int = Body(..., embed=True, description='标签ID'),
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    result = await svc.delete_space_tag(space_id, tag_id)
    return resp_200(result)


# ──────────────────────────── Folders ─────────────────────────────────────────

@router.post('/{space_id}/folders')
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


@router.put('/{space_id}/folders/{folder_id}')
async def rename_folder(
        space_id: int,
        folder_id: int,
        req: FolderRenameReq,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    folder = await svc.rename_folder(folder_id, req.name)
    return resp_200(folder)


@router.delete('/{space_id}/folders/{folder_id}')
async def delete_folder(
        space_id: int,
        folder_id: int,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    await svc.delete_folder(space_id, folder_id)
    return resp_200()


@router.get('/{space_id}/folders/{folder_id}/parent')
async def get_folder_parent(
        space_id: int,
        folder_id: int,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_folder_file_parent(space_id, folder_id)
    return resp_200(result)


# ──────────────────────────── Files ───────────────────────────────────────────

@router.post('/{space_id}/files')
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


@router.put('/{space_id}/files/{file_id}')
async def rename_file(
        space_id: int,
        file_id: int,
        req: FileRenameReq,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    file_record = await svc.rename_file(file_id, req.name)
    return resp_200(file_record)


@router.delete('/{space_id}/files/{file_id}')
async def delete_file(
        space_id: int,
        file_id: int,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    await svc.delete_file(file_id)
    return resp_200()


@router.get('/{space_id}/files/{file_id}/preview')
async def get_file_preview(
        space_id: int,
        file_id: int,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    urls = await svc.get_file_preview(file_id)
    return resp_200(urls)


@router.post('/{space_id}/files/{file_id}/tag')
async def update_file_tags(
        space_id: int,
        file_id: int,
        tag_ids: List[int] = Body(..., embed=True, description='标签ID列表'),
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    result = await svc.update_file_tags(space_id, file_id, tag_ids)
    return resp_200(result)


# ──────────────────────────── Batch Ops ───────────────────────────────────────

@router.post('/{space_id}/files/batch-download')
async def batch_download(
        space_id: int,
        req: BatchDownloadReq,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    url = await svc.batch_download(space_id, req.file_ids, req.folder_ids)
    return resp_200({'url': url})


@router.post('/{space_id}/files/batch-delete')
async def batch_delete(
        space_id: int,
        req: BatchDeleteReq,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    await svc.batch_delete(space_id, req.file_ids, req.folder_ids)
    return resp_200()


@router.post('/{space_id}/files/batch-tag')
async def batch_update_tags(
        space_id: int,
        file_ids: List[int] = Body(..., embed=True, description='文件ID列表'),
        tag_ids: List[int] = Body(..., embed=True, description='标签ID列表'),
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.batch_add_file_tags(space_id, file_ids, tag_ids)
    return resp_200(result)


@router.post('/{space_id}/files/batch-retry')
async def batch_retry_failed_files(
        space_id: int,
        file_ids: List[int] = Body(..., embed=True, description='file or folder ids'),
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    result = await svc.batch_retry_failed_files(space_id, file_ids)
    return resp_200(result)


# ──────────────────────────── Subscribe ───────────────────────────────────────

@router.post('/{space_id}/subscribe', response_model=None)
async def subscribe_space(
        space_id: int,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.subscribe_space(space_id)
    return resp_200(result)


@router.post('/{space_id}/unsubscribe', response_model=None)
async def subscribe_space(
        space_id: int,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.unsubscribe_space(space_id)
    return resp_200(result)


# ──────────────────────────── Chat ────────────────────────────────────────────

@router.post('/{space_id}/chat/file/{file_id}')
async def chat_single_file(
        space_id: int,
        file_id: int,
        req: ChatReq,
        svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
) -> Any:
    async def event_stream():
        try:
            async for one in svc.chat_single_file(space_id, file_id, req.query):
                yield SSEResponse(data=one).to_string()
        except BaseErrorCode as e:
            yield e.to_sse_event_instance_str()
        except Exception as e:
            yield ServerError(exception=e).to_sse_event_instance_str()

    return StreamingResponse(event_stream(), media_type='text/event-stream')


@router.get('/{space_id}/chat/file/{file_id}/history')
async def chat_single_file_history(
        space_id: int,
        file_id: int,
        page_size: int = 20,
        svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
) -> Any:
    response = await svc.single_file_history(space_id, file_id, page_size)
    return resp_200(response)


@router.delete('/{space_id}/chat/file/{file_id}/history')
async def clear_single_file_history(
        space_id: int,
        file_id: int,
        svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    response = await svc.clear_file_history(space_id, file_id)
    return resp_200(response)


@router.get('/{space_id}/chat/folder/session')
async def get_chat_folder_session(
        space_id: int,
        folder_id: int = Query(default=0, description="folder id"),
        svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    result = await svc.get_chat_folder_session(space_id, folder_id)
    return resp_200(result)


@router.post('/{space_id}/chat/folder/session')
async def create_chat_folder_session(
        space_id: int,
        folder_id: int = Body(default=0, embed=True, description="folder id"),
        svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    result = await svc.create_chat_folder_session(space_id, folder_id)
    return resp_200(result)


@router.delete('/{space_id}/chat/folder/session')
async def create_chat_folder_session(
        space_id: int,
        folder_id: int = Body(default=0, description="folder id"),
        chat_id: str = Body(..., description='Chat ID'),
        svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    result = await svc.delete_chat_folder_session(space_id, folder_id, chat_id)
    return resp_200(result)


@router.get('/{space_id}/chat/folder/history')
async def get_chat_folder_history(
        space_id: int,
        folder_id: int = Query(default=0, description="folder id"),
        chat_id: str = Query(..., description='Chat ID'),
        page_size: int = 20,
        svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    result = await svc.get_chat_folder_history(space_id, folder_id, chat_id, page_size)
    return resp_200(result)


@router.delete('/{space_id}/chat/folder/history')
async def get_chat_folder_history(
        space_id: int,
        folder_id: int = Query(default=0, description="folder id"),
        chat_id: str = Query(..., description='Chat ID'),
        svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    result = await svc.delete_chat_folder_history(space_id, folder_id, chat_id)
    return resp_200(result)


@router.post('/{space_id}/chat/folder')
async def chat_folder(
        space_id: int,
        req: ChatFolderReq,
        svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
) -> Any:
    async def event_stream():
        try:
            async for one in svc.chat_folder(space_id, req.folder_id, req.chat_id, req.query, req.tags):
                yield SSEResponse(data=one).to_string()
        except BaseErrorCode as e:
            yield e.to_sse_event_instance_str()
        except Exception as e:
            yield ServerError(exception=e).to_sse_event_instance_str()

    return StreamingResponse(event_stream(), media_type='text/event-stream')
