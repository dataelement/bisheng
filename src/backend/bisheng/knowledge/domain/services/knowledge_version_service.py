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

import asyncio

from fastapi import HTTPException, Request
from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_repository import (
    KnowledgeDocumentRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
    KnowledgeDocumentVersionRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import (
    KnowledgeFileRepository,
)


class KnowledgeVersionService:
    """Business service for the file version management feature."""

    def __init__(
        self,
        request: Request,
        login_user: UserPayload,
        doc_repo: KnowledgeDocumentRepository,
        version_repo: KnowledgeDocumentVersionRepository,
        knowledge_file_repo: KnowledgeFileRepository,
    ):
        self.request = request
        self.login_user = login_user
        self.doc_repo = doc_repo
        self.version_repo = version_repo
        self.knowledge_file_repo = knowledge_file_repo

    async def _require_version_management_enabled(self) -> None:
        """Raise 403 if the feature switch is off."""
        conf = await bisheng_settings.async_get_knowledge()
        vmc = getattr(conf, "version_management", None)
        if vmc is None or not vmc.enabled:
            raise HTTPException(status_code=403, detail="version management is disabled")

    async def list_versions_for_file(self, knowledge_file_id: int):
        """Return the entire version chain that contains the given physical file."""
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import (
            VersionEntry, VersionListResponse,
        )
        v = await self.version_repo.find_by_knowledge_file_id(knowledge_file_id)
        if v is None:
            raise HTTPException(status_code=404, detail="version chain not found for this file")
        doc = await self.doc_repo.find_by_id(v.document_id)
        versions = await self.version_repo.find_by_document_id(v.document_id)

        kf_ids = [vv.knowledge_file_id for vv in versions]
        kfs = await self.knowledge_file_repo.find_by_ids(kf_ids)
        kf_by_id = {kf.id: kf for kf in kfs}

        primary = next((vv for vv in versions if vv.is_primary), None)
        primary_kf = kf_by_id.get(primary.knowledge_file_id) if primary else None
        title = primary_kf.file_name if primary_kf else (
            kf_by_id[versions[0].knowledge_file_id].file_name if versions else ""
        )
        doc_code = getattr(primary_kf, "file_encoding", None) if primary_kf else None

        entries: list[VersionEntry] = []
        for vv in versions:
            kf = kf_by_id.get(vv.knowledge_file_id)
            entries.append(VersionEntry(
                version_id=vv.id, version_no=vv.version_no, is_primary=vv.is_primary,
                knowledge_file_id=vv.knowledge_file_id,
                original_file_name=kf.file_name if kf else "",
                file_code=getattr(kf, "file_encoding", None) if kf else None,
                uploader_name=kf.user_name if kf else None,
                uploader_id=kf.user_id if kf else None,
                upload_time=kf.create_time if kf else None,
                status=kf.status if kf else None,
            ))
        return VersionListResponse(
            document_id=doc.id, knowledge_id=doc.knowledge_id,
            title=title, doc_code=doc_code,
            current_primary_version_no=primary.version_no if primary else None,
            versions=entries,
        )

    async def search_associable_documents(
        self, knowledge_id: int, keyword: str, current_file_id: int,
    ):
        """Search documents in a space that the current file could be associated into.

        Returns documents matching the keyword on either the primary file's name or its
        file_encoding (used as 文件编码). Excludes the document that current_file_id belongs to.
        """
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import AssociableDocumentEntry
        docs = await self.doc_repo.find_by_knowledge_id(knowledge_id)

        current_v = await self.version_repo.find_by_knowledge_file_id(current_file_id)
        self_doc_id = current_v.document_id if current_v else None

        keyword_lower = (keyword or "").strip().lower()
        out: list[AssociableDocumentEntry] = []
        for doc in docs:
            if doc.id == self_doc_id:
                continue
            if doc.primary_version_id is None:
                continue
            primary_v = await self.version_repo.find_by_id(doc.primary_version_id)
            if primary_v is None:
                continue
            kf = await self.knowledge_file_repo.find_by_id(primary_v.knowledge_file_id)
            if kf is None:
                continue
            haystack = " ".join([
                kf.file_name or "",
                getattr(kf, "file_encoding", "") or "",
            ]).lower()
            if keyword_lower and keyword_lower not in haystack:
                continue
            out.append(AssociableDocumentEntry(
                document_id=doc.id, title=kf.file_name,
                doc_code=getattr(kf, "file_encoding", None),
                current_primary_version_no=primary_v.version_no,
                primary_uploader_name=kf.user_name,
                primary_upload_time=kf.create_time,
            ))
        return out

    async def link_file_to_document(self, knowledge_file_id: int, target_document_id: int):
        """Associate a parsed file into a target document's chain.

        Per product decision (2026-05-20 evt 3): the new version becomes the primary
        version immediately. The old primary is demoted to history. The current file's
        original independent document + V1 row are deleted (no追溯 retention needed —
        the file information lives in the new version row via the join).
        """
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import LinkResponse
        from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import (
            KnowledgeAuditTelemetryService,
        )

        await self._require_version_management_enabled()

        current_kf = await self.knowledge_file_repo.find_by_id(knowledge_file_id)
        if current_kf is None:
            raise HTTPException(status_code=404, detail="current file not found")
        if current_kf.status != KnowledgeFileStatus.SUCCESS.value:
            raise HTTPException(status_code=412, detail="current file must be successfully parsed")

        target_doc = await self.doc_repo.find_by_id(target_document_id)
        if target_doc is None:
            raise HTTPException(status_code=404, detail="target document not found")
        if target_doc.knowledge_id != current_kf.knowledge_id:
            raise HTTPException(status_code=409, detail="target document belongs to a different space")

        # Duplicate-content check: does any existing version in the target chain share md5?
        existing = await self.version_repo.find_by_document_id(target_document_id)
        existing_kf_ids = [v.knowledge_file_id for v in existing]
        existing_kfs = await self.knowledge_file_repo.find_by_ids(existing_kf_ids)
        if current_kf.md5 and any(kf.md5 == current_kf.md5 for kf in existing_kfs if kf.md5):
            raise HTTPException(status_code=409, detail="duplicate content already in target chain")

        # Capture the current file's original document (it will be deleted after relink)
        original_chain = await self.version_repo.find_by_knowledge_file_id(knowledge_file_id)

        # Demote old primary
        old_primary = await self.version_repo.find_primary(target_document_id)
        if old_primary is not None:
            old_primary.is_primary = False
            await self.version_repo.update(old_primary)

        # Create new version (auto-primary)
        next_no = await self.version_repo.next_version_no(target_document_id)
        new_version = KnowledgeDocumentVersion(
            document_id=target_document_id,
            knowledge_file_id=knowledge_file_id,
            version_no=next_no,
            is_primary=True,
        )
        saved = await self.version_repo.save(new_version)

        # Point target doc's primary_version_id at the new version
        await self.doc_repo.update_primary_version_id(target_document_id, saved.id)

        # Delete current file's ORIGINAL independent document + V1 row (use the captured id;
        # it may now be ambiguous with the freshly-created row we just inserted).
        if original_chain is not None and original_chain.id != saved.id:
            original_doc_id = original_chain.document_id
            await self.version_repo.delete(original_chain.id)
            await self.doc_repo.delete(original_doc_id)

        # Mark file similar_status as resolved (Plan 3 sets this proactively; we ensure it here too)
        if current_kf.similar_status != 2:
            current_kf.similar_status = 2
            await self.knowledge_file_repo.update(current_kf)

        # Audit log
        KnowledgeAuditTelemetryService.audit_link_file_version(
            self.login_user, self.request, current_kf.knowledge_id, current_kf.file_name, next_no,
        )

        return LinkResponse(document_id=target_document_id, new_version_no=next_no)

    async def set_primary_version(self, version_id: int):
        """Promote a historical version to primary; demote the old primary to history.

        Index is NOT rebuilt — the RAG filter (Plan 4) uses is_primary to decide what's live,
        so flipping the flag is sufficient and the change takes effect immediately.
        """
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import SetPrimaryResponse
        from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import (
            KnowledgeAuditTelemetryService,
        )

        await self._require_version_management_enabled()

        target_version = await self.version_repo.find_by_id(version_id)
        if target_version is None:
            raise HTTPException(status_code=404, detail="version not found")

        target_kf = await self.knowledge_file_repo.find_by_id(target_version.knowledge_file_id)
        if target_kf is None or target_kf.status != KnowledgeFileStatus.SUCCESS.value:
            raise HTTPException(status_code=412, detail="target version not parsed successfully")

        if not target_version.is_primary:
            old_primary = await self.version_repo.find_primary(target_version.document_id)
            if old_primary is not None and old_primary.id != target_version.id:
                old_primary.is_primary = False
                await self.version_repo.update(old_primary)
            target_version.is_primary = True
            await self.version_repo.update(target_version)
            await self.doc_repo.update_primary_version_id(target_version.document_id, target_version.id)

        KnowledgeAuditTelemetryService.audit_set_primary_version(
            self.login_user, self.request,
            target_kf.knowledge_id, target_kf.file_name, target_version.version_no,
        )
        return SetPrimaryResponse(
            document_id=target_version.document_id,
            new_primary_version_no=target_version.version_no,
        )

    async def delete_version(self, version_id: int):
        """Delete a historical (non-primary) version. Primary version must be promoted first.

        Cleans Milvus/ES chunks and MinIO objects for the deleted file (best-effort).
        """
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import DeleteVersionResponse
        from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import (
            KnowledgeAuditTelemetryService,
        )
        # Deferred import to avoid circular dependency (knowledge_imp imports KnowledgeVersionService
        # at runtime, so top-level import would create a cycle).
        from bisheng.api.services.knowledge_imp import delete_vector_files, delete_minio_files

        await self._require_version_management_enabled()

        v = await self.version_repo.find_by_id(version_id)
        if v is None:
            raise HTTPException(status_code=404, detail="version not found")
        if v.is_primary:
            raise HTTPException(
                status_code=409,
                detail="cannot delete the primary version; promote another version first",
            )

        kf = await self.knowledge_file_repo.find_by_id(v.knowledge_file_id)
        doc_id = v.document_id
        version_no = v.version_no
        kf_knowledge_id = kf.knowledge_id if kf else None
        kf_file_name = kf.file_name if kf else ""

        # Look up the knowledge space BEFORE deleting DB rows so the object is still
        # accessible even if the backing store flushes references on delete.
        knowledge = None
        if kf is not None and kf.knowledge_id is not None:
            knowledge = await KnowledgeDao.aquery_by_id(kf.knowledge_id)

        await self.version_repo.delete(version_id)
        if kf is not None:
            await self.knowledge_file_repo.delete(kf.id)

        # Best-effort cleanup: failures are logged but must not affect DB consistency.
        if kf is not None:
            if knowledge is not None:
                try:
                    await asyncio.to_thread(delete_vector_files, [kf.id], knowledge)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "delete_version: vector cleanup failed for file_id={} knowledge_id={}: {}",
                        kf.id, knowledge.id, exc,
                    )
            try:
                await asyncio.to_thread(delete_minio_files, kf)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "delete_version: MinIO cleanup failed for file_id={}: {}",
                    kf.id, exc,
                )

        KnowledgeAuditTelemetryService.audit_delete_file_version(
            self.login_user, self.request, kf_knowledge_id or 0, kf_file_name, version_no,
        )
        return DeleteVersionResponse(document_id=doc_id, deleted_version_no=version_no)

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
            knowledge_id=kf.knowledge_id, exclude_file_id=knowledge_file_id,
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
            knowledge_id=knowledge_id, similar_status=1,
        )

        out: list[PendingSimilarFileEntry] = []
        for kf in pending:
            # Use the read API to count current candidates above threshold
            candidates = await self.get_similar_candidates_for_file(kf.id, limit=100)
            out.append(PendingSimilarFileEntry(
                knowledge_file_id=kf.id, file_name=kf.file_name,
                file_code=getattr(kf, "file_encoding", None),
                candidate_count=len(candidates),
            ))
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
            self.login_user, self.request, kf.knowledge_id, kf.file_name,
        )
        return DismissSimilarResponse(knowledge_file_id=kf.id, similar_status=2)

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
            knowledge_id=kf.knowledge_id, exclude_file_id=knowledge_file_id,
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
            out.append(SimilarCandidateEntry(
                target_document_id=v.document_id,
                title=c.file_name,
                doc_code=getattr(c, "file_encoding", None),
                current_primary_version_no=v.version_no,
                similarity=sim,
                primary_uploader_name=getattr(c, "user_name", None),
                primary_upload_time=getattr(c, "create_time", None),
            ))
        return out
