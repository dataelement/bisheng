from typing import Any, Optional

from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    KnowledgeSpaceCreateReq, KnowledgeSpaceUpdateReq,
    FolderCreateReq, FolderRenameReq,
    FileCreateReq, FileRenameReq,
    BatchDeleteReq, BatchDownloadReq,
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
    )
    return resp_200(space)


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
    )
    return resp_200(space)


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
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_knowledge_square(order_by, page, page_size)
    return resp_200(result)


# ──────────────────────────── Members ─────────────────────────────────────────

@router.get('/{space_id}/members')
async def get_space_members(
        space_id: int,
        order_by: str = 'user_id',
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    members = await svc.get_space_members(space_id, order_by)
    return resp_200(members)


@router.get('/{space_id}/children')
async def list_space_children(
        space_id: int,
        parent_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.list_space_children(space_id, parent_id, page, page_size)
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


# ──────────────────────────── Subscribe ───────────────────────────────────────

@router.post('/{space_id}/subscribe', response_model=None)
async def subscribe_space(
        space_id: int,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.subscribe_space(space_id)
    return resp_200(result)


# ──────────────────────────── Chat ────────────────────────────────────────────

@router.post('/{space_id}/chat/file/{file_id}')
async def chat_single_file(
        space_id: int,
        file_id: int,
        req: ChatReq,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    response = KnowledgeSpaceChatService.chat_single_file(space_id, login_user.user_id, file_id, req.query)
    return resp_200(response)


@router.post('/{space_id}/chat/folder/{folder_id}')
async def chat_folder(
        space_id: int,
        folder_id: int,
        req: ChatFolderReq,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    response = KnowledgeSpaceChatService.chat_folder(space_id, login_user.user_id, folder_id, req.query, req.tags)
    return resp_200(response)
