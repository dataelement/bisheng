"""Business logic for knowledge-space file version management.

Responsibilities (to be filled in by subsequent Plan 2 tasks):
- link: associate a parsed file into a target logical document's chain (auto-promotes to primary)
- set_primary: promote a historical version back to primary
- delete_version: remove a historical version (mirrors normal file delete)
- list_versions: read a document's version chain
- search_documents: find candidate target documents in a knowledge space

Switch off => all write methods raise 403; read methods stay available.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError, SpaceNotFoundError
from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_repository import (
    KnowledgeDocumentRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
    KnowledgeDocumentVersionRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import (
    KnowledgeFileRepository,
)
from bisheng.knowledge.domain.services.knowledge_processing_guard import require_space_processing_idle


class KnowledgeVersionService:
    """Business service for the file version management feature."""

    def __init__(
        self,
        request: Request,
        login_user: UserPayload,
        doc_repo: KnowledgeDocumentRepository,
        version_repo: KnowledgeDocumentVersionRepository,
        knowledge_file_repo: KnowledgeFileRepository,
        *,
        version_read_service=None,
        version_mutation_application=None,
    ):
        self.request = request
        self.login_user = login_user
        self.doc_repo = doc_repo
        self.version_repo = version_repo
        self.knowledge_file_repo = knowledge_file_repo
        self._version_read_service = version_read_service
        self.version_mutation_application = version_mutation_application

    def _reads(self):
        if self._version_read_service is None:
            from bisheng.knowledge.domain.services.knowledge_version_read_service import KnowledgeVersionReadService

            self._version_read_service = KnowledgeVersionReadService(self.request, self.login_user)
        return self._version_read_service

    async def search_candidates_page(
        self, *, knowledge_id, keyword, current_file_id, page_size=40, cursor=None, source_only=False
    ):
        return await self._reads().search_candidates_page(
            knowledge_id=knowledge_id,
            keyword=keyword,
            current_file_id=current_file_id,
            page_size=page_size,
            cursor=cursor,
            source_only=source_only,
        )

    async def _require_version_management_enabled(self) -> None:
        """Raise the business-code error if the feature switch is off so the
        client can surface the product-specified Chinese toast instead of being
        bounced to /c/new?error=11403 by the global 403 redirect."""
        from bisheng.common.errcode.knowledge_space import VersionManagementDisabledError

        conf = await bisheng_settings.async_get_knowledge()
        vmc = getattr(conf, "version_management", None)
        if vmc is None or not vmc.enabled:
            raise VersionManagementDisabledError()

    async def _require_processing_idle(self, knowledge_id: int, operation: str) -> None:
        space = await KnowledgeDao.aquery_by_id(knowledge_id)
        if space is None:
            raise SpaceNotFoundError()
        if space.type == KnowledgeTypeEnum.SPACE.value:
            require_space_processing_idle(space, operation=operation)

    async def list_versions_for_file(self, knowledge_file_id: int):
        try:
            return await self._reads().list_versions_for_file(knowledge_file_id)
        except SpaceFileNotFoundError as error:
            raise HTTPException(status_code=404, detail="version chain not found for this file") from error

    async def search_associable_documents(self, knowledge_id: int, keyword: str, current_file_id: int):
        return await self._reads().search_associable_documents(knowledge_id, keyword, current_file_id)

    def _mutations(self):
        if self.version_mutation_application is None:
            raise RuntimeError("Version mutation application is not configured")
        return self.version_mutation_application

    async def link_file_to_document(self, knowledge_file_id: int, target_document_id: int):
        """Relink the complete chain in one application-owned transaction."""
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import LinkResponse
        from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import (
            KnowledgeAuditTelemetryService,
        )

        result = await self._mutations().alink_file(
            login_user=self.login_user,
            knowledge_file_id=knowledge_file_id,
            target_document_id=target_document_id,
        )
        KnowledgeAuditTelemetryService.audit_link_file_version(
            self.login_user, self.request, result.knowledge_id, result.file_name, result.new_version_no
        )
        return LinkResponse(document_id=result.document_id, new_version_no=result.new_version_no)

    async def set_primary_version(self, version_id: int):
        """Promote the selected version atomically; the existing RAG filter applies."""
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import SetPrimaryResponse
        from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import (
            KnowledgeAuditTelemetryService,
        )

        result = await self._mutations().aset_primary(login_user=self.login_user, version_id=version_id)
        KnowledgeAuditTelemetryService.audit_set_primary_version(
            self.login_user, self.request, result.knowledge_id, result.file_name, result.new_primary_version_no
        )
        return SetPrimaryResponse(document_id=result.document_id, new_primary_version_no=result.new_primary_version_no)

    async def delete_version(self, version_id: int):
        """Keep the historical-version protocol on the exact physical delete chain."""
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import DeleteVersionResponse
        from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import (
            KnowledgeAuditTelemetryService,
        )

        await self._require_version_management_enabled()
        version = await self.version_repo.find_by_id(version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="version not found")
        if version.is_primary:
            raise HTTPException(
                status_code=409, detail="cannot delete the primary version; promote another version first"
            )
        factory = getattr(self, "deletion_application_factory", None)
        if factory is None:
            raise RuntimeError("historical version deletion composition is not configured")
        deleted = await factory().adelete_historical_version(identity=self.login_user, version_id=version_id)
        KnowledgeAuditTelemetryService.audit_delete_file_version(
            self.login_user, self.request, deleted["knowledge_id"], deleted["file_name"], deleted["deleted_version_no"]
        )
        return DeleteVersionResponse(
            document_id=deleted["document_id"], deleted_version_no=deleted["deleted_version_no"]
        )

    async def scan_similar_for_file(
        self,
        knowledge_file_id: int,
        *,
        threshold: float | None = None,
    ) -> int:
        """Scan main-version files in the same space; if any candidate's similarity
        is >= threshold, set this file's similar_status = 1.

        Returns the number of candidates above threshold.
        Does nothing if the file has no simhash yet (e.g., scan called before parse finishes).
        """
        from bisheng.common.utils.simhash_utils import similarity as _similarity

        kf = await self.knowledge_file_repo.find_by_id(knowledge_file_id)
        if kf is None or not kf.simhash:
            return 0

        if threshold is None:
            conf = await bisheng_settings.async_get_knowledge()
            vmc = getattr(conf, "version_management", None)
            threshold = vmc.simhash_similarity_threshold if vmc else 0.85

        # Find all main-version files in the same space (excluding self)
        candidates = await self.knowledge_file_repo.find_main_version_files_in_space(
            knowledge_id=kf.knowledge_id,
            exclude_file_id=knowledge_file_id,
        )

        above_count = 0
        for c in candidates:
            if not c.simhash:
                continue
            if _similarity(kf.simhash, c.simhash) >= threshold:
                above_count += 1

        if above_count > 0 and kf.similar_status != 1:
            kf.similar_status = 1
            await self.knowledge_file_repo.update(kf)
        return above_count

    async def list_pending_similar_files(self, knowledge_id: int) -> list:
        """List files in this space with similar_status=1 (pending user action).

        For each, count how many candidates currently exceed threshold (fresh re-scan).
        """
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import PendingSimilarFileEntry

        pending = await KnowledgeFileDao.aget_files_by_similar_status(
            knowledge_id=knowledge_id,
            similar_status=1,
        )

        out: list[PendingSimilarFileEntry] = []
        for kf in pending:
            v = await self.version_repo.find_by_knowledge_file_id(kf.id)
            # Skip files whose logical document is already multi-version: the user
            # has already processed similarity (by merging another doc into this
            # chain). A multi-version doc is no longer an "independent document"
            # that needs the link-or-dismiss decision.
            if v is not None:
                chain = await self.version_repo.find_by_document_id(v.document_id)
                if len(chain) >= 2:
                    continue
            # Cap candidate_count at the same limit the right-panel uses (default 3)
            # so the left-side count never exceeds what the user can actually act on.
            candidates = await self.get_similar_candidates_for_file(kf.id)
            out.append(
                PendingSimilarFileEntry(
                    knowledge_file_id=kf.id,
                    file_name=kf.file_name,
                    file_code=getattr(kf, "file_encoding", None),
                    candidate_count=len(candidates),
                    current_primary_version_no=v.version_no if v else 1,
                    primary_uploader_name=kf.user_name,
                )
            )
        return out

    async def dismiss_similar(self, knowledge_file_id: int):
        """User chose 'don't link'. Set similar_status=2 + audit log."""
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import DismissSimilarResponse
        from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import (
            KnowledgeAuditTelemetryService,
        )

        await self._require_version_management_enabled()

        kf = await self.knowledge_file_repo.find_by_id(knowledge_file_id)
        if kf is None:
            raise HTTPException(status_code=404, detail="file not found")

        if kf.similar_status != 2:
            kf.similar_status = 2
            await self.knowledge_file_repo.update(kf)

        KnowledgeAuditTelemetryService.audit_dismiss_similar_file(
            self.login_user,
            self.request,
            kf.knowledge_id,
            kf.file_name,
        )
        return DismissSimilarResponse(knowledge_file_id=kf.id, similar_status=2)

    async def get_version_recommendations(
        self,
        current_file_id: int,
        *,
        limit: int = 3,
    ) -> list:
        """Top-N single-version similar candidates for the version management dialog.

        Same scoring as get_similar_candidates_for_file but additionally filters out
        documents that already have multiple versions — multi-version docs cannot be
        merged in (they own their own version chain).
        """
        from bisheng.common.utils.simhash_utils import similarity as _similarity
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import SimilarCandidateEntry

        kf = await self.knowledge_file_repo.find_by_id(current_file_id)
        if kf is None or not kf.simhash:
            return []

        conf = await bisheng_settings.async_get_knowledge()
        vmc = getattr(conf, "version_management", None)
        threshold: float = vmc.simhash_similarity_threshold if vmc else 0.85

        self_v = await self.version_repo.find_by_knowledge_file_id(current_file_id)
        self_doc_id = self_v.document_id if self_v else None

        candidates = await self.knowledge_file_repo.find_main_version_files_in_space(
            knowledge_id=kf.knowledge_id,
            exclude_file_id=current_file_id,
        )

        scored: list[tuple[float, KnowledgeFile]] = []
        for c in candidates:
            if not c.simhash:
                continue
            sim = _similarity(kf.simhash, c.simhash)
            if sim < threshold:
                continue
            scored.append((sim, c))

        scored.sort(key=lambda x: x[0], reverse=True)

        out: list[SimilarCandidateEntry] = []
        for sim, c in scored:
            if len(out) >= limit:
                break
            v = await self.version_repo.find_by_knowledge_file_id(c.id)
            if v is None:
                continue
            if self_doc_id is not None and v.document_id == self_doc_id:
                continue
            # Single-version filter (the merge-source eligibility constraint)
            chain = await self.version_repo.find_by_document_id(v.document_id)
            if len(chain) != 1:
                continue
            out.append(
                SimilarCandidateEntry(
                    target_document_id=v.document_id,
                    title=c.file_name,
                    doc_code=getattr(c, "file_encoding", None),
                    current_primary_version_no=v.version_no,
                    similarity=sim,
                    primary_uploader_name=getattr(c, "user_name", None),
                    primary_upload_time=getattr(c, "create_time", None),
                )
            )
        return out

    async def search_version_sources(self, knowledge_id: int, keyword: str, current_file_id: int):
        return await self._reads().search_version_sources(knowledge_id, keyword, current_file_id)

    async def merge_source_document_into_current(self, current_knowledge_file_id: int, source_document_id: int):
        """Absorb an independent source using the original qualification and response."""
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import LinkResponse
        from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import (
            KnowledgeAuditTelemetryService,
        )

        result = await self._mutations().amerge_document(
            login_user=self.login_user,
            current_knowledge_file_id=current_knowledge_file_id,
            source_document_id=source_document_id,
        )
        KnowledgeAuditTelemetryService.audit_link_file_version(
            self.login_user, self.request, result.knowledge_id, result.file_name, result.new_version_no
        )
        return LinkResponse(document_id=result.document_id, new_version_no=result.new_version_no)

    async def get_similar_candidates_for_file(
        self,
        knowledge_file_id: int,
        *,
        limit: int = 3,
    ) -> list:
        """Top-N similar candidates above threshold, sorted by similarity desc.

        Each result item is a SimilarCandidateEntry with the candidate's target document info.
        Excludes the candidate's own document (1:1 file→version row); empty if no matches.
        """
        from bisheng.common.utils.simhash_utils import similarity as _similarity
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import SimilarCandidateEntry

        kf = await self.knowledge_file_repo.find_by_id(knowledge_file_id)
        if kf is None or not kf.simhash:
            return []

        conf = await bisheng_settings.async_get_knowledge()
        vmc = getattr(conf, "version_management", None)
        threshold: float = vmc.simhash_similarity_threshold if vmc else 0.85

        # Exclude self-doc to avoid recommending the file's own logical document
        self_v = await self.version_repo.find_by_knowledge_file_id(knowledge_file_id)
        self_doc_id = self_v.document_id if self_v else None

        candidates = await self.knowledge_file_repo.find_main_version_files_in_space(
            knowledge_id=kf.knowledge_id,
            exclude_file_id=knowledge_file_id,
        )

        scored: list[tuple[float, KnowledgeFile]] = []
        for c in candidates:
            if not c.simhash:
                continue
            sim = _similarity(kf.simhash, c.simhash)
            if sim < threshold:
                continue
            scored.append((sim, c))

        # Sort desc by similarity, take top N
        scored.sort(key=lambda x: x[0], reverse=True)
        scored = scored[:limit]

        out: list[SimilarCandidateEntry] = []
        for sim, c in scored:
            v = await self.version_repo.find_by_knowledge_file_id(c.id)
            if v is None:
                continue  # orphaned file — no version row
            if self_doc_id is not None and v.document_id == self_doc_id:
                continue  # exclude the requester's own document
            out.append(
                SimilarCandidateEntry(
                    target_document_id=v.document_id,
                    title=c.file_name,
                    doc_code=getattr(c, "file_encoding", None),
                    current_primary_version_no=v.version_no,
                    similarity=sim,
                    primary_uploader_name=getattr(c, "user_name", None),
                    primary_upload_time=getattr(c, "create_time", None),
                )
            )
        return out
