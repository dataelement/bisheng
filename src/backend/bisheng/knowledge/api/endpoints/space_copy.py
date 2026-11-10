"""Whole-space copy confirmation and truthful accepted/completed outcomes."""

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.api.endpoints.processing import _write_scope
from bisheng.knowledge.application.space_copy import SpaceCopyApplication
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest

router = APIRouter(tags=["knowledge_copy"])


class SpaceCopyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)


@router.post("/{space_id}/copy/precheck")
async def precheck_copy(
    change: SpaceCopyRequest,
    request: Request,
    space_id: int = Path(gt=0),
    identity: UserPayload = Depends(UserPayload.get_login_user),
):
    await _write_scope(request, identity)
    return resp_200(await SpaceCopyApplication().aprecheck(space_id, name=change.name, identity=identity))


@router.post("/{space_id}/copy/confirm")
async def confirm_copy(
    change: ProcessingCreateRequest,
    request: Request,
    space_id: int = Path(gt=0),
    identity: UserPayload = Depends(UserPayload.get_login_user),
):
    await _write_scope(request, identity)
    return resp_200(await SpaceCopyApplication().aconfirm(space_id, change, identity=identity))
