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
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeState, KnowledgeTypeEnum
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
from bisheng.permission.application.business_authorization import require_business_action


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

    async def _require_knowledge(self, knowledge_id: int, action: str | None = None, *, allow_failed: bool = False):
        """Resolve the real container before authorization, including admin shortcuts.

        Document and version rows have no tenant column. Their presence is not
        authority to read or mutate them.
        """
        knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
        if (
            knowledge is None
            or knowledge.id != knowledge_id
            or knowledge.tenant_id != get_current_tenant_id()
            or (
                knowledge.state not in {KnowledgeState.PUBLISHED.value, KnowledgeState.REBUILDING.value}
                and not (allow_failed and knowledge.state == KnowledgeState.FAILED.value)
            )
            or knowledge.type not in {KnowledgeTypeEnum.SPACE.value, KnowledgeTypeEnum.NORMAL.value}
        ):
            raise HTTPException(status_code=404, detail="knowledge not found")
        if action is not None:
            await require_business_action(
                self.login_user,
                resource_type=(
                    "knowledge_space" if knowledge.type == KnowledgeTypeEnum.SPACE.value else "knowledge_library"
                ),
                resource_id=knowledge.id,
                action=action,
            )
        return knowledge

    async def _require_file(
        self, file_id: int, action: str | None = None, *, knowledge_id: int | None = None, allow_failed: bool = False
    ):
        kf = await self.knowledge_file_repo.find_by_id(file_id)
        if kf is None or kf.id != file_id or kf.tenant_id != get_current_tenant_id():
            raise HTTPException(status_code=404, detail="file not found")
        if knowledge_id is not None and kf.knowledge_id != knowledge_id:
            raise HTTPException(status_code=409, detail="file belongs to a different knowledge")
        await self._require_knowledge(kf.knowledge_id, "edit" if action == "edit" else None, allow_failed=allow_failed)
        if action == "visible":
            await require_business_action(
                self.login_user,
                resource_type="knowledge_file",
                resource_id=kf.id,
                action="visible",
            )
        return kf

    async def _require_version(
        self, version, *, knowledge_id: int | None = None, action: str | None = None, allow_failed: bool = False
    ):
        if version is None:
            raise HTTPException(status_code=404, detail="version not found")
        doc = await self.doc_repo.find_by_id(version.document_id)
        if doc is None or doc.id != version.document_id:
            raise HTTPException(status_code=404, detail="document not found")
        if knowledge_id is not None and doc.knowledge_id != knowledge_id:
            raise HTTPException(status_code=409, detail="document belongs to a different knowledge")
        kf = await self._require_file(
            version.knowledge_file_id, action, knowledge_id=doc.knowledge_id, allow_failed=allow_failed
        )
        return doc, kf

    async def _require_chain(
        self, document_id: int, *, knowledge_id: int, action: str | None = None, allow_failed: bool = False
    ):
        doc = await self.doc_repo.find_by_id(document_id)
        if doc is None or doc.id != document_id or doc.knowledge_id != knowledge_id:
            raise HTTPException(status_code=409, detail="invalid document knowledge relationship")
        versions = await self.version_repo.find_by_document_id(document_id)
        if doc.primary_version_id is not None and not any(v.id == doc.primary_version_id for v in versions):
            raise HTTPException(status_code=409, detail="invalid primary version relationship")
        for version in versions:
            if version.document_id != document_id:
                raise HTTPException(status_code=409, detail="version belongs to a different document")
            await self._require_version(version, knowledge_id=knowledge_id, action=action, allow_failed=allow_failed)
        return versions

    def _reads(self):
        if self._version_read_service is None:
            from bisheng.knowledge.domain.services.knowledge_version_read_service import KnowledgeVersionReadService

            self._version_read_service = KnowledgeVersionReadService(self.request, self.login_user)
        return self._version_read_service

    async def search_candidates_page(
        self, *, knowledge_id, keyword, current_file_id, page_size=40, cursor=None, source_only=False
    ):
        await self._require_knowledge(knowledge_id, "visible")
        if current_file_id:
            await self._require_file(current_file_id, "visible", knowledge_id=knowledge_id)
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
        version = await self.version_repo.find_by_knowledge_file_id(knowledge_file_id)
        if version is None:
            raise HTTPException(status_code=404, detail="version chain not found for this file")
        doc, _ = await self._require_version(version, action="visible")
        await self._require_chain(version.document_id, knowledge_id=doc.knowledge_id, action="visible")
        try:
            return await self._reads().list_versions_for_file(knowledge_file_id)
        except SpaceFileNotFoundError as error:
            raise HTTPException(status_code=404, detail="version chain not found for this file") from error

    async def search_associable_documents(self, knowledge_id: int, keyword: str, current_file_id: int):
        await self._require_knowledge(knowledge_id, "visible")
        if current_file_id:
            await self._require_file(current_file_id, "visible", knowledge_id=knowledge_id)
            current_version = await self.version_repo.find_by_knowledge_file_id(current_file_id)
            if current_version is not None:
                await self._require_version(current_version, knowledge_id=knowledge_id)
        return await self._reads().search_associable_documents(knowledge_id, keyword, current_file_id)

    def _mutations(self):
        if self.version_mutation_application is None:
            raise RuntimeError("Version mutation application is not configured")
        return self.version_mutation_application

    async def link_file_to_document(self, knowledge_file_id: int, target_document_id: int):
        """Relink the complete chain in one application-owned transaction."""
        await self._require_version_management_enabled()
        current_kf = await self._require_file(knowledge_file_id, "edit")
        source_version = await self.version_repo.find_by_knowledge_file_id(knowledge_file_id)
        if source_version is not None:
            await self._require_version(source_version, knowledge_id=current_kf.knowledge_id)
            source_chain = await self._require_chain(source_version.document_id, knowledge_id=current_kf.knowledge_id)
            if len(source_chain) >= 2:
                raise HTTPException(status_code=409, detail="source file is already in a multi-version document")
        target_doc = await self.doc_repo.find_by_id(target_document_id)
        if target_doc is None or target_doc.knowledge_id != current_kf.knowledge_id:
            raise HTTPException(status_code=404, detail="target document not found")
        if target_doc.primary_version_id is None:
            raise HTTPException(status_code=409, detail="target document has no primary version")
        target_primary = await self.version_repo.find_by_id(target_doc.primary_version_id)
        await self._require_version(target_primary, knowledge_id=current_kf.knowledge_id, action="edit")
        if source_version is not None and source_version.document_id == target_document_id:
            raise HTTPException(status_code=409, detail="file is already in the target document")
        await self._require_chain(target_document_id, knowledge_id=current_kf.knowledge_id)
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
        await self._require_version_management_enabled()
        target_version = await self.version_repo.find_by_id(version_id)
        target_doc, _ = await self._require_version(target_version, action="edit")
        await self._require_chain(target_doc.id, knowledge_id=target_doc.knowledge_id)
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
        # Failed containers must remain physically cleanable, never readable or relinkable.
        doc, _ = await self._require_version(version, action="edit", allow_failed=True)
        await self._require_chain(doc.id, knowledge_id=doc.knowledge_id, allow_failed=True)
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

        kf = await self._require_file(knowledge_file_id, "edit")
        self_version = await self.version_repo.find_by_knowledge_file_id(knowledge_file_id)
        if self_version is not None:
            await self._require_version(self_version, knowledge_id=kf.knowledge_id)
        if not kf.simhash:
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

        Candidate counts share one space scan. A multi-version document is no
        longer an independent document that needs the link-or-dismiss decision.
        The count stays capped at the right panel's limit of 3.
        """

        conf = await bisheng_settings.async_get_knowledge()
        vmc = getattr(conf, "version_management", None)
        return await self._reads().list_pending_similar(
            knowledge_id,
            threshold=vmc.simhash_similarity_threshold if vmc else 0.85,
        )

    async def dismiss_similar(self, knowledge_file_id: int):
        """User chose 'don't link'. Set similar_status=2 + audit log."""
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import DismissSimilarResponse
        from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import (
            KnowledgeAuditTelemetryService,
        )

        await self._require_version_management_enabled()

        kf = await self._require_file(knowledge_file_id, "edit")
        version = await self.version_repo.find_by_knowledge_file_id(knowledge_file_id)
        if version is not None:
            await self._require_version(version, knowledge_id=kf.knowledge_id)

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
        """Original recommendation ranking with the shared visible-read contract."""
        kf = await self._require_file(current_file_id, "visible")
        self_version = await self.version_repo.find_by_knowledge_file_id(current_file_id)
        if self_version is not None:
            await self._require_version(self_version, knowledge_id=kf.knowledge_id)
        conf = await bisheng_settings.async_get_knowledge()
        vmc = getattr(conf, "version_management", None)
        return await self._reads().similar_candidates(
            current_file_id, threshold=vmc.simhash_similarity_threshold if vmc else 0.85, limit=limit, source_only=True
        )

    async def search_version_sources(self, knowledge_id: int, keyword: str, current_file_id: int):
        await self._require_knowledge(knowledge_id, "visible")
        if current_file_id:
            await self._require_file(current_file_id, "visible", knowledge_id=knowledge_id)
            current_version = await self.version_repo.find_by_knowledge_file_id(current_file_id)
            if current_version is not None:
                await self._require_version(current_version, knowledge_id=knowledge_id)
        return await self._reads().search_version_sources(knowledge_id, keyword, current_file_id)

    async def merge_source_document_into_current(self, current_knowledge_file_id: int, source_document_id: int):
        """Absorb an independent source using the original qualification and response."""
        await self._require_version_management_enabled()
        current_version = await self.version_repo.find_by_knowledge_file_id(current_knowledge_file_id)
        current_doc, _ = await self._require_version(current_version, action="edit")
        if current_doc.id == source_document_id:
            raise HTTPException(status_code=409, detail="source document is the current document")
        source_version = await self.version_repo.find_by_document_id(source_document_id)
        if source_version:
            await self._require_version(source_version[0], knowledge_id=current_doc.knowledge_id, action="edit")
        await self._require_chain(current_doc.id, knowledge_id=current_doc.knowledge_id)
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
        """Original similar-file protocol with the shared visible-read contract."""
        kf = await self._require_file(knowledge_file_id, "visible")
        self_version = await self.version_repo.find_by_knowledge_file_id(knowledge_file_id)
        if self_version is not None:
            await self._require_version(self_version, knowledge_id=kf.knowledge_id)
        conf = await bisheng_settings.async_get_knowledge()
        vmc = getattr(conf, "version_management", None)
        return await self._reads().similar_candidates(
            knowledge_file_id, threshold=vmc.simhash_similarity_threshold if vmc else 0.85, limit=limit
        )
