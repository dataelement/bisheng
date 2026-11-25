"""Best-effort reverse lookups; no source sets, coverage, or migration evidence."""

from sqlalchemy import String, and_, cast, exists, or_, select

from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference as Ref


class ReferenceHintRepository:
    async def aread(self, session, targets, *, space_id=None):
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
            raise ValueError("hint lookup requires a concrete tenant")
        predicates = []
        targets = tuple(targets)
        for offset in range(0, len(targets), 200):
            batch = targets[offset : offset + 200]
            predicates.append(
                or_(*(and_(Ref.target_type == key.target_type.value, Ref.target_id == key.target_id) for key in batch))
            )
        if space_id is not None:
            predicates.append(
                and_(
                    Ref.target_type == "knowledge_file",
                    exists(
                        select(KnowledgeFile.id).where(
                            KnowledgeFile.tenant_id == tenant,
                            KnowledgeFile.knowledge_id == space_id,
                            # Both casts use the connection collation, including on mixed-collation MySQL schemas.
                            cast(KnowledgeFile.id, String(64)) == cast(Ref.target_id, String(64)),
                        )
                    ),
                )
            )
        rows = {}
        # Authorized target IDs are globally unique. Foreign source metadata is never returned here.
        with session.no_autoflush, bypass_tenant_filter():
            for predicate in predicates:
                query = select(Ref).join(Tenant, Tenant.id == Ref.tenant_id).where(predicate).order_by(Ref.id)
                for row in (await session.execute(query)).scalars():
                    rows[row.id] = row
        return tuple(rows.values())
