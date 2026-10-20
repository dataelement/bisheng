"""只删除没有关联业务的初始接口文件, 不复用版本级联删除。"""

from loguru import logger
from sqlalchemy import delete, or_
from sqlmodel import select

from bisheng.approval.domain.models.approval_instance import ApprovalInstance
from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.review_tags import ReviewTagLink
from bisheng.database.models.tag import TagLink
from bisheng.knowledge.domain.models.department_file_view_grant import DepartmentFileViewGrant
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_file_correction import KnowledgeFileCorrection
from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import KnowledgeFilePdfArtifact
from bisheng.knowledge.domain.models.knowledge_file_similarity_candidate import KnowledgeFileSimilarityCandidate
from bisheng.knowledge.domain.models.portal_recommendation_file_projection import PortalRecommendationFileProjection
from bisheng.knowledge.domain.repositories.implementations.knowledge_background_repository_impl import (
    KnowledgeBackgroundRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.interfaces.unreadable_sync_file_repository import (
    DiscardResult,
    UnreadableSyncFileRepository,
)
from bisheng.knowledge.domain.services.knowledge_source_file_validation import is_sync_file, unreadable_reason


class UnreadableSyncFileRepositoryImpl(BaseRepositoryImpl[KnowledgeFile, int], UnreadableSyncFileRepository):
    def __init__(self, session):
        super().__init__(session, KnowledgeFile)

    def discard(self, file: KnowledgeFile) -> DiscardResult:
        if unreadable_reason(file) is None:
            return "retained"
        current = self.session.exec(select(KnowledgeFile).where(KnowledgeFile.id == file.id).with_for_update()).first()
        if current is None or current.deleted_at is not None:
            return "stale"
        if not is_sync_file(current) or any(
            current.user_metadata.get(key) != file.user_metadata.get(key)
            for key in ("filelib_sync_endpoint", "developer_token_id")
        ):
            return "stale"
        if (current.tenant_id, current.knowledge_id, current.object_name, current.md5) != (
            file.tenant_id,
            file.knowledge_id,
            file.object_name,
            file.md5,
        ) or current.status not in {1, 3}:
            return "stale"
        if any(self._has_content_or_distribution(row) for row in (current, file)):
            return self._retain(file, "content_or_distribution")
        knowledge = self.session.get(Knowledge, current.knowledge_id)
        if knowledge is None or knowledge.tenant_id != current.tenant_id:
            return self._retain(file, "knowledge_mismatch")
        versions = self.session.exec(
            select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.knowledge_file_id == file.id)
        ).all()
        document = None
        if versions:
            if len(versions) != 1:
                return self._retain(file, "ambiguous_version")
            version = versions[0]
            document = self.session.exec(
                select(KnowledgeDocument).where(KnowledgeDocument.id == version.document_id).with_for_update()
            ).first()
            chain = self.session.exec(
                select(KnowledgeDocumentVersion)
                .where(KnowledgeDocumentVersion.document_id == version.document_id)
                .with_for_update()
            ).all()
            if (
                document is None
                or document.tenant_id != current.tenant_id
                or document.knowledge_id != current.knowledge_id
                or document.lifecycle_status != "active"
                or document.content_generation
                or document.predecessor_logic_file_id is not None
                or document.primary_version_id != version.id
                or not version.is_primary
                or version.version_no != 1
                or len(chain) != 1
            ):
                return self._retain(file, "version_history_or_conflict")
        if self._has_references(current, document):
            return self._retain(file, "business_reference")

        artifacts = self.session.exec(
            select(KnowledgeFilePdfArtifact)
            .where(KnowledgeFilePdfArtifact.knowledge_file_id == file.id)
            .with_for_update()
        ).all()
        snapshot = current.model_dump()
        snapshot.update(status=file.status, remark=file.remark)
        # 先建立实际写事务, 确保嵌套的补偿清单与源删除一起回滚。
        current.status, current.remark = file.status, file.remark
        self.session.add(current)
        self.session.flush()
        KnowledgeBackgroundRepositoryImpl(self.session).request_delete(
            tenant_id=int(current.tenant_id),
            knowledge=knowledge,
            files=[snapshot],
            artifacts=[row.model_dump() for row in artifacts],
            cleanup_permissions=True,
        )
        for model in (TagLink, ReviewTagLink):
            self.session.exec(
                delete(model).where(
                    model.resource_id == str(file.id),
                    model.resource_type.in_([ResourceTypeEnum.SPACE_FILE.value, ResourceTypeEnum.KNOWLEDGE_FILE.value]),
                )
            )
        self.session.exec(
            delete(KnowledgeFileSimilarityCandidate).where(
                or_(
                    KnowledgeFileSimilarityCandidate.source_file_id == file.id,
                    KnowledgeFileSimilarityCandidate.candidate_file_id == file.id,
                )
            )
        )
        self.session.exec(
            delete(PortalRecommendationFileProjection).where(PortalRecommendationFileProjection.file_id == file.id)
        )
        for artifact in artifacts:
            self.session.delete(artifact)
        for version in versions:
            self.session.delete(version)
        if document is not None:
            self.session.delete(document)
        self.session.delete(current)
        self.session.flush()
        logger.info("unreadable sync file cleanup prepared file_id={} reason={}", file.id, unreadable_reason(file))
        return "deleted"

    @staticmethod
    def _has_content_or_distribution(file: KnowledgeFile) -> bool:
        return bool(
            file.file_type != 1
            or file.entry_type
            or file.reference_document_id is not None
            or file.predecessor_logic_file_id is not None
            or file.share_source_file_id is not None
            or file.approval_instance_id is not None
            or file.projection_previous_file_id is not None
            or file.simhash
            or file.preview_file_object_name
            or file.desired_content_generation
            or file.applied_content_generation
            or file.desired_entry_generation
            or file.applied_entry_generation
        )

    @staticmethod
    def _retain(file: KnowledgeFile, reason: str) -> DiscardResult:
        logger.warning("unreadable sync file retained file_id={} protection={}", file.id, reason)
        return "retained"

    def _has_references(self, file: KnowledgeFile, document: KnowledgeDocument | None) -> bool:
        conditions = [
            KnowledgeFile.predecessor_logic_file_id == file.id,
            KnowledgeFile.share_source_file_id == file.id,
            KnowledgeFile.projection_previous_file_id == file.id,
        ]
        if document is not None:
            conditions.append(KnowledgeFile.reference_document_id == document.id)
        if self.session.exec(
            select(KnowledgeFile.id).where(KnowledgeFile.id != file.id, or_(*conditions)).limit(1)
        ).first():
            return True
        if self.session.exec(
            select(KnowledgeDocument.id).where(KnowledgeDocument.predecessor_logic_file_id == file.id).limit(1)
        ).first():
            return True
        if self.session.exec(
            select(DepartmentFileViewGrant.id).where(DepartmentFileViewGrant.file_id == file.id).limit(1)
        ).first():
            return True
        if self.session.exec(
            select(KnowledgeFileCorrection.id)
            .where(
                or_(
                    KnowledgeFileCorrection.file_id == file.id,
                    KnowledgeFileCorrection.pending_update_file_id == file.id,
                )
            )
            .limit(1)
        ).first():
            return True
        if self.session.exec(
            select(ApprovalInstance.id)
            .where(
                ApprovalInstance.business_resource_id == str(file.id),
            )
            .limit(1)
        ).first():
            return True
        favorites = self.session.exec(
            select(KnowledgeFile).where(KnowledgeFile.file_source == "favorite_reference")
        ).all()
        for favorite in favorites:
            reference = (favorite.user_metadata or {}).get("favorite_reference") or {}
            if str(reference.get("source_file_id")) == str(file.id):
                return True
        return False
