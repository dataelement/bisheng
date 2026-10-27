"""相似比较中的目标入口和当前正文身份。"""

from dataclasses import dataclass

from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


@dataclass(frozen=True)
class KnowledgeSimilarityContext:
    entry: KnowledgeFile
    document: KnowledgeDocument | None
    version: KnowledgeDocumentVersion | None
    content: KnowledgeFile | None

    @property
    def valid(self) -> bool:
        entry, document, version, content = self.entry, self.document, self.version, self.content
        if entry.file_type != 1 or entry.status != 2 or entry.deleted_at is not None or content is None:
            return False
        if entry.entry_type not in {None, "manager", "publish"}:
            return False
        if entry.entry_type is None and entry.reference_document_id is not None:
            return False
        if entry.entry_type is not None and entry.reference_document_id is None:
            return False
        if entry.entry_type is not None and (
            entry.entry_status != "active"
            or entry.projection_status != "ready"
            or entry.applied_content_generation != entry.desired_content_generation
            or entry.applied_entry_generation != entry.desired_entry_generation
        ):
            return False
        if (
            content.status != 2
            or content.file_type != 1
            or content.deleted_at is not None
            or content.tenant_id != entry.tenant_id
            or content.entry_type not in {None, "manager"}
        ):
            return False
        if document is None:
            return entry.entry_type is None and entry.reference_document_id is None
        return bool(
            document.tenant_id == entry.tenant_id
            and document.lifecycle_status == "active"
            and version is not None
            and version.document_id == document.id
            and version.is_primary
            and content.knowledge_id == document.knowledge_id
            and (entry.reference_document_id == document.id or entry.id == content.id)
            and (entry.entry_type is not None or entry.id == content.id)
            and (entry.entry_type is None or document.content_generation == entry.applied_content_generation)
        )

    def cached_with(self, target: "KnowledgeSimilarityContext") -> bool:
        metadata = self.entry.user_metadata if isinstance(self.entry.user_metadata, dict) else {}
        snapshot = metadata.get("_similarity_snapshot")
        if not isinstance(snapshot, dict):
            return self.entry.entry_type is None and target.entry.entry_type is None
        targets = snapshot.get("targets")
        return (
            isinstance(targets, dict)
            and snapshot.get("source") == list(self.signature)
            and targets.get(str(target.entry.id)) == list(target.signature)
        )

    @property
    def comparison_file(self) -> KnowledgeFile:
        result = KnowledgeFile(**self.content.model_dump())
        result.id, result.knowledge_id = self.entry.id, self.entry.knowledge_id
        result.__dict__["_similarity_content_file_id"] = self.content.id
        return result

    @property
    def can_associate(self) -> bool:
        return self.entry.entry_type is None and self.entry.reference_document_id is None

    @property
    def signature(self) -> tuple:
        return (
            self.entry.id,
            self.entry.knowledge_id,
            self.entry.entry_type,
            self.entry.entry_status,
            self.entry.desired_content_generation,
            self.entry.desired_entry_generation,
            self.document.primary_version_id if self.document else None,
            self.document.content_generation if self.document else None,
            self.content.id,
            self.content.md5,
            self.content.simhash,
            self.content.file_encoding,
            self.content.file_subcategory_code,
        )
