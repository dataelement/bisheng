from __future__ import annotations

import asyncio
from collections.abc import Sequence

from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.interfaces.knowledge_migration_preflight_inspector import (
    KnowledgeMigrationPreflightInspector,
)
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils


class KnowledgeMigrationPreflightInspectorImpl(
    KnowledgeMigrationPreflightInspector
):
    @staticmethod
    def _find_storage_errors(
        files: Sequence[KnowledgeFile],
    ) -> dict[int, str]:
        storage = get_minio_storage_sync()
        errors: dict[int, str] = {}
        for file in files:
            file_id = int(file.id)
            object_name = KnowledgeUtils.resolve_source_object_name(
                file_id,
                file.file_name,
                file.object_name,
            )
            if not object_name:
                errors[file_id] = "来源原始对象路径无法解析"
            elif not storage.object_exists_sync(
                storage.bucket,
                object_name,
            ):
                errors[file_id] = "来源原始对象不存在"
        return errors

    async def find_storage_errors(
        self,
        files: Sequence[KnowledgeFile],
    ) -> dict[int, str]:
        from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
        from bisheng.knowledge.rag.shared_space_storage import aresolve_space_shared_routing

        for tenant_id in {int(file.tenant_id or 1) for file in files}:
            await aresolve_space_shared_routing(tenant_id, KnowledgeTypeEnum.SPACE.value)
        return await asyncio.to_thread(
            self._find_storage_errors,
            tuple(files),
        )
