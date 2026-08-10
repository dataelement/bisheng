from __future__ import annotations

import logging
from typing import Any

from bisheng.knowledge.domain.models.knowledge_file import (
    MEMBER_HIDDEN_FILE_STATUSES,
    KnowledgeFile,
)
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileAccessSource,
    DepartmentFileAccessStatus,
    DepartmentFileViewAccessService,
)

logger = logging.getLogger(__name__)


class KnowledgeFileVisibilityService:
    """Reuse effective list visibility and narrow department files by approval state."""

    def __init__(
        self,
        *,
        authorization_service: Any,
        department_access_service: DepartmentFileViewAccessService,
    ):
        self.authorization_service = authorization_service
        self.department_access_service = department_access_service

    async def filter_visible(
        self,
        *,
        login_user: Any,
        knowledge_id: int,
        files: list[KnowledgeFile],
    ) -> list[KnowledgeFile]:
        if not files:
            return []
        try:
            standard_visible = await self.authorization_service.filter_visible_files(
                space_id=knowledge_id,
                files=files,
            )
            standard_ids = {int(file.id) for file in standard_visible}
            decisions = await self.department_access_service.evaluate_files(
                login_user=login_user,
                files=files,
            )
        except Exception:
            logger.exception(
                "knowledge file visibility evaluation failed knowledge_id=%s user_id=%s file_ids=%s",
                knowledge_id,
                getattr(login_user, "user_id", None),
                [int(file.id) for file in files],
            )
            return []

        visible: list[KnowledgeFile] = []
        for file in files:
            file_id = int(file.id)
            decision = decisions.get(file_id)
            if decision is None or decision.status == DepartmentFileAccessStatus.NOT_APPLICABLE:
                if file_id in standard_ids:
                    visible.append(file)
                continue
            if decision.status != DepartmentFileAccessStatus.ALLOWED:
                continue
            if file.status in MEMBER_HIDDEN_FILE_STATUSES and decision.source not in {
                DepartmentFileAccessSource.ADMINISTRATOR,
                DepartmentFileAccessSource.RESOURCE_OWNER,
            }:
                continue
            visible.append(file)
        return visible
