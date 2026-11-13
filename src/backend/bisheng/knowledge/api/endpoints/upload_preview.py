"""Owned upload-only previews; registered file edits retain their original gates."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Path, Query, UploadFile

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.domain.schemas.upload_preview import UploadChunkUpdate, UploadPreviewRequest
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.knowledge.domain.services.upload_preview_service import UploadPreviewService
from bisheng.role.domain.services.quota_service import QuotaResourceType, require_quota

router = APIRouter(tags=["knowledge_space"])
Token = Annotated[str, Path(min_length=32, max_length=32, pattern="^[0-9a-f]+$")]


@router.post("/{space_id}/uploads")
@require_quota(QuotaResourceType.KNOWLEDGE_SPACE_FILE)
async def stage_file(
    space_id: int,
    file: UploadFile = File(...),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    parent_id: int | None = Query(default=None, gt=0),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    try:
        return resp_200(await UploadPreviewService(svc).stage(space_id, parent_id, file))
    finally:
        await file.close()


@router.get("/{space_id}/uploads/{upload_id}")
async def upload_status(
    space_id: int, upload_id: Token, svc: KnowledgeSpaceService = Depends(get_knowledge_space_service)
):
    value = await UploadPreviewService(svc).read(space_id, upload_id)
    return resp_200({"upload_id": upload_id, "state": value["state"], "rows": value.get("rows", [])})


@router.post("/{space_id}/uploads/{upload_id}/previews")
async def start_preview(
    space_id: int,
    upload_id: Token,
    request: UploadPreviewRequest,
    background_tasks: BackgroundTasks,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    service = UploadPreviewService(svc)
    receipt, rule, preview_id = await service.start(space_id, upload_id, request.overrides)
    background_tasks.add_task(service.parse, receipt, rule, preview_id)
    return resp_200({"preview_id": preview_id})


@router.get("/{space_id}/uploads/{upload_id}/previews/{preview_id}")
async def preview_status(
    space_id: int,
    upload_id: Token,
    preview_id: Token,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    service = UploadPreviewService(svc)
    return resp_200(service.preview(await service.read(space_id, upload_id), preview_id))


@router.put("/{space_id}/uploads/{upload_id}/previews/{preview_id}/chunks/{chunk_index}")
async def update_chunk(
    space_id: int,
    upload_id: Token,
    preview_id: Token,
    request: UploadChunkUpdate,
    chunk_index: int = Path(ge=0),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    return resp_200(
        await UploadPreviewService(svc).edit(
            space_id, upload_id, preview_id, chunk_index, request.expected_revision, request
        )
    )


@router.delete("/{space_id}/uploads/{upload_id}/previews/{preview_id}/chunks/{chunk_index}")
async def delete_chunk(
    space_id: int,
    upload_id: Token,
    preview_id: Token,
    chunk_index: int = Path(ge=0),
    expected_revision: int = Query(ge=0),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    return resp_200(
        await UploadPreviewService(svc).edit(space_id, upload_id, preview_id, chunk_index, expected_revision, None)
    )
