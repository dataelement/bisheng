"""Knowledge-owned reference inspection; internal facts never enter responses."""

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.domain.schemas.direct_delete_scope import DeleteSelection
from bisheng.knowledge.domain.services.knowledge_reference_service import KnowledgeReferenceService

router = APIRouter(tags=["knowledge_references"])


def get_reference_service():
    from bisheng.knowledge.application.unification_coverage import production_coverage_factory

    return KnowledgeReferenceService(coverage_factory=production_coverage_factory)


class ReferenceSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(gt=0, le=2**63 - 1, strict=True)
    type: Literal["file", "folder"]


class FileReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ReferenceSelectionRequest] = Field(min_length=1)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)
    page_size: int = Field(default=50, ge=1, le=200)


def inspection_response(inspection):
    # Explicit projection: facts includes hidden Source IDs and the complete
    # physical deletion scope, so serializing the internal dataclass is unsafe.
    return {
        "check_complete": inspection.check_complete,
        "blocked": inspection.blocked,
        "source_counts": dict(inspection.source_counts),
        "slot_counts": dict(inspection.slot_counts),
        "restricted_counts": dict(inspection.restricted_counts),
        "source_page": asdict(inspection.source_page),
    }


async def _inspect(service, identity, space_id, selections, whole_space, size, cursor):
    arguments = {"identity": identity, "space_id": space_id, "selections": selections, "whole_space": whole_space}
    if cursor is not None:
        return resp_200(asdict(await service.alist_sources(**arguments, page_size=size, cursor=cursor)))
    return resp_200(inspection_response(await service.ainspect(**arguments, source_page_size=size)))


@router.get("/{space_id}/references")
async def space_references(
    space_id: int = Path(gt=0, le=2**63 - 1),
    cursor: str | None = Query(default=None, min_length=1, max_length=2048),
    page_size: int = Query(default=50, ge=1, le=200),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    service: KnowledgeReferenceService = Depends(get_reference_service),
):
    return await _inspect(service, identity, space_id, (), True, page_size, cursor)


@router.post("/{space_id}/files/references")
async def file_references(
    change: FileReferenceRequest,
    space_id: int = Path(gt=0, le=2**63 - 1),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    service: KnowledgeReferenceService = Depends(get_reference_service),
):
    selections = tuple(
        DeleteSelection("folder" if row.type == "folder" else "knowledge_file", row.id) for row in change.items
    )
    return await _inspect(service, identity, space_id, selections, False, change.page_size, change.cursor)
