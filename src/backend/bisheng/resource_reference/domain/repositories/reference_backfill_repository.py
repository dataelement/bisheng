"""Bounded index observations for M4; these facts grant no write authority.

Only the caller's current concrete tenant is read. Missing or invalid head
facts are preserved for the owning verifier, never repaired or marked ready.
"""

from dataclasses import dataclass, fields

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.resource_reference.application.contracts import ROOT_GUARD_VERSION, SourceKey, TransactionIdentity
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.repositories.source_read_repository import ReferenceReadRow, SourceSetReadFact


@dataclass(frozen=True, slots=True)
class SourceBackfillHead:
    source_key: SourceKey
    root: SourceSetReadFact | None
    source: SourceSetReadFact | None


@dataclass(frozen=True, slots=True)
class IndexedReference:
    id: int
    fact: ReferenceReadRow


@dataclass(frozen=True, slots=True)
class ReferenceBackfillPage:
    items: tuple[IndexedReference, ...]
    next_after: int | None


def _invalid(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"reference_backfill_{reason}")


def _scope(session):
    tenant = get_current_tenant_id()
    if not isinstance(session, AsyncSession) or type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
        _invalid("native_tenant_scope_required")
    try:
        transaction = TransactionIdentity.capture(session)
    except (TypeError, ValueError) as error:
        raise KnowledgeOperationPlanConflictError(reason="reference_backfill_native_transaction_required") from error
    return tenant, transaction


def _key(value, tenant):
    if not isinstance(value, SourceKey) or value.tenant_id != tenant:
        _invalid("source_scope_invalid")
    try:
        # Revalidate forged/mutated dataclasses without inventing a second
        # SourceKey grammar or accepting the reserved root version as a source.
        return SourceKey(value.tenant_id, value.source_type, value.source_id, value.source_version)
    except (TypeError, ValueError) as error:
        raise KnowledgeOperationPlanConflictError(reason="reference_backfill_source_key_invalid") from error


def _identity(row):
    return row.tenant_id, row.source_type, row.source_id, row.source_version


class ReferenceBackfillRepository:
    @staticmethod
    async def _read(session, statement):
        tenant, transaction = _scope(session)
        with session.no_autoflush, strict_tenant_filter():
            rows = tuple((await session.execute(statement)).mappings())
        current, _ = _scope(session)
        if current != tenant:
            _invalid("tenant_changed")
        try:
            transaction.assert_current(session)
        except (TypeError, ValueError) as error:
            raise KnowledgeOperationPlanConflictError(reason="reference_backfill_transaction_changed") from error
        return rows

    async def aload_heads(
        self, session: AsyncSession, *, source_keys: tuple[SourceKey, ...]
    ) -> tuple[SourceBackfillHead, ...]:
        tenant, _ = _scope(session)
        if type(source_keys) is not tuple or len(source_keys) > 200:
            _invalid("source_batch_invalid")
        keys = tuple(_key(key, tenant) for key in source_keys)
        if len(set(keys)) != len(keys):
            _invalid("duplicate_source_key")
        if not keys:
            return ()
        table = BusinessReferenceSet.__table__
        columns = tuple(table.c[item.name] for item in fields(SourceSetReadFact))
        source_conditions = tuple(
            and_(
                table.c.tenant_id == key.tenant_id,
                table.c.source_type == key.source_type.value,
                table.c.source_id == key.source_id,
                table.c.source_version == key.source_version,
            )
            for key in keys
        )
        root_keys = tuple(dict.fromkeys((key.tenant_id, key.source_type.value, key.source_id) for key in keys))
        root_conditions = tuple(
            and_(table.c.tenant_id == owner, table.c.source_type == kind, table.c.source_id == identifier)
            for owner, kind, identifier in root_keys
        )
        # Two exact scalar queries, with no Source x Root join or independently
        # multiplied IN lists. Status/record_kind remain observations, not filters.
        sources = await self._read(session, select(*columns).where(or_(*source_conditions)))
        roots = await self._read(
            session, select(*columns).where(table.c.source_version == ROOT_GUARD_VERSION, or_(*root_conditions))
        )
        source_facts, root_facts = {}, {}
        for rows, result in ((sources, source_facts), (roots, root_facts)):
            for row in rows:
                fact = SourceSetReadFact(**row)
                identity = _identity(fact)
                if identity in result:
                    _invalid("duplicate_index_head")
                result[identity] = fact
        return tuple(
            SourceBackfillHead(
                key,
                root_facts.get((key.tenant_id, key.source_type.value, key.source_id, ROOT_GUARD_VERSION)),
                source_facts.get((key.tenant_id, key.source_type.value, key.source_id, key.source_version)),
            )
            for key in keys
        )

    async def alist_source_rows(
        self, session: AsyncSession, *, source_key: SourceKey, after_id: int = 0, limit: int = 200
    ) -> ReferenceBackfillPage:
        tenant, _ = _scope(session)
        key = _key(source_key, tenant)
        # BRR.id is a signed BIGINT. This is a storage cursor bound, not a
        # limit on the number of references in a source or in a backfill.
        if (
            type(after_id) is not int
            or not 0 <= after_id <= 2**63 - 1
            or type(limit) is not int
            or not 1 <= limit <= 200
        ):
            _invalid("page_bounds_invalid")
        table = BusinessResourceReference.__table__
        columns = tuple(table.c[item.name] for item in fields(ReferenceReadRow))
        rows = await self._read(
            session,
            select(table.c.id, *columns)
            .where(
                table.c.tenant_id == key.tenant_id,
                table.c.source_type == key.source_type.value,
                table.c.source_id == key.source_id,
                table.c.source_version == key.source_version,
                table.c.id > after_id,
            )
            .order_by(table.c.id)
            .limit(limit),
        )
        items = tuple(
            IndexedReference(
                row["id"], ReferenceReadRow(**{item.name: row[item.name] for item in fields(ReferenceReadRow)})
            )
            for row in rows
        )
        # A full final page intentionally permits one subsequent empty page.
        return ReferenceBackfillPage(items, items[-1].id if len(items) == limit else None)
