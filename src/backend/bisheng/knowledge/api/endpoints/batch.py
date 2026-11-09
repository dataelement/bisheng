"""Same-action inspection and signed ordinary-batch confirmation."""

from typing import Literal

from fastapi import APIRouter, Depends, Path, Request
from fastapi.exceptions import RequestValidationError
from pydantic import Field, ValidationError

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.api.endpoints.processing import _write_scope
from bisheng.knowledge.application.knowledge_batch import get_batch_application
from bisheng.knowledge.domain.schemas.knowledge_batch import BatchCommand, BatchSelection
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from bisheng.knowledge.domain.schemas.processing_settings import PositiveInteger, ProcessingSchema


def command_from(operation, change):
    try:
        return BatchCommand(operation=operation, **change.model_dump(mode="json", exclude_unset=True))
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from error


router = APIRouter(tags=["knowledge_batch"])
BatchOperation = Literal["download", "tag", "retry"]


class BatchRequest(ProcessingSchema):
    items: list[BatchSelection] = Field(min_length=1)
    tag_ids: list[PositiveInteger] = Field(default_factory=list)
    new_tag_names: list[str] = Field(default_factory=list)


@router.post("/{space_id}/files/batch/{operation}/inspect")
async def inspect_batch(
    operation: BatchOperation,
    change: BatchRequest,
    space_id: int = Path(gt=0, le=9223372036854775807),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    application=Depends(get_batch_application),
):
    command = command_from(operation, change)
    return resp_200(await application.ainspect(identity=identity, space_id=space_id, command=command))


@router.post("/{space_id}/files/batch/{operation}/precheck")
async def precheck_batch(
    operation: BatchOperation,
    change: BatchRequest,
    request: Request,
    space_id: int = Path(gt=0, le=9223372036854775807),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    application=Depends(get_batch_application),
):
    await _write_scope(request, identity)
    command = command_from(operation, change)
    return resp_200(await application.aprecheck(identity=identity, space_id=space_id, command=command))


@router.post("/{space_id}/files/batch/{operation}/confirm")
async def confirm_batch(
    operation: BatchOperation,
    change: ProcessingCreateRequest,
    request: Request,
    space_id: int = Path(gt=0, le=9223372036854775807),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    application=Depends(get_batch_application),
):
    await _write_scope(request, identity)
    return resp_200(
        await application.aconfirm(identity=identity, space_id=space_id, operation=operation, request=change)
    )
