"""Complete space content facts using the original exact deletion closure."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.knowledge_space_delete_repository import KnowledgeSpaceDeleteRepository
from bisheng.knowledge.domain.schemas.direct_delete_scope import DeleteScope, DeleteSelection
from bisheng.resource_reference.application.contracts import TransactionIdentity


class SpaceDeleteScopeRepository(KnowledgeSpaceDeleteRepository):
    async def aread_space_scope(self, session, *, space_id: int, for_update=False) -> DeleteScope:
        tenant = get_current_tenant_id()
        if (
            not isinstance(session, AsyncSession)
            or not session.in_transaction()
            or type(tenant) is not int
            or tenant <= 0
            or is_tenant_filter_bypassed()
            or type(space_id) is not int
            or space_id <= 0
            or type(for_update) is not bool
            or session.new
            or session.dirty
            or session.deleted
        ):
            raise ValueError("space deletion requires a clean concrete native transaction")
        transaction = TransactionIdentity.capture(session)

        def current():
            transaction.assert_current(session)
            if (
                type(get_current_tenant_id()) is not int
                or get_current_tenant_id() != tenant
                or is_tenant_filter_bypassed()
            ):
                raise KnowledgeOperationPlanConflictError(reason="space_delete_context_changed")

        columns = ("id", "name", "type", "tenant_id", "user_id", "model", "index_name", "collection_name")
        query = select(*(getattr(Knowledge, name) for name in columns)).where(Knowledge.id == space_id)
        with session.no_autoflush, strict_tenant_filter():
            root = (await session.execute(query.with_for_update() if for_update else query)).mappings().one_or_none()
        current()
        if root is None or root["tenant_id"] != tenant or root["type"] != 3:
            raise SpaceNotFoundError()
        # Select the physical inventory once, including unregistered/history
        # files. The original closure validates paths and actual version links.
        selections, after = [], 0
        file, space = KnowledgeFile.__table__, Knowledge.__table__
        while True:
            query = (
                select(Knowledge.tenant_id, file.c.id, file.c.file_type, file.c.tenant_id)
                .select_from(space.join(file, file.c.knowledge_id == space.c.id))
                .where(Knowledge.id == space_id, file.c.id > after)
                .order_by(file.c.id)
                .limit(200)
            )
            with session.no_autoflush, strict_tenant_filter():
                page = (await session.execute(query)).all()
            current()
            for root_owner, ident, kind, owner in page:
                if root_owner != tenant or owner != tenant or type(kind) is not int or kind not in (0, 1):
                    raise KnowledgeOperationPlanConflictError(reason="space_delete_physical_inventory_invalid")
                selections.append(DeleteSelection("folder" if kind == 0 else "knowledge_file", ident))
            if len(page) < 200:
                break
            after = page[-1][1]
        if not selections:
            return DeleteScope(tenant, space_id, (), cleanup_identity=dict(root))
        result = await self.aread_delete_scope(
            session, space_id=space_id, selections=tuple(selections), for_update=for_update
        )
        current()
        if result.issues or {row.id for row in result.resources} != {row.resource_id for row in selections}:
            raise KnowledgeOperationPlanConflictError(reason="space_delete_inventory_changed")
        return result
