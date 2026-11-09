"""Native, bounded physical-file facts and metadata result writes."""

from copy import deepcopy
from datetime import datetime

from sqlalchemy import select, update

from bisheng.common.errcode.knowledge import KnowledgeFileNotExistError, KnowledgeOperationPlanChangedError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


class KnowledgeIndexEditRepository:
    async def aread_root(self, session, knowledge_id):
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
            raise KnowledgeFileNotExistError()
        with session.no_autoflush, strict_tenant_filter():
            root = (await session.execute(select(Knowledge).where(Knowledge.id == knowledge_id))).scalar_one_or_none()
        if root is None or root.tenant_id != tenant:
            raise KnowledgeFileNotExistError()
        return root.model_copy(deep=True)

    async def aread(self, session, file_id, *, lock=False):
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
            raise KnowledgeFileNotExistError()
        file = KnowledgeFile.__table__
        with session.no_autoflush, strict_tenant_filter():
            source = (
                await session.execute(
                    select(Knowledge.id).join(file, file.c.knowledge_id == Knowledge.id).where(file.c.id == file_id)
                )
            ).scalar_one_or_none()
            if source is None:
                raise KnowledgeFileNotExistError()
            root_query = select(Knowledge).where(Knowledge.id == source)
            root = (await session.execute(root_query.with_for_update() if lock else root_query)).scalar_one()
            query = select(file).where(file.c.id == file_id, file.c.knowledge_id == source)
            row = (await session.execute(query.with_for_update() if lock else query)).mappings().one_or_none()
        if row is None or row["tenant_id"] != tenant or row["file_type"] != 1 or root.tenant_id != tenant:
            raise KnowledgeFileNotExistError()
        return root.model_copy(deep=True), KnowledgeFile(**deepcopy(dict(row)))

    async def aanchor(self, session, root, file):
        version, document = KnowledgeDocumentVersion, KnowledgeDocument
        with session.no_autoflush, strict_tenant_filter():
            rows = (
                await session.execute(
                    select(version, document)
                    .join(document, document.id == version.document_id)
                    .where(version.knowledge_file_id == file.id, document.knowledge_id == root.id)
                    .limit(2)
                )
            ).all()
            if len(rows) != 1:
                raise KnowledgeOperationPlanChangedError()
            selected, doc = rows[0]
        return selected.model_dump(mode="json"), doc.model_dump(mode="json")

    async def awrite_metadata(self, session, *, file, values, user):
        tenant = get_current_tenant_id()
        result = await session.execute(
            update(KnowledgeFile.__table__)
            .where(
                KnowledgeFile.id == file.id,
                KnowledgeFile.knowledge_id == file.knowledge_id,
                KnowledgeFile.tenant_id == tenant,
            )
            .values(
                user_metadata=deepcopy(values),
                updater_id=user.user_id,
                updater_name=user.user_name,
                update_time=datetime.now(),
            )
        )
        if result.rowcount != 1:
            raise KnowledgeOperationPlanChangedError()
        await session.flush()
        return (await self.aread(session, file.id))[1]
