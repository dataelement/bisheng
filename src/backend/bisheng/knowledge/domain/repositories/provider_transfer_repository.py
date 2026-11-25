"""Tenant-scoped migration reads. Caller owns the short SQL transaction."""

from sqlalchemy import select, update

from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderBinding as Binding,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderGeneration as Generation,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderInstance as Instance,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderMapping as Mapping,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderOperation as Operation,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderQuota as Quota,
)


def scoped(cls, tenant, space):
    return select(cls).where(cls.tenant_id == tenant, cls.space_id == space)


async def locked(session, stmt):
    return (await session.scalars(stmt.with_for_update().execution_options(populate_existing=True))).all()


async def binding(session, tenant, space):
    rows = await locked(session, scoped(Binding, tenant, space))
    return next(iter(rows), None)


async def generation(session, tenant, space, n):
    rows = await locked(session, scoped(Generation, tenant, space).where(Generation.generation == n))
    return next(iter(rows), None)


async def instance(session, tenant, instance_id):
    rows = await locked(session, select(Instance).where(Instance.tenant_id == tenant, Instance.id == instance_id))
    return next(iter(rows), None)


async def mappings(session, gen):
    return await locked(
        session,
        scoped(Mapping, gen.tenant_id, gen.space_id).where(Mapping.generation == gen.generation).order_by(Mapping.id),
    )


async def charges(session, gen):
    return await locked(session, scoped(Quota, gen.tenant_id, gen.space_id).where(Quota.state != "released"))


async def operation(session, tenant, op_id):
    rows = await locked(
        session, select(Operation).where(Operation.tenant_id == tenant, Operation.operation_id == op_id)
    )
    return next(iter(rows), None)


async def replay(session, tenant, key):
    return await session.scalar(
        select(Operation).where(
            Operation.tenant_id == tenant, Operation.kind == "provider_transfer", Operation.request_key == key
        )
    )


async def change_binding(session, tenant, space, generation, revision, **values):
    result = await session.execute(
        update(Binding)
        .where(
            Binding.tenant_id == tenant,
            Binding.space_id == space,
            Binding.active_generation == generation,
            Binding.revision == revision,
            Binding.state == "ready",
        )
        .values(**values, revision=Binding.revision + 1)
    )
    return result.rowcount == 1
