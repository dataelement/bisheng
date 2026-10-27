import json
import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from langchain_core.documents import Document
from starlette.concurrency import run_in_threadpool

from bisheng.api.v1.schemas import KnowledgeFileOne, KnowledgeFileProcess
from bisheng.common.errcode.knowledge import KnowledgeFileDeleteError, KnowledgeSharedStorageUnavailableError
from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError
from bisheng.core.cache.utils import save_download_file
from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.shared_space_direct_ingestion_service import SharedSpaceDirectIngestionService
from bisheng.open_endpoints.domain.schemas.filelib import FilelibSpaceCreate
from bisheng.open_endpoints.domain.services.filelib_space_query_service import FilelibSpaceQueryService
from bisheng.role.domain.services.quota_service import QuotaResourceType, QuotaService

logger = logging.getLogger(__name__)


class FilelibSpaceCommandService:
    def __init__(self, *, query: FilelibSpaceQueryService) -> None:
        self.query = query
        self.repository, self.owner = query.repository, query.space_service
        self.user, self.request = query.user, query.request

    async def create(self, data: FilelibSpaceCreate) -> Any:
        route = await self.query.route(write=True)
        for key, expected in (
            ("index_name", route.index_name),
            ("collection_name", route.collection_name),
            ("model", route.embedding_model_id),
        ):
            value = getattr(data, key)
            if value is not None and str(value) != str(expected):
                raise HTTPException(status_code=422, detail=f"{key} must match tenant shared storage")
        await QuotaService.check_quota(
            user_id=self.user.user_id,
            resource_type=QuotaResourceType.KNOWLEDGE_SPACE,
            tenant_id=self.user.tenant_id,
            login_user=self.user,
        )
        return await self.owner.create_knowledge_space(
            name=data.name,
            description=data.description,
            auth_type=data.auth_type,
            is_released=data.is_released,
            space_level=data.space_level,
            department_id=data.department_id,
            is_clinic=data.is_clinic,
            auto_tag_enabled=data.auto_tag_enabled,
            auto_tag_library_id=data.auto_tag_library_id,
        )

    async def update(self, knowledge_id: int, *, name: str | None, description: str | None) -> Any:
        space = await self.query.require_space(knowledge_id)
        await self.query.route(write=True)
        return await self.owner.update_knowledge_space(
            knowledge_id, name=name, description=description, is_released=bool(space.is_released)
        )

    async def prepare_upload(self, knowledge_id: int) -> Any:
        space = await self.query.require_space(knowledge_id, check_read=False)
        await self.owner.require_root_upload_permission(knowledge_id)
        await self.query.route(write=True)
        return space

    async def upload(
        self, data: KnowledgeFileProcess, *, synchronous: bool = False, background_tasks: Any = None
    ) -> list:
        await self.prepare_upload(data.knowledge_id)
        limit = await QuotaService.get_knowledge_space_upload_limit_bytes(self.user)
        if synchronous:
            return await run_in_threadpool(
                KnowledgeService.sync_process_knowledge_file, self.request, self.user, data, upload_limit_bytes=limit
            )
        return await KnowledgeService.aprocess_knowledge_file(
            request=self.request,
            login_user=self.user,
            req_data=data,
            background_tasks=background_tasks,
            upload_limit_bytes=limit,
        )

    async def delete_files(self, file_ids: list[int]) -> None:
        ids = list(dict.fromkeys(file_ids))
        if not ids:
            raise HTTPException(status_code=422, detail="file_ids must not be empty")
        files = list(await self.repository.find_by_ids(ids))
        if {int(f.id) for f in files} != set(ids) or any(
            f.file_type != FileType.FILE.value
            or int(f.tenant_id or 1) != int(self.user.tenant_id)
            or getattr(f, "deleted_at", None) is not None
            for f in files
        ):
            raise SpaceFileNotFoundError()
        space_ids = {int(f.knowledge_id) for f in files}
        if len(space_ids) != 1:
            raise KnowledgeFileDeleteError()
        space_id = next(iter(space_ids))
        await self.query.require_space(space_id)
        await self.query.route(write=True)
        await self.owner.batch_delete(space_id, ids, [])

    async def clear(self, knowledge_id: int) -> None:
        await self.query.require_space(knowledge_id)
        await self.query.route(write=True)
        roots = await self.repository.root_entries(knowledge_id)
        files = [int(f.id) for f in roots if f.file_type == FileType.FILE.value]
        folders = [int(f.id) for f in roots if f.file_type == FileType.DIR.value]
        # The domain preflights all roots and records durable folder cleanup intents.
        await self.owner.batch_delete(knowledge_id, files, folders)

    async def delete_space(self, knowledge_id: int) -> None:
        await self.query.require_space(knowledge_id)
        await self.query.route(write=True)
        await self.owner.delete_space(knowledge_id)

    async def ingest_strings(self, knowledge_id: int, documents: list[Document]) -> Any:
        if not documents:
            raise HTTPException(status_code=422, detail="documents must not be empty")
        await self.prepare_upload(knowledge_id)
        docs = [document.model_copy(deep=True) for document in documents]
        filename = Path(str(docs[0].metadata.get("source") or "document.txt")).name
        content = "\n\n".join(document.page_content for document in docs).encode("utf-8")
        path = await run_in_threadpool(save_download_file, content, "bisheng", filename)
        data = KnowledgeFileProcess(
            knowledge_id=knowledge_id,
            separator=["\n\n"],
            separator_rule=["after"],
            file_list=[KnowledgeFileOne(file_path=path)],
            extra=json.dumps(docs[0].metadata, ensure_ascii=False),
        )
        limit = await QuotaService.get_knowledge_space_upload_limit_bytes(self.user)
        knowledge, failed, files, _ = await KnowledgeService.asave_knowledge_file(
            self.user, data, upload_limit_bytes=limit
        )
        if failed:
            return failed[0]
        file = files[0]
        try:
            route = await self.query.route(write=True)
            file = await self.repository.persist_parse_result(int(file.id), 1)
            await run_in_threadpool(
                SharedSpaceDirectIngestionService.ingest_documents_sync,
                knowledge=knowledge,
                file_record=file,
                documents=docs,
                routing=route,
            )
        except Exception as exc:
            logger.exception("filelib shared text ingestion failed file_id=%s", file.id)
            await self.repository.persist_parse_result(int(file.id), 3, "共享正文写入失败。请重试")
            raise KnowledgeSharedStorageUnavailableError() from exc
        file = await self.repository.persist_parse_result(int(file.id), 2)
        return file.model_dump()
