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
from typing import Awaitable, Callable

from fastapi import HTTPException, Request
from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
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
        """Raise the business-code error if the feature switch is off so the
        client can surface the product-specified Chinese toast instead of being
        bounced to /c/new?error=11403 by the global 403 redirect."""
        from bisheng.common.errcode.knowledge_space import VersionManagementDisabledError

        conf = await bisheng_settings.async_get_knowledge()
        vmc = getattr(conf, "version_management", None)
        if vmc is None or not vmc.enabled:
            raise VersionManagementDisabledError()

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
            # Hide documents whose primary file is gone or has not parsed
            # successfully — they're effectively unusable as a link target
            # and would just trip the link-time guard.
            if kf is None or kf.status != KnowledgeFileStatus.SUCCESS.value:
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

        from bisheng.common.errcode.knowledge_space import (
            VersionLinkFileNotReadyError,
            VersionLinkSourceFileMissingError,
            VersionLinkSourceMultiVersionError,
        )

        # ── Source guard ────────────────────────────────────────────────────
        # Distinguish "file is gone" (deleted between list refresh and click)
        # from "file is still parsing / failed" — they get different product
        # toasts so the user knows whether to retry or pick another file.
        current_kf = await self.knowledge_file_repo.find_by_id(knowledge_file_id)
        if current_kf is None:
            raise VersionLinkSourceFileMissingError()
        if current_kf.status != KnowledgeFileStatus.SUCCESS.value:
            raise VersionLinkFileNotReadyError()

        # 2) source document must not already be a multi-version chain — moving
        #    any of its versions out would break the existing chain.
        source_version = await self.version_repo.find_by_knowledge_file_id(knowledge_file_id)
        if source_version is not None:
            source_chain = await self.version_repo.find_by_document_id(source_version.document_id)
            if len(source_chain) >= 2:
                raise VersionLinkSourceMultiVersionError()

        # ── Target guard ────────────────────────────────────────────────────
        # 1) target document row must exist.
        target_doc = await self.doc_repo.find_by_id(target_document_id)
        if target_doc is None:
            raise VersionLinkTargetUnavailableError()
        # 2) target must have a live primary chain — primary_version_id set,
        #    that version row exists, its knowledge_file row exists, and the
        #    file is parsed SUCCESS. Any link in that chain being broken means
        #    the target is effectively "deleted" from the user's point of view.
        if target_doc.primary_version_id is None:
            raise VersionLinkTargetUnavailableError()
        target_primary_v = await self.version_repo.find_by_id(target_doc.primary_version_id)
        if target_primary_v is None:
            raise VersionLinkTargetUnavailableError()
        target_primary_kf = await self.knowledge_file_repo.find_by_id(
            target_primary_v.knowledge_file_id
        )
        if (
            target_primary_kf is None
            or target_primary_kf.status != KnowledgeFileStatus.SUCCESS.value
        ):
            raise VersionLinkTargetUnavailableError()

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

        # Snapshot the old primary; we'll demote it AFTER the new primary is
        # in place so an interruption never leaves the chain without any
        # primary at all (the worst case here is two primaries, recoverable).
        old_primary = await self.version_repo.find_primary(target_document_id)

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

        # Demote the old primary now — chain is already healthy with the new one.
        if old_primary is not None and old_primary.id != saved.id:
            old_primary.is_primary = False
            await self.version_repo.update(old_primary)

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
            # Promote the new primary BEFORE demoting the old one so that any
            # interruption in the middle leaves the chain with two primaries
            # (recoverable, still visible in the list) instead of the rare
            # "no primary at all" state that hides every file from the UI but
            # keeps them in the dup checker.
            old_primary = await self.version_repo.find_primary(target_version.document_id)
            target_version.is_primary = True
            await self.version_repo.update(target_version)
            await self.doc_repo.update_primary_version_id(target_version.document_id, target_version.id)
            if old_primary is not None and old_primary.id != target_version.id:
                old_primary.is_primary = False
                await self.version_repo.update(old_primary)

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
        if kf is None or not self._has_valid_simhash(getattr(kf, "simhash", None)):
            return 0
        if self._shougang_encoding_first_three_segments(getattr(kf, "file_encoding", None)) is None:
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
            if not self._has_valid_simhash(getattr(c, "simhash", None)):
                continue
            if not self._shougang_encoding_matches(kf, c):
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
            if not candidates:
                kf.similar_status = 0
                await self.knowledge_file_repo.update(kf)
                continue
            out.append(PendingSimilarFileEntry(
                knowledge_file_id=kf.id, file_name=kf.file_name,
                file_code=getattr(kf, "file_encoding", None),
                candidate_count=len(candidates),
                current_primary_version_no=v.version_no if v else 1,
                primary_uploader_name=kf.user_name,
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
        if kf is None or not self._has_valid_simhash(getattr(kf, "simhash", None)):
            return []
        if self._shougang_encoding_first_three_segments(getattr(kf, "file_encoding", None)) is None:
            return []

        conf = await bisheng_settings.async_get_knowledge()
        vmc = getattr(conf, "version_management", None)
        threshold: float = vmc.simhash_similarity_threshold if vmc else 0.85

        self_v = await self.version_repo.find_by_knowledge_file_id(current_file_id)
        self_doc_id = self_v.document_id if self_v else None

        candidates = await self.knowledge_file_repo.find_main_version_files_in_space(
            knowledge_id=kf.knowledge_id, exclude_file_id=current_file_id,
        )

        scored: list[tuple[float, KnowledgeFile]] = []
        for c in candidates:
            if not self._has_valid_simhash(getattr(c, "simhash", None)):
                continue
            if not self._shougang_encoding_matches(kf, c):
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

    async def search_version_sources(
        self,
        knowledge_id: int,
        keyword: str,
        current_file_id: int,
    ):
        """Keyword-search single-version documents in a space — for the version
        management merge selection. Identical to search_associable_documents but
        additionally excludes multi-version documents.
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
            chain = await self.version_repo.find_by_document_id(doc.id)
            if len(chain) != 1:
                continue
            primary_v = chain[0]
            kf = await self.knowledge_file_repo.find_by_id(primary_v.knowledge_file_id)
            # Hide documents whose primary file is gone or has not parsed
            # successfully — they're effectively unusable as a link target
            # and would just trip the link-time guard.
            if kf is None or kf.status != KnowledgeFileStatus.SUCCESS.value:
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

    @staticmethod
    def _has_valid_simhash(simhash: str | None) -> bool:
        return bool(simhash) and simhash != "0" * 16

    @staticmethod
    def _shougang_encoding_first_three_segments(file_encoding: str | None) -> tuple[str, str, str] | None:
        parts = [part.strip() for part in (file_encoding or "").split("-")]
        if len(parts) < 3 or not all(parts[:3]):
            return None
        return parts[0], parts[1], parts[2]

    @classmethod
    def _shougang_encoding_matches(cls, source_file: KnowledgeFile, candidate_file: KnowledgeFile) -> bool:
        source_encoding_key = cls._shougang_encoding_first_three_segments(
            getattr(source_file, "file_encoding", None)
        )
        if source_encoding_key is None:
            return False
        return (
            cls._shougang_encoding_first_three_segments(
                getattr(candidate_file, "file_encoding", None)
            )
            == source_encoding_key
        )

    async def search_shougang_publish_version_sources(
        self,
        knowledge_id: int,
        keyword: str,
        current_file_id: int,
        *,
        can_view_file: Callable[[int], Awaitable[bool]] | None = None,
    ):
        """Search target documents for Shougang publish version linking.

        This is intentionally separate from the generic version-management search
        so Shougang file-level permission filtering does not change Bisheng's
        original version-management behavior.
        """
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import ShougangFilePublishDocumentEntry

        docs = await self.doc_repo.find_by_knowledge_id(knowledge_id)
        current_v = await self.version_repo.find_by_knowledge_file_id(current_file_id)
        self_doc_id = current_v.document_id if current_v else None

        keyword_lower = (keyword or "").strip().lower()
        out: list[ShougangFilePublishDocumentEntry] = []
        versioned_file_ids: set[int] = set()
        for doc in docs:
            if doc.id == self_doc_id:
                continue
            if doc.primary_version_id is None:
                continue
            chain = await self.version_repo.find_by_document_id(doc.id)
            if len(chain) != 1:
                continue
            primary_v = chain[0]
            kf = await self.knowledge_file_repo.find_by_id(primary_v.knowledge_file_id)
            if kf is None or kf.status != KnowledgeFileStatus.SUCCESS.value:
                continue
            versioned_file_ids.add(int(kf.id))
            if can_view_file is not None and not await can_view_file(int(kf.id)):
                continue
            haystack = " ".join([
                kf.file_name or "",
                getattr(kf, "file_encoding", "") or "",
            ]).lower()
            if keyword_lower and keyword_lower not in haystack:
                continue
            out.append(ShougangFilePublishDocumentEntry(
                document_id=doc.id, title=kf.file_name,
                doc_code=getattr(kf, "file_encoding", None),
                current_primary_version_no=primary_v.version_no,
                primary_uploader_name=kf.user_name,
                primary_upload_time=kf.create_time,
            ))

        if hasattr(self.knowledge_file_repo, "find_success_files_in_space"):
            files = await self.knowledge_file_repo.find_success_files_in_space(
                knowledge_id=knowledge_id,
                exclude_file_id=current_file_id,
            )
        else:
            files = await self.knowledge_file_repo.find_all(knowledge_id=knowledge_id)
        for kf in files:
            if int(kf.id) == int(current_file_id):
                continue
            if int(kf.id) in versioned_file_ids:
                continue
            if kf.file_type != FileType.FILE.value:
                continue
            if kf.status != KnowledgeFileStatus.SUCCESS.value:
                continue
            existing_version = await self.version_repo.find_by_knowledge_file_id(int(kf.id))
            if existing_version is not None:
                continue
            if can_view_file is not None and not await can_view_file(int(kf.id)):
                continue
            haystack = " ".join([
                kf.file_name or "",
                getattr(kf, "file_encoding", "") or "",
            ]).lower()
            if keyword_lower and keyword_lower not in haystack:
                continue
            out.append(ShougangFilePublishDocumentEntry(
                document_id=None,
                target_file_id=int(kf.id),
                title=kf.file_name,
                doc_code=getattr(kf, "file_encoding", None),
                current_primary_version_no=1,
                primary_uploader_name=kf.user_name,
                primary_upload_time=kf.create_time,
            ))
        return out

    async def ensure_shougang_publish_document_for_file(self, knowledge_file_id: int) -> int:
        """Create the missing V1 document chain for a Shougang publish target file."""
        await self._require_version_management_enabled()

        from bisheng.common.errcode.knowledge_space import VersionLinkTargetUnavailableError

        kf = await self.knowledge_file_repo.find_by_id(knowledge_file_id)
        if (
            kf is None
            or kf.file_type != FileType.FILE.value
            or kf.status != KnowledgeFileStatus.SUCCESS.value
        ):
            raise VersionLinkTargetUnavailableError()

        existing_version = await self.version_repo.find_by_knowledge_file_id(knowledge_file_id)
        if existing_version is not None:
            doc = await self.doc_repo.find_by_id(existing_version.document_id)
            if doc is None:
                raise VersionLinkTargetUnavailableError()
            return int(existing_version.document_id)

        doc = await self.doc_repo.save(KnowledgeDocument(
            knowledge_id=int(kf.knowledge_id),
            file_level_path=getattr(kf, "file_level_path", None),
            level=getattr(kf, "level", 0),
        ))
        version = await self.version_repo.save(KnowledgeDocumentVersion(
            document_id=int(doc.id),
            knowledge_file_id=int(kf.id),
            version_no=1,
            is_primary=True,
        ))
        await self.doc_repo.update_primary_version_id(int(doc.id), int(version.id))
        return int(doc.id)

    async def merge_source_document_into_current(
        self,
        current_knowledge_file_id: int,
        source_document_id: int,
    ):
        """Merge a single-version source document into the current file's document
        chain. The source's V1 file becomes the new primary version of the current
        document; the source document row is deleted.

        Reverse direction of link_file_to_document — used by the version management
        flow where the user picks a single-version target to absorb into the file
        they are managing.
        """
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import LinkResponse
        from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import (
            KnowledgeAuditTelemetryService,
        )

        await self._require_version_management_enabled()

        from bisheng.common.errcode.knowledge_space import (
            VersionLinkFileNotReadyError,
            VersionLinkSourceFileMissingError,
            VersionLinkSourceMultiVersionError,
        )

        # ── Current (the file the user is managing) guard ───────────────────
        # Same split as link_file_to_document: deleted vs. not-yet-parsed get
        # different toasts.
        current_kf = await self.knowledge_file_repo.find_by_id(current_knowledge_file_id)
        if current_kf is None:
            raise VersionLinkSourceFileMissingError()
        if current_kf.status != KnowledgeFileStatus.SUCCESS.value:
            raise VersionLinkFileNotReadyError()

        current_v = await self.version_repo.find_by_knowledge_file_id(current_knowledge_file_id)
        if current_v is None:
            # Current file is not in any chain — treat as not-ready for version mgmt.
            raise VersionLinkFileNotReadyError()
        target_doc_id = current_v.document_id

        # ── Source (the document being absorbed) guard ──────────────────────
        # In the merge flow the user picks a *file* from the similar/search
        # list, so "source missing" is the user's mental model when any of
        # these checks fail — surface 18064 "source file deleted" rather than
        # 18062 "target document unavailable" (which is link-flow language).
        source_doc = await self.doc_repo.find_by_id(source_document_id)
        if source_doc is None:
            # Cascade-on-delete (the new code path) removes the doc when the
            # primary file is deleted in another tab.
            raise VersionLinkSourceFileMissingError()
        if source_doc.knowledge_id != current_kf.knowledge_id:
            raise HTTPException(
                status_code=409, detail="source document belongs to a different space",
            )

        source_chain = await self.version_repo.find_by_document_id(source_document_id)
        # Multi-version source: same product rule as link — a multi-version
        # document cannot be absorbed into another chain.
        if len(source_chain) >= 2:
            raise VersionLinkSourceMultiVersionError()
        if len(source_chain) == 0:
            # Doc row survived but every version is gone — file was deleted.
            raise VersionLinkSourceFileMissingError()
        source_version = source_chain[0]
        source_kf = await self.knowledge_file_repo.find_by_id(source_version.knowledge_file_id)
        if source_kf is None:
            raise VersionLinkSourceFileMissingError()
        if source_kf.status != KnowledgeFileStatus.SUCCESS.value:
            # File still around but not finished parsing.
            raise VersionLinkFileNotReadyError()
        # Version linking is a deliberate, user-driven action: the user manually
        # searches for and picks the document to merge. We therefore do NOT gate
        # the link on content/encoding similarity — any parsed document the user
        # selects may be linked. (The md5 duplicate guard below still prevents
        # linking byte-identical content twice into the same chain.)

        existing = await self.version_repo.find_by_document_id(target_doc_id)
        existing_kf_ids = [v.knowledge_file_id for v in existing]
        existing_kfs = await self.knowledge_file_repo.find_by_ids(existing_kf_ids)
        if source_kf.md5 and any(kf.md5 == source_kf.md5 for kf in existing_kfs if kf.md5):
            raise HTTPException(status_code=409, detail="duplicate content already in current chain")

        # Promote-before-demote: an interruption mid-flow leaves the chain
        # with two primaries (recoverable) instead of none (which would hide
        # every file from the UI while still blocking dup uploads).
        old_primary = await self.version_repo.find_primary(target_doc_id)

        next_no = await self.version_repo.next_version_no(target_doc_id)
        new_version = KnowledgeDocumentVersion(
            document_id=target_doc_id,
            knowledge_file_id=source_kf.id,
            version_no=next_no,
            is_primary=True,
        )
        saved = await self.version_repo.save(new_version)

        await self.doc_repo.update_primary_version_id(target_doc_id, saved.id)

        if old_primary is not None and old_primary.id != saved.id:
            old_primary.is_primary = False
            await self.version_repo.update(old_primary)

        if source_version.id != saved.id:
            await self.version_repo.delete(source_version.id)
            await self.doc_repo.delete(source_document_id)

        if source_kf.similar_status != 2:
            source_kf.similar_status = 2
            await self.knowledge_file_repo.update(source_kf)

        KnowledgeAuditTelemetryService.audit_link_file_version(
            self.login_user, self.request, current_kf.knowledge_id, source_kf.file_name, next_no,
        )

        return LinkResponse(document_id=target_doc_id, new_version_no=next_no)

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
        if kf is None or not self._has_valid_simhash(getattr(kf, "simhash", None)):
            return []
        if self._shougang_encoding_first_three_segments(getattr(kf, "file_encoding", None)) is None:
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
            if not self._has_valid_simhash(getattr(c, "simhash", None)):
                continue
            if not self._shougang_encoding_matches(kf, c):
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

    async def get_similar_candidates_for_file_in_space(
        self,
        knowledge_file_id: int,
        target_knowledge_id: int,
        *,
        limit: int = 10,
    ) -> list:
        """Return similar primary documents from a target knowledge space."""
        from bisheng.common.utils.simhash_utils import similarity as _similarity
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import SimilarCandidateEntry

        kf = await self.knowledge_file_repo.find_by_id(knowledge_file_id)
        if kf is None or not self._has_valid_simhash(getattr(kf, "simhash", None)):
            return []
        if self._shougang_encoding_first_three_segments(getattr(kf, "file_encoding", None)) is None:
            return []

        conf = await bisheng_settings.async_get_knowledge()
        vmc = getattr(conf, "version_management", None)
        threshold: float = vmc.simhash_similarity_threshold if vmc else 0.85

        self_v = await self.version_repo.find_by_knowledge_file_id(knowledge_file_id)
        self_doc_id = self_v.document_id if self_v else None
        candidates = await self.knowledge_file_repo.find_main_version_files_in_space(
            knowledge_id=target_knowledge_id,
            exclude_file_id=knowledge_file_id,
        )

        scored: list[tuple[float, KnowledgeFile]] = []
        for candidate in candidates:
            if not self._has_valid_simhash(getattr(candidate, "simhash", None)):
                continue
            if not self._shougang_encoding_matches(kf, candidate):
                continue
            sim = _similarity(kf.simhash, candidate.simhash)
            if sim >= threshold:
                scored.append((sim, candidate))
        scored.sort(key=lambda item: item[0], reverse=True)

        out: list[SimilarCandidateEntry] = []
        for sim, candidate in scored[:limit]:
            version = await self.version_repo.find_by_knowledge_file_id(candidate.id)
            if version is None:
                continue
            if self_doc_id is not None and version.document_id == self_doc_id:
                continue
            out.append(
                SimilarCandidateEntry(
                    target_document_id=version.document_id,
                    title=candidate.file_name,
                    doc_code=getattr(candidate, "file_encoding", None),
                    current_primary_version_no=version.version_no,
                    similarity=sim,
                    primary_uploader_name=getattr(candidate, "user_name", None),
                    primary_upload_time=getattr(candidate, "create_time", None),
                )
            )
        return out

    async def get_shougang_publish_similar_candidates_for_file_in_space(
        self,
        knowledge_file_id: int,
        target_knowledge_id: int,
        *,
        limit: int = 10,
        can_view_file: Callable[[int], Awaitable[bool]] | None = None,
    ) -> list:
        """Return Shougang publish candidates from a target space.

        Shougang matching is stricter than Bisheng's generic recommendation:
        file_encoding COMPANY/DOCTYPE/DOMAIN must match first, then SimHash must
        meet the configured threshold. The optional permission callback keeps
        caller-specific file visibility out of the generic repository query.
        """
        from bisheng.common.utils.simhash_utils import similarity as _similarity
        from bisheng.knowledge.domain.schemas.knowledge_version_schema import SimilarCandidateEntry

        kf = await self.knowledge_file_repo.find_by_id(knowledge_file_id)
        if kf is None or not self._has_valid_simhash(getattr(kf, "simhash", None)):
            return []
        if self._shougang_encoding_first_three_segments(getattr(kf, "file_encoding", None)) is None:
            return []

        conf = await bisheng_settings.async_get_knowledge()
        vmc = getattr(conf, "version_management", None)
        threshold: float = vmc.simhash_similarity_threshold if vmc else 0.85

        self_v = await self.version_repo.find_by_knowledge_file_id(knowledge_file_id)
        self_doc_id = self_v.document_id if self_v else None
        candidates = await self.knowledge_file_repo.find_main_version_files_in_space(
            knowledge_id=target_knowledge_id,
            exclude_file_id=knowledge_file_id,
        )

        scored: list[tuple[float, KnowledgeFile]] = []
        for candidate in candidates:
            if not self._has_valid_simhash(getattr(candidate, "simhash", None)):
                continue
            if not self._shougang_encoding_matches(kf, candidate):
                continue
            if can_view_file is not None and not await can_view_file(int(candidate.id)):
                continue
            sim = _similarity(kf.simhash, candidate.simhash)
            if sim >= threshold:
                scored.append((sim, candidate))
        scored.sort(key=lambda item: item[0], reverse=True)

        out: list[SimilarCandidateEntry] = []
        for sim, candidate in scored[:limit]:
            version = await self.version_repo.find_by_knowledge_file_id(candidate.id)
            if version is None:
                continue
            if self_doc_id is not None and version.document_id == self_doc_id:
                continue
            out.append(
                SimilarCandidateEntry(
                    target_document_id=version.document_id,
                    title=candidate.file_name,
                    doc_code=getattr(candidate, "file_encoding", None),
                    current_primary_version_no=version.version_no,
                    similarity=sim,
                    primary_uploader_name=getattr(candidate, "user_name", None),
                    primary_upload_time=getattr(candidate, "create_time", None),
                )
            )
        return out
