"""通过 ORM 分批读取共享存储的权威数据, 兼容 MySQL/DM8。"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.knowledge.domain.contracts.shared_storage_reconcile import DocumentSnapshot
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.interfaces.shared_storage_reconcile_repository import (
    SharedStorageReconcileRepository,
)
from bisheng.user.domain.models.user import User

logger = logging.getLogger(__name__)


class SharedStorageReconcileRepositoryImpl(
    BaseRepositoryImpl[KnowledgeDocument, int], SharedStorageReconcileRepository
):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, KnowledgeDocument)

    @staticmethod
    def _document_ids() -> Any:
        return (
            select(KnowledgeDocument.id)
            .join(Knowledge, Knowledge.id == KnowledgeDocument.knowledge_id)
            .where(Knowledge.type == KnowledgeTypeEnum.SPACE.value)
        )

    async def upper_bound(self) -> int:
        result = await self.session.execute(self._document_ids().order_by(KnowledgeDocument.id.desc()).limit(1))
        return int(result.scalar() or 0)

    async def page_ids(self, after: int, upper: int, limit: int) -> list[int]:
        result = await self.session.execute(
            self._document_ids()
            .where(
                KnowledgeDocument.id > after,
                KnowledgeDocument.id <= upper,
            )
            .order_by(KnowledgeDocument.id.asc())
            .limit(limit)
        )
        return [int(i) for i in result.scalars()]

    async def _all(self, statement: Any, lock: bool) -> list[Any]:
        if lock:
            statement = statement.with_for_update()
        result = await self.session.execute(statement.execution_options(populate_existing=True))
        return list(result.scalars().all())

    async def snapshots(self, ids: list[int], *, lock: bool = False) -> dict[int, DocumentSnapshot]:
        if not ids:
            return {}
        documents = await self._all(
            select(KnowledgeDocument).where(col(KnowledgeDocument.id).in_(ids)).order_by(KnowledgeDocument.id.asc()),
            lock,
        )
        entries = await self._all(
            select(KnowledgeFile)
            .where(col(KnowledgeFile.reference_document_id).in_(ids))
            .order_by(KnowledgeFile.id.asc()),
            lock,
        )
        version_ids = [d.primary_version_id for d in documents if d.primary_version_id]
        versions = (
            await self._all(
                select(KnowledgeDocumentVersion).where(col(KnowledgeDocumentVersion.id).in_(version_ids)),
                False,
            )
            if version_ids
            else []
        )
        versions = {v.id: v for v in versions}
        file_ids = [v.knowledge_file_id for v in versions.values()]
        files = (
            await self._all(
                select(KnowledgeFile).where(col(KnowledgeFile.id).in_(file_ids)).order_by(KnowledgeFile.id.asc()),
                lock,
            )
            if file_ids
            else []
        )
        files = {f.id: f for f in files}
        user_ids = {i for f in files.values() for i in (f.user_id, f.updater_id) if i}
        users = await self._all(select(User).where(col(User.user_id).in_(user_ids)), False) if user_ids else []
        names = {u.user_id: u.user_name for u in users}
        by_document = {i: [] for i in ids}
        for entry in entries:
            by_document[entry.reference_document_id].append(entry)
        result = {}
        for document in documents:
            try:
                result[document.id] = self._snapshot(document, versions, files, by_document[document.id], names)
            except Exception as exc:
                # 一篇异常不能使整批健康文档失去核验机会。
                logger.warning(
                    "shared_reconcile invalid_source document_id=%s error_type=%s", document.id, type(exc).__name__
                )
                result[document.id] = DocumentSnapshot(document_id=document.id, skip_reason="invalid_source")
        return result

    @staticmethod
    def _snapshot(
        document: KnowledgeDocument,
        versions: dict[int, KnowledgeDocumentVersion],
        files: dict[int, KnowledgeFile],
        entries: list[KnowledgeFile],
        names: dict[int, str],
    ) -> DocumentSnapshot:
        base = {"document_id": int(document.id), "tenant_id": int(document.tenant_id or 1)}
        if document.lifecycle_status != "active":
            return DocumentSnapshot(**base, skip_reason="document_not_active")
        version = versions.get(document.primary_version_id)
        if version is None or version.document_id != document.id:
            return DocumentSnapshot(**base, skip_reason="invalid_primary_version")
        file = files.get(version.knowledge_file_id)
        if file is None or file.deleted_at is not None or int(file.tenant_id or 1) != base["tenant_id"]:
            return DocumentSnapshot(**base, skip_reason="invalid_content_file")
        if file.status != KnowledgeFileStatus.SUCCESS.value:
            return DocumentSnapshot(**base, skip_reason="content_not_ready")
        active = [
            e
            for e in entries
            if e.entry_type in {"manager", "publish", "share"} and e.entry_status == "active" and e.deleted_at is None
        ]
        managers = [e for e in active if e.entry_type == "manager"]
        if len(managers) != 1:
            return DocumentSnapshot(**base, skip_reason="invalid_manager")
        if any(int(e.tenant_id or 1) != base["tenant_id"] for e in active):
            return DocumentSnapshot(**base, skip_reason="invalid_entry_tenant")
        now = datetime.now()
        projecting = [
            e
            for e in entries
            if e.entry_type in {"manager", "publish", "share"} and e.entry_status in {"active", "deleting"}
        ]
        if any(
            e.projection_status in {"pending", "processing"}
            or (e.projection_lease_until and e.projection_lease_until > now)
            for e in projecting
        ):
            return DocumentSnapshot(**base, skip_reason="projection_busy")
        metadata = {
            "document_name": file.file_name,
            "abstract": file.abstract,
            "upload_time": int(file.create_time.timestamp()) if file.create_time else None,
            "update_time": int(file.update_time.timestamp()) if file.update_time else None,
            "uploader": names.get(file.user_id),
            "updater": names.get(file.updater_id or file.user_id),
            "user_metadata": file.user_metadata or {},
        }
        knowledge_ids = tuple(sorted({int(e.knowledge_id) for e in active}))
        signature = hashlib.sha256(
            json.dumps(
                {
                    "document": document.model_dump(),
                    "file": file.model_dump(),
                    "entries": [e.model_dump() for e in entries],
                    "metadata": metadata,
                },
                sort_keys=True,
                default=str,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        return DocumentSnapshot(
            **base,
            version_id=int(version.id),
            file_id=int(file.id),
            entry_id=int(managers[0].id),
            generation=int(document.content_generation),
            membership_generation=max(
                [int(document.content_generation)] + [int(e.desired_entry_generation) for e in active]
            ),
            knowledge_ids=knowledge_ids,
            metadata=metadata,
            signature=signature,
        )

    async def queue_rebuild(self, snapshot: DocumentSnapshot) -> int:
        # 调用者已按 ID 锁定文档和入口; 嵌入失败仍由原投影重试链路接管。
        async with self.session.begin_nested():
            document = await self.session.get(KnowledgeDocument, snapshot.document_id)
            if document.content_generation != snapshot.generation or document.primary_version_id != snapshot.version_id:
                raise ValueError("source changed before rebuild")
            document.content_generation += 1
            self.session.add(document)
            await KnowledgeFileRepositoryImpl(self.session).mark_document_entries_content_generation(
                snapshot.document_id,
                int(document.content_generation),
            )
            await self.session.flush()
        return snapshot.entry_id
