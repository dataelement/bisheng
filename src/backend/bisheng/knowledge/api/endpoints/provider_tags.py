"""Generation-bound vocabulary and document manual tag selection."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.application.provider_tag_reads import MAX_SAFE, TagRequest

router = APIRouter(tags=["knowledge_provider_tags"])
Id = Annotated[int, Path(gt=0, le=MAX_SAFE)]
Generation = Annotated[int, Query(gt=0, le=MAX_SAFE)]
Ref = Annotated[int, Field(gt=0, le=MAX_SAFE)]


class ManualTagEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    generation: Ref
    mode: Literal["replace", "clear"]
    tag_ref_ids: Annotated[list[Ref], Field(max_length=50)]
    expected_revision: Annotated[int, Field(ge=0, le=MAX_SAFE)]

    @model_validator(mode="after")
    def check_selection(self):
        if (self.mode == "clear") != (not self.tag_ref_ids) or len(set(self.tag_ref_ids)) != len(self.tag_ref_ids):
            raise ValueError("use clear for an empty selection; each reference must be unique")
        return self


@router.get("/{space_id}/provider-tags")
async def page_provider_tags(
    space_id: Id,
    generation: Generation,
    page: int = Query(1, ge=1, le=2**31 - 1),
    page_size: int = Query(50, ge=1, le=200),
    service=Depends(get_knowledge_space_service),
):
    return resp_200(await TagRequest(service, space_id, generation).page(page, page_size))


@router.get("/{space_id}/files/{file_id}/provider-tags")
async def file_provider_tags(
    space_id: Id, file_id: Id, generation: Generation, service=Depends(get_knowledge_space_service)
):
    return resp_200(await TagRequest(service, space_id, generation, file_id).file_selection())


@router.put("/{space_id}/files/{file_id}/provider-tags")
async def edit_provider_tags(
    space_id: Id, file_id: Id, command: ManualTagEdit, service=Depends(get_knowledge_space_service)
):
    return resp_200(
        await TagRequest(service, space_id, command.generation, file_id, write=True).file_selection(command)
    )
