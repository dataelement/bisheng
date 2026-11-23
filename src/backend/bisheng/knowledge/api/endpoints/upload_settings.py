"""Expose only effective upload rules under the original container action."""

from fastapi import APIRouter, Depends, Path, Query

from bisheng.common.schemas.api import resp_200
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.application.file_processing_adapter import system_processing_defaults
from bisheng.knowledge.domain.repositories.processing_settings_repository import ProcessingSettingsRepository
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.knowledge.domain.services.processing_settings_service import ProcessingSettingsService

router = APIRouter(tags=["knowledge_space"])


@router.get("/{space_id}/files/upload-settings")
async def get_upload_settings(
    space_id: int = Path(gt=0, le=9223372036854775807),
    parent_id: int | None = Query(default=None, gt=0, le=9223372036854775807),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    await svc.require_upload_container(space_id, parent_id)
    async with get_async_db_session() as session:
        data = await ProcessingSettingsService(ProcessingSettingsRepository()).get_settings(
            session, space_id, system_defaults=system_processing_defaults(space_id)
        )
    return resp_200(data)
