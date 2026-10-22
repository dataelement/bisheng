import logging
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from bisheng.common.errcode.knowledge import KnowledgeSharedStorageUnavailableError
from bisheng.common.errcode.knowledge_space import (
    KnowledgeDocumentStateConflictError,
    SpaceNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.repositories.interfaces.filelib_space_repository import FilelibSpaceRepository
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.rag.shared_space_storage import aresolve_space_shared_routing
from bisheng.open_endpoints.domain.schemas.filelib import FileDetailFile, FileDetailResp

logger = logging.getLogger(__name__)
OPENAPI_FILE_CATEGORY_ID = "入库分类测试"
OPENAPI_FILE_CATEGORY_GROUP_CLASS_CODE = "分类编码测试"
OPENAPI_FILE_DOC_TYPE_CODE = "分类赋码测试"


def _parse_document_type_code(file_encoding: str | None) -> str:
    if not isinstance(file_encoding, str):
        return ""
    parts = [part.strip().upper() for part in file_encoding.split("-") if part.strip()]
    return parts[1] if len(parts) >= 3 else parts[0] if len(parts) == 2 else ""


def _serialize_openapi_file_item(file_item: Any, *, is_primary: bool) -> dict:
    item = (
        file_item.model_dump()
        if hasattr(file_item, "model_dump")
        else dict(file_item)
        if isinstance(file_item, dict)
        else vars(file_item).copy()
    )
    encoding = item.get("file_encoding") or ""
    return {
        **item,
        "file_encoding": encoding,
        "is_primary": is_primary,
        "document_type": _parse_document_type_code(encoding),
        "categoryID": OPENAPI_FILE_CATEGORY_ID,
        "categoryGroupClassCode": OPENAPI_FILE_CATEGORY_GROUP_CLASS_CODE,
        "docTypeCode": OPENAPI_FILE_DOC_TYPE_CODE,
    }


def _serialize_openapi_file_detail(file_item: Any, *, is_primary: bool) -> FileDetailFile:
    item = _serialize_openapi_file_item(file_item, is_primary=is_primary)
    value = item.get("update_time")
    item["update_time"] = (
        value.isoformat(sep=" ") if isinstance(value, datetime) else str(value) if value is not None else ""
    )
    return FileDetailFile.model_validate(item)


class FilelibSpaceQueryService:
    def __init__(
        self,
        *,
        request: Any,
        user: Any,
        repository: FilelibSpaceRepository,
        space_service: Any,
        content_service: Any = None,
    ) -> None:
        self.request, self.user = request, user
        self.repository, self.space_service = repository, space_service
        self.content_service = content_service

    async def require_space(self, knowledge_id: int, *, check_read: bool = True) -> Any:
        space = await self.repository.get_space(knowledge_id)
        if space is None or space.state == KnowledgeState.DELETING.value:
            raise SpaceNotFoundError()
        if int(space.type) != KnowledgeTypeEnum.SPACE.value:
            raise HTTPException(status_code=422, detail="filelib file APIs require SPACE knowledge")
        if int(space.tenant_id or 1) != int(self.user.tenant_id):
            raise SpacePermissionDeniedError()
        if check_read:
            await self.space_service._require_read_permission(knowledge_id)
        return space

    async def require_spaces(self, knowledge_ids: list[int]) -> None:
        for knowledge_id in dict.fromkeys(knowledge_ids):
            await self.require_space(int(knowledge_id))
        await self.route()

    async def route(self, *, write: bool = False) -> Any:
        try:
            route = await aresolve_space_shared_routing(int(self.user.tenant_id), KnowledgeTypeEnum.SPACE.value)
        except Exception as exc:
            logger.exception("filelib shared route unavailable tenant_id=%s", self.user.tenant_id)
            raise KnowledgeSharedStorageUnavailableError() from exc
        if route is None:
            raise KnowledgeSharedStorageUnavailableError()
        if write and route.write_frozen:
            raise KnowledgeDocumentStateConflictError(msg="共享知识存储正在维护。暂不可写入")
        return route

    async def list_files(
        self, knowledge_id: int, *, keyword: str | None, status: list[int] | None, page_num: int, page_size: int
    ) -> dict:
        await self.require_space(knowledge_id)
        await self.route()
        rows, total, writeable = await KnowledgeService.aget_knowledge_files(
            self.request,
            self.user,
            knowledge_id,
            keyword,
            status,
            page_num,
            page_size,
            file_type=FileType.FILE.value,
            include_titles=False,
        )
        ids = [int(row["id"] if isinstance(row, dict) else row.id) for row in rows]
        flags = await self.repository.primary_flags(ids)
        files = list(await self.repository.find_by_ids(ids)) if ids else []
        try:
            abstracts = await self.repository.abstracts(files)
        except Exception as exc:
            logger.exception("filelib shared abstracts unavailable knowledge_id=%s", knowledge_id)
            raise KnowledgeSharedStorageUnavailableError() from exc
        result = []
        for row, file_id in zip(rows, ids, strict=True):
            item = _serialize_openapi_file_item(row, is_primary=flags.get(file_id, True))
            item["title"] = abstracts.get(file_id, "")
            result.append(item)
        return {"data": result, "total": total, "writeable": writeable}

    async def detail(self, encoding: str, knowledge_id: int | None, content_format: str) -> FileDetailResp:
        cleaned = encoding.strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="file_encoding must not be empty")
        if knowledge_id is not None:
            await self.require_space(knowledge_id)
        files = await self.repository.find_by_encoding(cleaned, knowledge_id)
        if not files:
            raise HTTPException(status_code=404, detail="file not found")
        if len(files) > 1:
            raise HTTPException(status_code=409, detail="duplicate file_encoding found")
        file = files[0]
        await self.require_space(int(file.knowledge_id))
        if file.status != 2:
            return FileDetailResp()
        content, count = await self.content_service.read(file, content_format)
        flags = await self.repository.primary_flags([int(file.id)])
        return FileDetailResp(
            file=_serialize_openapi_file_detail(file, is_primary=flags.get(int(file.id), True)),
            content=content,
            chunk_count=count,
        )
