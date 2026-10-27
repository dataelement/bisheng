"""以库内入口控制可见性, 以当前主版本计算相似度。"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_file_similarity_candidate import KnowledgeFileSimilarityCandidate
from bisheng.knowledge.domain.schemas.knowledge_similarity_context import KnowledgeSimilarityContext
from bisheng.knowledge.domain.schemas.knowledge_version_schema import SimilarCandidateEntry

if TYPE_CHECKING:
    from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService

PermissionCheck = Callable[[int], Awaitable[bool]]


class KnowledgeSimilarityEntryService:
    def __init__(self, version_service: "KnowledgeVersionService") -> None:
        self.owner = version_service
        self.files = version_service.knowledge_file_repo

    async def resolve(self, file: KnowledgeFile | None) -> KnowledgeSimilarityContext | None:
        if file is None:
            return None
        context = await self.files.resolve_similarity_file(int(file.id))
        if context is None or not context.valid:
            return None
        return context

    async def candidates(
        self, source: KnowledgeSimilarityContext, space_id: int, can_view_file: PermissionCheck | None = None
    ) -> dict[int, KnowledgeSimilarityContext]:
        contexts = {}
        entries = await self.files.find_similarity_files_in_space(space_id, exclude_file_id=source.entry.id)
        resolved = {}
        for start in range(0, len(entries), 500):
            resolved.update(
                await self.files.resolve_similarity_files([int(entry.id) for entry in entries[start : start + 500]])
            )
        for entry in entries:
            candidate = resolved.get(entry.id)
            if (
                candidate is None
                or not candidate.valid
                or candidate.document is None
                or candidate.entry.knowledge_id != space_id
            ):
                continue
            if candidate.entry.tenant_id != source.entry.tenant_id:
                continue
            if source.document is not None and source.document.id == candidate.document.id:
                continue
            if can_view_file is not None and not await can_view_file(int(entry.id)):
                continue
            contexts[int(entry.id)] = candidate
        return contexts

    async def calculate(
        self, file_id: int, *, threshold: float | None = None, limit: int = 3
    ) -> list[KnowledgeFileSimilarityCandidate]:
        if limit <= 0:
            return []
        source = await self.resolve(await self.files.find_by_id(file_id))
        if source is None:
            return []
        contexts = await self.candidates(source, source.entry.knowledge_id)
        scored = await self.owner._score_similarity_candidates(
            source.comparison_file, [c.comparison_file for c in contexts.values()], threshold=threshold
        )
        rows = []
        seen = set()
        for score, refined, file in scored:
            target = contexts[file.id]
            if target.document.id in seen:
                continue
            seen.add(target.document.id)
            row = KnowledgeFileSimilarityCandidate(
                tenant_id=source.entry.tenant_id or 1,
                knowledge_id=source.entry.knowledge_id,
                source_file_id=file_id,
                candidate_file_id=file.id,
                candidate_document_id=target.document.id,
                similarity=score,
                refined_similarity=refined,
                sort_order=len(rows),
            )
            row.__dict__["_similarity_contexts"] = (source, target)
            rows.append(row)
            if len(rows) >= limit:
                break
        return rows

    async def rows_current(self, rows: list[KnowledgeFileSimilarityCandidate]) -> bool:
        for row in rows:
            contexts = row.__dict__.get("_similarity_contexts")
            if contexts is None:
                continue
            for previous in contexts:
                current = await self.resolve(previous.entry)
                if current is None or current.signature != previous.signature:
                    return False
        return True

    @staticmethod
    def snapshot(source: KnowledgeSimilarityContext, rows: list[KnowledgeFileSimilarityCandidate]) -> dict:
        return {
            "source": list(source.signature),
            "targets": {
                str(row.candidate_file_id): list(row.__dict__["_similarity_contexts"][1].signature)
                for row in rows
                if "_similarity_contexts" in row.__dict__
            },
        }

    @staticmethod
    def response(
        source: KnowledgeSimilarityContext, target: KnowledgeSimilarityContext, score: float, refined: float | None
    ) -> SimilarCandidateEntry:
        return SimilarCandidateEntry(
            target_document_id=target.document.id,
            title=target.entry.file_name,
            doc_code=target.content.file_encoding,
            current_primary_version_no=target.version.version_no,
            similarity=score,
            refined_similarity=refined,
            primary_uploader_name=target.content.user_name,
            primary_upload_time=target.content.create_time,
            primary_knowledge_file_id=target.entry.id,
            content_file_id=target.content.id,
            can_associate=source.can_associate and target.can_associate,
        )

    async def can_view(self, context: KnowledgeSimilarityContext) -> bool:
        resolver = self.owner.document_entry_resolver
        if resolver is None:
            return True
        from bisheng.knowledge.domain.services.knowledge_document_entry_resolver import (
            KnowledgeDocumentEntryResolutionError,
        )

        try:
            resolved = await resolver.resolve(
                tenant_id=int(context.entry.tenant_id), space_id=context.entry.knowledge_id, file_id=context.entry.id
            )
            return bool(resolved.capabilities.can_view)
        except KnowledgeDocumentEntryResolutionError:
            return False

    async def cached(
        self, file_id: int, rows: list[KnowledgeFileSimilarityCandidate], *, limit: int, check_permissions: bool = True
    ) -> list[SimilarCandidateEntry]:
        if limit <= 0:
            return []
        source = await self.resolve(await self.files.find_by_id(file_id))
        if source is None or source.entry.similar_status == 2:
            return []
        if check_permissions and not await self.can_view(source):
            return []
        out = []
        for row in rows:
            if row.knowledge_id != source.entry.knowledge_id:
                continue
            target = await self.resolve(await self.files.find_by_id(row.candidate_file_id))
            if target is None or target.document is None or target.entry.knowledge_id != source.entry.knowledge_id:
                continue
            if target.document.id != row.candidate_document_id or (
                source.document and source.document.id == target.document.id
            ):
                continue
            if not source.cached_with(target):
                continue
            if check_permissions and not await self.can_view(target):
                continue
            out.append(self.response(source, target, row.similarity, row.refined_similarity))
            if len(out) >= limit:
                break
        return out

    async def publish(
        self, file_id: int, space_id: int, *, limit: int, can_view_file: PermissionCheck | None = None
    ) -> list[SimilarCandidateEntry]:
        if limit <= 0:
            return []
        source = await self.resolve(await self.files.find_by_id(file_id))
        if source is None:
            return []
        contexts = await self.candidates(source, space_id, can_view_file)
        scored = await self.owner._score_similarity_candidates(
            source.comparison_file, [c.comparison_file for c in contexts.values()]
        )
        out, seen = [], set()
        for score, refined, file in scored:
            target = contexts[file.id]
            if target.document.id in seen:
                continue
            seen.add(target.document.id)
            response = self.response(source, target, score, refined)
            chain = await self.owner.version_repo.find_by_document_id(target.document.id)
            response.can_associate = (
                target.entry.id == target.content.id and target.document.knowledge_id == space_id and len(chain) == 1
            )
            out.append(response)
            if len(out) >= limit:
                break
        return out


async def refresh_published_similarity(session: AsyncSession, payload: dict) -> str:
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
        KnowledgeDocumentRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
        KnowledgeDocumentVersionRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
        KnowledgeFileRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_similarity_candidate_repository_impl import (
        KnowledgeFileSimilarityCandidateRepositoryImpl,
    )
    from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService

    files = KnowledgeFileRepositoryImpl(session)
    file = await files.find_by_id(payload["file_id"])
    if file is None or (
        file.knowledge_id,
        file.reference_document_id,
        file.desired_content_generation,
        file.desired_entry_generation,
    ) != (payload["knowledge_id"], payload["document_id"], payload["content_generation"], payload["entry_generation"]):
        return "skipped"
    context = await files.resolve_similarity_file(file.id)
    if context is None or not context.valid:
        return "skipped"
    service = KnowledgeVersionService(
        request=None,
        login_user=None,
        doc_repo=KnowledgeDocumentRepositoryImpl(session),
        version_repo=KnowledgeDocumentVersionRepositoryImpl(session),
        knowledge_file_repo=files,
        similar_candidate_repo=KnowledgeFileSimilarityCandidateRepositoryImpl(session),
    )
    await service.refresh_similar_candidates_for_file(file.id)
    return "done"
