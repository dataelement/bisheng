import logging
from typing import Any, Literal

from bisheng.common.errcode.knowledge import (
    KnowledgeSharedContentNotReadyError,
    KnowledgeSharedStorageUnavailableError,
)
from bisheng.common.errcode.knowledge_space import KnowledgeDocumentStateConflictError, SpacePermissionDeniedError
from bisheng.knowledge.domain.repositories.interfaces.filelib_space_repository import FilelibSpaceRepository
from bisheng.knowledge.domain.services.knowledge_document_entry_resolver import (
    KnowledgeDocumentEntryResolutionError,
    KnowledgeDocumentEntryResolver,
)
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)


class FilelibSpaceContentService:
    def __init__(
        self,
        *,
        repository: FilelibSpaceRepository,
        resolver: KnowledgeDocumentEntryResolver,
        storage: Any,
        guard: Any,
        user: Any,
    ) -> None:
        self.repository = repository
        self.resolver = resolver
        self.storage = storage
        self.guard = guard
        self.user = user

    async def _snapshot(self, entry: Any) -> tuple[Any, Any, tuple[int, int, int], tuple]:
        try:
            resolved = await self.resolver.resolve(
                tenant_id=int(self.user.tenant_id),
                space_id=int(entry.knowledge_id),
                file_id=int(entry.id),
            )
        except KnowledgeDocumentEntryResolutionError as exc:
            raise KnowledgeDocumentStateConflictError() from exc
        if not resolved.capabilities.can_view:
            raise SpacePermissionDeniedError()
        if not resolved.projection_ready:
            raise KnowledgeSharedContentNotReadyError()
        refs = await self.repository.content_refs([entry])
        ref = refs.get(int(entry.id))
        if ref is None:
            raise KnowledgeSharedContentNotReadyError()
        if (
            getattr(resolved, "canonical_document_id", None) is not None
            and (
                int(resolved.canonical_document_id),
                int(resolved.canonical_version_id),
                int(resolved.content_generation),
            )
            != ref
        ):
            raise KnowledgeDocumentStateConflictError()
        physical = await self.repository.find_by_id(int(resolved.content_file_id))
        if physical is None or int(physical.tenant_id or 1) != int(self.user.tenant_id):
            raise KnowledgeDocumentStateConflictError()
        signature = (
            ref,
            int(resolved.content_file_id),
            resolved.applied_entry_generation,
            getattr(physical, "md5", None),
            str(getattr(physical, "update_time", None)),
            getattr(physical, "preview_file_object_name", None),
        )
        return resolved, physical, ref, signature

    @staticmethod
    def text_candidates(physical: Any, content_format: str) -> list[str]:
        suffixes = ("md", "txt") if content_format == "markdown" else ("txt", "md")
        explicit = getattr(physical, "preview_file_object_name", None)
        candidates = [explicit] if explicit and str(explicit).lower().endswith((".txt", ".md", ".markdown")) else []
        for suffix in suffixes:
            candidates.extend(
                [
                    f"preview/{physical.id}.{suffix}",
                    f"{'markdown' if suffix == 'md' else 'text'}/{physical.id}.{suffix}",
                ]
            )
        return list(dict.fromkeys(candidates))

    async def _text(self, physical: Any, content_format: str) -> str | None:
        for name in self.text_candidates(physical, content_format):
            try:
                if await self.storage.object_exists(self.storage.bucket, name):
                    raw = await self.storage.get_object(self.storage.bucket, name)
                    if raw is not None:
                        return raw.decode("utf-8")
            except Exception:
                # Text artifacts are optional; shared chunks remain an authorized fallback.
                logger.warning("filelib text artifact read failed file_id=%s", physical.id, exc_info=True)
        return None

    async def _chunks(self, entry: Any, ref: tuple[int, int, int]) -> tuple[str, int]:
        parts, index = [], 0
        while True:
            try:
                batch = await self.repository.chunks(entry, ref, from_index=index, limit=100)
            except Exception as exc:
                logger.exception("filelib shared chunks unavailable file_id=%s", entry.id)
                raise KnowledgeSharedStorageUnavailableError() from exc
            if not batch:
                break
            for chunk in batch:
                try:
                    chunk_index = int(chunk.get("metadata", {}).get("chunk_index", -1))
                except (TypeError, ValueError) as exc:
                    raise KnowledgeSharedContentNotReadyError() from exc
                if chunk_index < index:
                    raise KnowledgeSharedContentNotReadyError()
                index = chunk_index + 1
                parts.append(KnowledgeService.split_chunk_metadata(str(chunk.get("text") or "")))
            if len(batch) < 100:
                break
        if not parts:
            raise KnowledgeSharedContentNotReadyError()
        return "\n".join(parts), len(parts)

    async def read(self, entry: Any, content_format: Literal["text", "markdown"]) -> tuple[str, int]:
        await self.guard.require_space(int(entry.knowledge_id))
        flags = await self.repository.primary_flags([int(entry.id)])
        if flags.get(int(entry.id)) is False:
            raise KnowledgeDocumentStateConflictError()
        _, physical, ref, signature = await self._snapshot(entry)
        route = await self.guard.route()
        text = await self._text(physical, content_format)
        result = (text, 1 if text else 0) if text is not None else await self._chunks(entry, ref)
        latest = await self.repository.find_by_id(int(entry.id))
        if latest is None or latest.status != 2:
            raise KnowledgeDocumentStateConflictError()
        _, _, _, latest_signature = await self._snapshot(latest)
        latest_route = await self.guard.route()
        if latest_signature != signature or latest_route.routing_version != route.routing_version:
            raise KnowledgeDocumentStateConflictError()
        try:
            fresh_state = await self.repository.fresh_content_state(int(entry.id))
        except Exception as exc:
            logger.exception("filelib shared final state check failed file_id=%s", entry.id)
            raise KnowledgeSharedStorageUnavailableError() from exc
        if fresh_state != signature:
            raise KnowledgeDocumentStateConflictError()
        return result
