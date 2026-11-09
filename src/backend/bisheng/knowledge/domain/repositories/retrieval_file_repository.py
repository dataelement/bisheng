"""Current successful retrieval candidates, with positive SPACE version proof."""

from collections.abc import Iterable

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
from bisheng.resource_reference.application.contracts import TransactionIdentity


def _invalid():
    raise KnowledgeOperationPlanConflictError(reason="retrieval_file_context_changed")


class KnowledgeRetrievalFileRepository:
    async def aload_actual_types(self, session: AsyncSession, *, knowledge_ids) -> dict[int, int]:
        """Classify only the exact selected Roots, under their existing C3 scope."""
        tenant = get_current_tenant_id()
        if (
            not isinstance(session, AsyncSession)
            or type(tenant) is not int
            or tenant <= 0
            or is_tenant_filter_bypassed()
            or session.new
            or session.dirty
            or session.deleted
        ):
            _invalid()
        ids = []
        for raw in knowledge_ids:
            if type(raw) not in (str, int) or not str(raw).isdecimal() or not 0 < int(raw) <= 2**63 - 1:
                _invalid()
            ids.append(int(raw))
        ids = tuple(dict.fromkeys(ids))
        if not ids:
            return {}
        if not session.in_transaction():
            await session.connection()
        if get_current_tenant_id() != tenant or is_tenant_filter_bypassed():
            _invalid()
        transaction = TransactionIdentity.capture(session)
        result = {}
        for start in range(0, len(ids), 200):
            transaction.assert_current(session)
            if get_current_tenant_id() != tenant or is_tenant_filter_bypassed():
                _invalid()
            with session.no_autoflush, strict_tenant_filter():
                rows = (
                    await session.execute(
                        select(Knowledge.id, Knowledge.type).where(Knowledge.id.in_(ids[start : start + 200]))
                    )
                ).all()
            transaction.assert_current(session)
            if (
                get_current_tenant_id() != tenant
                or is_tenant_filter_bypassed()
                or session.new
                or session.dirty
                or session.deleted
            ):
                _invalid()
            result.update(rows)
        return result

    @staticmethod
    def _query(space_id):
        file = KnowledgeFile.__table__
        version = KnowledgeDocumentVersion.__table__
        document = KnowledgeDocument.__table__
        other = version.alias("other_file_version")
        unique_file = ~exists(
            select(other.c.id).where(
                other.c.knowledge_file_id == file.c.id,
                other.c.id != version.c.id,
            )
        ).correlate(file, version)
        primary = exists(
            select(version.c.id)
            .select_from(version.join(document, document.c.id == version.c.document_id))
            .where(
                version.c.knowledge_file_id == file.c.id,
                version.c.is_primary.is_(True),
                version.c.version_no > 0,
                document.c.primary_version_id == version.c.id,
                document.c.knowledge_id == Knowledge.id,
                unique_file,
            )
        ).correlate(file, Knowledge.__table__)
        return (
            select(file.c.id)
            .select_from(Knowledge)
            .join(file, file.c.knowledge_id == Knowledge.id)
            .where(
                Knowledge.id == space_id,
                file.c.tenant_id == Knowledge.tenant_id,
                file.c.status == KnowledgeFileStatus.SUCCESS.value,
                or_(
                    Knowledge.type != KnowledgeTypeEnum.SPACE.value,
                    and_(file.c.file_type == FileType.FILE.value, primary),
                ),
            )
        )

    async def alist_successful_files(
        self, session: AsyncSession, *, space_id: int, file_ids: Iterable[int] | None = None
    ) -> set[int]:
        tenant = get_current_tenant_id()
        if (
            not isinstance(session, AsyncSession)
            or type(space_id) is not int
            or space_id <= 0
            or type(tenant) is not int
            or tenant <= 0
            or is_tenant_filter_bypassed()
            or session.new
            or session.dirty
            or session.deleted
        ):
            _invalid()
        if file_ids is None:
            batches = (None,)
        else:
            supplied = tuple(file_ids)
            if any(type(value) is not int or not 0 < value <= 2**63 - 1 for value in supplied):
                _invalid()
            ids = sorted(set(supplied))
            batches = tuple(ids[start : start + 200] for start in range(0, len(ids), 200))
        if not batches:
            return set()
        transaction = TransactionIdentity.capture(session) if session.in_transaction() else None
        if transaction is None:
            await session.connection()
            transaction = TransactionIdentity.capture(session)

        def current():
            if (
                type(get_current_tenant_id()) is not int
                or get_current_tenant_id() != tenant
                or is_tenant_filter_bypassed()
                or session.new
                or session.dirty
                or session.deleted
            ):
                _invalid()
            try:
                transaction.assert_current(session)
            except (TypeError, ValueError) as error:
                raise KnowledgeOperationPlanConflictError(reason="retrieval_file_context_changed") from error

        result = set()
        query = self._query(space_id)
        for batch in batches:
            bounded = query if batch is None else query.where(KnowledgeFile.__table__.c.id.in_(batch))
            after = 0
            while True:
                current()
                with session.no_autoflush, strict_tenant_filter():
                    rows = (
                        (
                            await session.execute(
                                bounded.where(KnowledgeFile.__table__.c.id > after)
                                .order_by(KnowledgeFile.__table__.c.id)
                                .limit(201)
                            )
                        )
                        .scalars()
                        .all()
                    )
                current()
                result.update(rows[:200])
                if len(rows) <= 200:
                    break
                after = rows[199]
        return result
