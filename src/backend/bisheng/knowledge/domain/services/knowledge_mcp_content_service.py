import codecs
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import anyio

from bisheng.common.cursor import decode_cursor, encode_cursor
from bisheng.common.errcode.knowledge import KnowledgeChunkError
from bisheng.common.errcode.knowledge_space import KnowledgeDocumentStateConflictError, SpacePermissionDeniedError
from bisheng.knowledge.domain.repositories.interfaces.knowledge_mcp_repository import KnowledgeMcpRepository
from bisheng.knowledge.domain.services.knowledge_document_entry_resolver import KnowledgeDocumentEntryResolver
from bisheng.knowledge.domain.services.knowledge_mcp_query_service import KnowledgeMcpQueryService
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

NATIVE_PREVIEW_EXTENSIONS = frozenset({"txt", "md", "markdown", "pdf", "jpg", "jpeg", "png", "gif", "bmp", "webp"})


class KnowledgeMcpContentService:
    def __init__(
        self,
        repository: KnowledgeMcpRepository,
        query: KnowledgeMcpQueryService,
        storage: Any,
        resolver: KnowledgeDocumentEntryResolver,
    ) -> None:
        self.repository = repository
        self.query = query
        self.storage = storage
        self.resolver = resolver

    async def _authorized(self, knowledge_id: int, file_id: int) -> Any:
        await self.query.require_space(knowledge_id)
        file = await self.repository.find_by_id(file_id)
        if (
            file is None
            or file.file_type != 1
            or file.knowledge_id != knowledge_id
            or not await self.query.visible(file)
        ):
            raise SpacePermissionDeniedError()
        return file

    async def _resolve(self, file: Any) -> tuple[Any, Any]:
        resolved = await self.resolver.resolve(
            tenant_id=int(self.query.user.tenant_id), space_id=int(file.knowledge_id), file_id=int(file.id)
        )
        if not resolved.capabilities.can_view:
            raise SpacePermissionDeniedError()
        physical = (
            file if resolved.content_file_id == file.id else await self.repository.find_by_id(resolved.content_file_id)
        )
        if physical is None or int(physical.tenant_id or 1) != int(self.query.user.tenant_id):
            raise SpacePermissionDeniedError()
        return resolved, physical

    @staticmethod
    def _version(entry: Any, physical: Any, ref: tuple[int, int, int] | None, content_format: str) -> str:
        identity = [
            entry.id,
            physical.id,
            ref,
            getattr(physical, "md5", None),
            str(physical.update_time),
            getattr(physical, "preview_file_object_name", None),
            content_format,
        ]
        return hashlib.sha256(json.dumps(identity, default=str).encode()).hexdigest()

    @staticmethod
    def _read_text_window(storage: Any, object_name: str, offset: int, limit: int) -> tuple[str, bool]:
        response = storage.download_object_sync(storage.bucket, object_name)
        decoder = codecs.getincrementaldecoder("utf-8")()
        parts, count, skipped = [], 0, 0
        try:
            while count <= limit:
                raw = response.read(65536)
                text = decoder.decode(raw, final=not raw)
                if skipped < offset:
                    removed = min(offset - skipped, len(text))
                    text = text[removed:]
                    skipped += removed
                if text:
                    piece = text[: limit + 1 - count]
                    parts.append(piece)
                    count += len(piece)
                if not raw:
                    break
            value = "".join(parts)
            if skipped < offset:
                raise ValueError("content offset exceeds text length")
            return value[:limit], len(value) > limit
        finally:
            response.close()
            response.release_conn()

    async def _text_object(self, physical: Any, content_format: str) -> tuple[str, str] | None:
        explicit = getattr(physical, "preview_file_object_name", None)
        suffixes = ("txt", "md") if content_format == "text" else ("md", "txt")
        candidates = [explicit] if explicit and str(explicit).lower().endswith((".txt", ".md", ".markdown")) else []
        candidates.extend(f"preview/{physical.id}.{suffix}" for suffix in suffixes)
        for name in dict.fromkeys(candidates):
            if await self.storage.object_exists(self.storage.bucket, name):
                return name, "text" if name.endswith(".txt") else "markdown"
        return None

    async def _chunk_window(
        self, file: Any, ref: tuple[int, int, int], index: int, offset: int, limit: int
    ) -> tuple[str, bool, int, int]:
        fetched = await self.repository.chunks(file, ref, from_index=index, limit=101)
        chunks = fetched[:100]
        next_batch = len(fetched) > 100
        parts, count, next_index, next_offset = [], 0, index, offset
        for number, chunk in enumerate(chunks):
            chunk_index = int(chunk.get("metadata", {}).get("chunk_index", 0))
            if chunk_index < index:
                continue
            text = KnowledgeService.split_chunk_metadata(str(chunk.get("text") or ""))
            if number < len(chunks) - 1 or next_batch:
                text += "\n"
            start = offset if chunk_index == index else 0
            if start > len(text):
                raise ValueError("invalid content cursor")
            available = text[start:]
            take = min(limit - count, len(available))
            parts.append(available[:take])
            count += take
            next_index, next_offset = chunk_index, start + take
            if next_offset == len(text):
                next_index, next_offset = chunk_index + 1, 0
            more = take < len(available) or number < len(chunks) - 1 or next_batch
            if count == limit:
                return "".join(parts), more, next_index, next_offset
        return "".join(parts), next_batch, next_index, next_offset

    async def get_file_detail(
        self,
        *,
        knowledge_id: int,
        file_id: int,
        include_content: bool = True,
        content_format: str = "text",
        max_chars: int = 20000,
        cursor: str | None = None,
    ) -> dict:
        file = await self._authorized(knowledge_id, file_id)
        metadata = self.query.file_item(file)
        result = {
            "file": metadata,
            "content": "",
            "content_ready": file.status == 2,
            "content_format": content_format,
            "content_version": None,
            "has_more": False,
            "next_cursor": None,
        }
        if file.status != 2 or not include_content:
            if cursor:
                raise ValueError("content cursor is not applicable")
            return result
        resolved, physical = await self._resolve(file)
        if not resolved.projection_ready:
            result["content_ready"] = False
            return result
        ref = (await self.repository.content_refs([file])).get(file.id)
        version = self._version(file, physical, ref, content_format)
        context = self.query.context(
            "get_file_detail", {"knowledge_id": knowledge_id, "file_id": file_id, "content_format": content_format}
        )
        key = decode_cursor(cursor, expected_key_len=3, expected_context=context)
        index, offset = 0, 0
        if key:
            if key[0] != version:
                raise KnowledgeDocumentStateConflictError()
            if type(key[1]) is not int or type(key[2]) is not int or key[1] < -1 or not 0 <= key[2] <= 1_000_000_000:
                raise ValueError("invalid content cursor")
            index, offset = key[1:]
        text_object = await self._text_object(physical, content_format) if not key or index == -1 else None
        if text_object:
            object_name, actual_format = text_object
            value, more = await anyio.to_thread.run_sync(
                self._read_text_window, self.storage, object_name, offset, max_chars
            )
            next_index, next_offset = -1, offset + len(value)
            result["content_format"] = actual_format
        else:
            if index == -1 or ref is None:
                raise KnowledgeChunkError()
            value, more, next_index, next_offset = await self._chunk_window(file, ref, index, offset, max_chars)
            result["content_format"] = "text"
        latest = await self.repository.find_by_id(file_id)
        latest_ref = (await self.repository.content_refs([latest])).get(file_id) if latest is not None else None
        latest_physical = await self.repository.find_by_id(int(physical.id)) if latest is not None else None
        if (
            latest is None
            or latest_physical is None
            or latest.status != 2
            or latest_ref != ref
            or self._version(latest, latest_physical, latest_ref, content_format) != version
        ):
            raise KnowledgeDocumentStateConflictError()
        result.update(
            content=value,
            content_version=version,
            has_more=more,
            next_cursor=encode_cursor([version, next_index, next_offset], context=context) if more else None,
        )
        return result

    async def get_file_source(self, *, knowledge_id: int, file_id: int, source_type: str = "auto") -> dict:
        file = await self._authorized(knowledge_id, file_id)
        resolved, physical = await self._resolve(file)
        if not resolved.capabilities.can_preview:
            raise SpacePermissionDeniedError()
        # Original downloads must use the owner's watermarked download flow.
        if source_type == "original":
            raise SpacePermissionDeniedError()
        # Pass the entry ID so the owner retains its canonical and permission checks.
        detail = await self.query.owner.get_file_preview(file_id)
        url = detail.get("pdf_preview_url") or detail.get("html_preview_url") or detail.get("preview_url")
        extension = str(physical.file_name or "").rsplit(".", 1)[-1].lower()
        # Native viewers use the owner's original URL; Office originals are never a fallback.
        if not url and extension in NATIVE_PREVIEW_EXTENSIONS:
            url = detail.get("original_url")
        if not url:
            raise KnowledgeChunkError()
        # The existing UI strips the storage host. MCP clients need an absolute link,
        # with the owner's signed path and query left unchanged.
        if url.startswith("/"):
            url = self.storage.get_minio_share_host().rstrip("/") + url
        return {
            "file_id": file_id,
            "knowledge_id": knowledge_id,
            "preview_url": url,
            "original_url": "",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            "original_unavailable_reason": "Original access requires the existing authorized watermarked download flow",
        }
