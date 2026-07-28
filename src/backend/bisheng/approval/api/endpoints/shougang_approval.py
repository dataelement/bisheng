from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from bisheng.approval.api.dependencies import (
    get_knowledge_space_service,
    get_knowledge_version_service,
)
from bisheng.approval.domain.schemas.shougang_approval_schema import (
    ShougangFilePublishSubmitReq,
    ShougangFileShareRevokeReq,
    ShougangFileShareSubmitReq,
    ShougangKnowledgeSpaceCreateSubmitReq,
    ShougangKnowledgeSpaceCreateValidateReq,
)
from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200

router = APIRouter(prefix="/approval/shougang", tags=["approval"])


@router.post("/knowledge-space-create/validate")
async def validate_knowledge_space_create(
    req: ShougangKnowledgeSpaceCreateValidateReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    space_service=Depends(get_knowledge_space_service),
):
    service = ShougangApprovalService(message_service=getattr(space_service, "message_service", None))
    data = await service.validate_knowledge_space_create(
        req=req,
        login_user=login_user,
        space_service=space_service,
    )
    return resp_200(data)


@router.post("/knowledge-space-create/submit")
async def submit_knowledge_space_create(
    req: ShougangKnowledgeSpaceCreateSubmitReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    space_service=Depends(get_knowledge_space_service),
):
    service = ShougangApprovalService(message_service=getattr(space_service, "message_service", None))
    data = await service.submit_knowledge_space_create(
        req=req,
        login_user=login_user,
        space_service=space_service,
    )
    return resp_200(data)


@router.get("/file-publish/target-spaces")
async def list_file_publish_target_spaces(
    source_space_id: int = Query(..., gt=0),
    _: UserPayload = Depends(UserPayload.get_login_user),
    space_service=Depends(get_knowledge_space_service),
):
    service = ShougangApprovalService(message_service=getattr(space_service, "message_service", None))
    data = await service.list_file_publish_target_spaces(
        source_space_id=source_space_id,
        space_service=space_service,
    )
    return resp_200(data)


@router.get("/file-publish/similar-candidates")
async def list_file_publish_similar_candidates(
    source_file_id: int,
    target_space_id: int,
    _: UserPayload = Depends(UserPayload.get_login_user),
    space_service=Depends(get_knowledge_space_service),
    version_service=Depends(get_knowledge_version_service),
):
    service = ShougangApprovalService(message_service=getattr(space_service, "message_service", None))
    data = await service.list_file_publish_similar_candidates(
        source_file_id=source_file_id,
        target_space_id=target_space_id,
        version_service=version_service,
        space_service=space_service,
    )
    return resp_200(data)


@router.get("/file-publish/document-search")
async def search_file_publish_documents(
    source_file_id: int,
    target_space_id: int,
    keyword: str = "",
    cursor: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=20),
    _: UserPayload = Depends(UserPayload.get_login_user),
    space_service=Depends(get_knowledge_space_service),
    version_service=Depends(get_knowledge_version_service),
):
    service = ShougangApprovalService(message_service=getattr(space_service, "message_service", None))
    data = await service.search_file_publish_documents(
        source_file_id=source_file_id,
        target_space_id=target_space_id,
        keyword=keyword,
        cursor=cursor,
        limit=limit,
        version_service=version_service,
        space_service=space_service,
    )
    return resp_200(data)


@router.post("/file-publish/submit")
async def submit_file_publish(
    req: ShougangFilePublishSubmitReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    space_service=Depends(get_knowledge_space_service),
    version_service=Depends(get_knowledge_version_service),
):
    service = ShougangApprovalService(message_service=getattr(space_service, "message_service", None))
    data = await service.submit_file_publish(
        req=req,
        login_user=login_user,
        space_service=space_service,
        version_service=version_service,
    )
    return resp_200(data)


@router.get("/file-share/target-spaces")
async def list_file_share_target_spaces(
    source_space_id: int = Query(..., gt=0),
    source_file_id: int = Query(..., gt=0),
    _: UserPayload = Depends(UserPayload.get_login_user),
    space_service=Depends(get_knowledge_space_service),
):
    service = ShougangApprovalService(message_service=getattr(space_service, "message_service", None))
    data = await service.list_file_share_target_spaces(
        source_space_id=source_space_id,
        source_file_id=source_file_id,
        space_service=space_service,
    )
    return resp_200(data)


@router.post("/file-share/submit")
async def submit_file_share(
    req: ShougangFileShareSubmitReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    space_service=Depends(get_knowledge_space_service),
):
    service = ShougangApprovalService(message_service=getattr(space_service, "message_service", None))
    data = await service.submit_file_share(
        req=req,
        login_user=login_user,
        space_service=space_service,
    )
    return resp_200(data)


@router.get("/file-share/entries")
async def list_file_share_entries(
    source_file_id: int = Query(..., gt=0),
    _: UserPayload = Depends(UserPayload.get_login_user),
    space_service=Depends(get_knowledge_space_service),
):
    data = await space_service.list_document_share_entries(
        source_file_id=source_file_id,
    )
    return resp_200(data)


@router.post("/file-share/revoke")
async def revoke_file_share(
    req: ShougangFileShareRevokeReq,
    _: UserPayload = Depends(UserPayload.get_login_user),
    space_service=Depends(get_knowledge_space_service),
):
    data = await space_service.revoke_document_share(
        source_file_id=req.source_file_id,
        share_entry_id=req.share_entry_id,
    )
    return resp_200(data)
