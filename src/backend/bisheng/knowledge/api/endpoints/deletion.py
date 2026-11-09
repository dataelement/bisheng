"""Precheck, immutable confirmation and original durable deletion status."""

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.api.endpoints.processing import _write_scope
from bisheng.knowledge.api.endpoints.references import ReferenceSelectionRequest
from bisheng.knowledge.application.knowledge_deletion import KnowledgeDeletionApplication, get_deletion_application
from bisheng.knowledge.domain.schemas.direct_delete_scope import DeleteSelection
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest

router = APIRouter(tags=["knowledge_deletion"])


class FileDeletePrecheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ReferenceSelectionRequest] = Field(min_length=1)


class SpaceDeletePrecheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    force: bool = Field(default=False, strict=True)


@router.post("/{space_id}/files/delete/precheck")
async def precheck_files(
    change: FileDeletePrecheckRequest,
    request: Request,
    space_id: int = Path(gt=0, le=2**63 - 1),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    application: KnowledgeDeletionApplication = Depends(get_deletion_application),
):
    await _write_scope(request, identity)
    selections = tuple(
        DeleteSelection("folder" if row.type == "folder" else "knowledge_file", row.id) for row in change.items
    )
    return resp_200(await application.aprecheck(identity=identity, space_id=space_id, selections=selections))


@router.post("/{space_id}/delete/precheck")
async def precheck_space(
    change: SpaceDeletePrecheckRequest,
    request: Request,
    space_id: int = Path(gt=0, le=2**63 - 1),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    application: KnowledgeDeletionApplication = Depends(get_deletion_application),
):
    await _write_scope(request, identity)
    return resp_200(
        await application.aprecheck(
            identity=identity, space_id=space_id, operation="knowledge_space_delete", force=change.force
        )
    )


@router.post("/{space_id}/clear/precheck")
async def precheck_clear(
    request: Request,
    space_id: int = Path(gt=0, le=2**63 - 1),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    application: KnowledgeDeletionApplication = Depends(get_deletion_application),
):
    await _write_scope(request, identity)
    return resp_200(
        await application.aprecheck(identity=identity, space_id=space_id, operation="knowledge_space_clear")
    )


@router.post("/{space_id}/deletion/confirm")
async def confirm_deletion(
    change: ProcessingCreateRequest,
    request: Request,
    space_id: int = Path(gt=0, le=2**63 - 1),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    service=Depends(get_knowledge_space_service),
):
    await _write_scope(request, identity)
    return resp_200(await service.confirm_deletion(space_id, change))


@router.get("/{space_id}/deletion/{job_id}")
async def deletion_status(
    job_id: str,
    space_id: int = Path(gt=0, le=2**63 - 1),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    application: KnowledgeDeletionApplication = Depends(get_deletion_application),
):
    return resp_200(await application.astatus(identity=identity, space_id=space_id, job_id=job_id))
