"""Explicit move admission; confirmation acknowledges acceptance, not completion."""

from fastapi import APIRouter, Depends, Path, Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.api.endpoints.processing import _write_scope
from bisheng.knowledge.application.move_processing_access import get_move_owner
from bisheng.knowledge.application.move_processing_owner import KnowledgeMoveProcessingOwner
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FileMoveReq
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest

router = APIRouter(tags=["knowledge_move"])


@router.post("/{space_id}/files/move/precheck")
async def precheck_move(
    change: FileMoveReq,
    request: Request,
    space_id: int = Path(gt=0),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    owner: KnowledgeMoveProcessingOwner = Depends(get_move_owner),
):
    await _write_scope(request, identity)
    return resp_200(await owner.aprecheck(space_id, change, identity=identity, entry_kind="web"))


@router.post("/{space_id}/files/move/confirm")
async def confirm_move(
    change: ProcessingCreateRequest,
    request: Request,
    space_id: int = Path(gt=0),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    owner: KnowledgeMoveProcessingOwner = Depends(get_move_owner),
):
    await _write_scope(request, identity)
    return resp_200(await owner.aaccept(space_id, change, identity=identity, entry_kind="web"))
