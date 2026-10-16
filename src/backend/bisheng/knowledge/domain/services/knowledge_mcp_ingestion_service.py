import asyncio
import base64
import binascii
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import anyio

from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge_space import (
    KnowledgeDocumentStateConflictError,
    SpaceFileDuplicateError,
    SpacePermissionDeniedError,
)
from bisheng.knowledge.domain.services.knowledge_mcp_query_service import KnowledgeMcpQueryService
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.upload_extensions import validate_knowledge_upload_file_extension
from bisheng.knowledge.domain.upload_file_size import validate_knowledge_upload_file_size

logger = logging.getLogger(__name__)


class KnowledgeMcpIngestionService:
    def __init__(
        self,
        query: KnowledgeMcpQueryService,
        storage: Any,
        *,
        max_file_bytes: int,
        max_text_bytes: int,
        size_validator: Callable[[str, int], None] = validate_knowledge_upload_file_size,
        name_factory: Callable[[str], Awaitable[str]] = KnowledgeService.save_upload_file_original_name,
    ) -> None:
        self.query = query
        self.owner = query.owner
        self.storage = storage
        self.max_file_bytes = max_file_bytes
        self.max_text_bytes = max_text_bytes
        self.size_validator = size_validator
        self.name_factory = name_factory

    async def _require_target(self, knowledge_id: int, folder_id: int | None, file_name: str) -> None:
        if (
            not file_name
            or len(file_name) > 200
            or any(c in file_name for c in "/\\")
            or any(ord(c) < 32 or ord(c) == 127 for c in file_name)
        ):
            raise ValueError("invalid file name")
        validate_knowledge_upload_file_extension(file_name)
        space = await self.query.require_space(knowledge_id)
        if space.is_favorite:
            raise SpacePermissionDeniedError()
        await self.query.folder_path(knowledge_id, folder_id)
        kind, resource_id = ("folder", folder_id) if folder_id is not None else ("knowledge_space", knowledge_id)
        action = "upload_file_to_folder" if folder_id is not None else "upload_file_to_space"
        if action not in await self.query.permissions(
            kind, resource_id, knowledge_id if folder_id is not None else None
        ):
            raise SpacePermissionDeniedError()

    async def create_document(
        self,
        *,
        knowledge_id: int,
        file_name: str,
        content: str,
        content_format: str = "markdown",
        folder_id: int | None = None,
        **metadata: Any,
    ) -> dict:
        await self._require_target(knowledge_id, folder_id, file_name)
        suffix = ".md" if content_format == "markdown" else ".txt"
        if content_format not in {"text", "markdown"} or not file_name.lower().endswith(suffix):
            raise ValueError("file extension must match document format")
        if not content or len(content) > self.max_text_bytes:
            raise ValueError("document exceeds text limit")
        raw = content.encode("utf-8")
        if len(raw) > self.max_text_bytes:
            raise ValueError("document exceeds UTF-8 byte limit")
        return await self._write(knowledge_id, folder_id, file_name, raw, metadata)

    async def upload_file(
        self, *, knowledge_id: int, file_name: str, content_base64: str, folder_id: int | None = None, **metadata: Any
    ) -> dict:
        await self._require_target(knowledge_id, folder_id, file_name)
        if not content_base64 or len(content_base64) > ((self.max_file_bytes + 2) // 3) * 4:
            raise ValueError("file exceeds byte limit")
        try:
            raw = await asyncio.to_thread(base64.b64decode, content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid Base64 file") from exc
        if not raw or len(raw) > self.max_file_bytes:
            raise ValueError("file exceeds byte limit")
        return await self._write(knowledge_id, folder_id, file_name, raw, metadata)

    async def _write(
        self, knowledge_id: int, folder_id: int | None, file_name: str, raw: bytes, metadata: dict
    ) -> dict:
        allowed = {
            "file_category_code",
            "file_subcategory_code",
            "business_domain_code",
            "manual_tag_ids",
            "manual_tag_names",
        }
        if metadata.keys() - allowed:
            raise ValueError("unsupported upload metadata")
        await asyncio.to_thread(self.size_validator, file_name, len(raw))
        object_name = await self.name_factory(file_name)
        file_id = None
        try:
            await self.storage.put_object_tmp(object_name=object_name, file=raw)
            staged_url = await self.storage.get_share_link(object_name, self.storage.tmp_bucket, clear_host=False)
            try:
                # Preserve the owner-to-worker handoff when the client disconnects.
                with anyio.fail_after(90, shield=True):
                    results = await self.owner.add_file(
                        knowledge_id=knowledge_id,
                        parent_id=folder_id,
                        file_path=[staged_url],
                        enqueue_processing=False,
                        **metadata,
                    )
                    if len(results) != 1 or results[0].status == 3:
                        raise SpaceFileDuplicateError()
                    file = results[0]
                    file_id = int(file.id)
                    key = self.owner.get_preview_cache_key(knowledge_id, staged_url)
                    try:
                        await self.owner.enqueue_file_title_extraction(
                            results,
                            [key],
                            operator_user_id=self.query.user.user_id,
                            operator_is_global_super=bool(getattr(self.query.user, "is_global_super", False)),
                        )
                    except Exception as exc:
                        logger.error(
                            "mcp dispatch uncertain user_id=%s file_id=%s exception_type=%s",
                            self.query.user.user_id,
                            file_id,
                            type(exc).__name__,
                        )
                        raise KnowledgeDocumentStateConflictError(mcp_write_uncertain=True, file_id=file_id) from exc
            except BaseErrorCode:
                raise
            except (Exception, asyncio.CancelledError) as exc:
                logger.error(
                    "mcp write uncertain user_id=%s file_id=%s exception_type=%s",
                    self.query.user.user_id,
                    file_id,
                    type(exc).__name__,
                )
                raise KnowledgeDocumentStateConflictError(mcp_write_uncertain=True, file_id=file_id) from exc
            return {
                "file_id": file_id,
                "knowledge_id": knowledge_id,
                "folder_id": folder_id,
                "file_name": str(file.file_name),
                "status": int(file.status),
                "accepted": True,
                "content_ready": file.status == 2,
            }
        finally:
            # Delete only our staging object; never undo an uncertain broker publish.
            with anyio.CancelScope(shield=True):
                try:
                    await self.storage.remove_object(self.storage.tmp_bucket, object_name)
                except Exception as exc:
                    logger.warning(
                        "mcp staging cleanup deferred user_id=%s exception_type=%s",
                        self.query.user.user_id,
                        type(exc).__name__,
                    )
