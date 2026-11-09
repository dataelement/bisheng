"""Bounded index observations for M4; these facts grant no write authority.

Only the caller's current concrete tenant is read. Missing or invalid head
facts are preserved for the owning verifier, never repaired or marked ready.
"""

from dataclasses import dataclass, fields

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.resource_reference.application.contracts import (
    ROOT_GUARD_VERSION,
    SourceKey,
    TransactionIdentity,
    reference_set_digest,
)
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

    async def aload_raw_snapshot(self, session, *, source_key, for_update=False):
        """One exact-source stream; PK/order and every real SQL column survive."""
        tenant, _ = _scope(session)
        key = _key(source_key, tenant)
        sets = BusinessReferenceSet.__table__
        if for_update:
            await self._read(
                session,
                select(sets.c.id)
                .where(
                    sets.c.tenant_id == tenant,
                    sets.c.source_type == key.source_type.value,
                    sets.c.source_id == key.source_id,
                    sets.c.source_version == ROOT_GUARD_VERSION,
                )
                .with_for_update(),
            )
        heads = await self._read(
            session,
            select(*sets.c).where(
                sets.c.tenant_id == tenant,
                sets.c.source_type == key.source_type.value,
                sets.c.source_id == key.source_id,
                sets.c.source_version.in_((ROOT_GUARD_VERSION, key.source_version)),
            ),
        )
        by_version = {row["source_version"]: dict(row) for row in heads}
        if len(by_version) != len(heads):
            _invalid("duplicate_index_head")
        table, rows, after = BusinessResourceReference.__table__, [], 0
        while True:
            page = await self._read(
                session,
                select(*table.c)
                .where(
                    table.c.tenant_id == tenant,
                    table.c.source_type == key.source_type.value,
                    table.c.source_id == key.source_id,
                    table.c.source_version == key.source_version,
                    table.c.id > after,
                )
                .order_by(table.c.id)
                .limit(200),
            )
            rows.extend(dict(row) for row in page)
            if len(page) < 200:
                break
            after = page[-1]["id"]
        return by_version.get(ROOT_GUARD_VERSION), by_version.get(key.source_version), tuple(rows)

    async def aload_tombstones(self, session, *, targets):
        """The globally unique target key, with all actual owners kept visible."""
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.resource_reference.application.contracts import TargetKey
        from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone

        tenant, transaction = _scope(session)
        if type(targets) is not tuple or len(targets) > 200 or any(type(key) is not TargetKey for key in targets):
            _invalid("target_batch_invalid")
        if not targets:
            return ()
        table = ResourceReferenceTombstone.__table__.alias("m4_exact_rrt")
        query = (
            select(*table.c)
            .where(
                or_(
                    *(
                        and_(table.c.target_type == key.target_type.value, table.c.target_id == key.target_id)
                        for key in targets
                    )
                )
            )
            .order_by(table.c.id)
        )
        with session.no_autoflush, strict_tenant_filter(), bypass_tenant_filter():
            rows = tuple(dict(row) for row in (await session.execute(query)).mappings())
        if _scope(session)[0] != tenant:
            _invalid("tenant_changed")
        transaction.assert_current(session)
        return rows

    async def aload_raw_snapshots(self, session, *, source_keys):
        """Read each original row once across one exact bounded source group."""
        tenant, _ = _scope(session)
        if type(source_keys) is not tuple or len(source_keys) > 200:
            _invalid("source_batch_invalid")
        keys = tuple(_key(key, tenant) for key in source_keys)
        if len(set(keys)) != len(keys):
            _invalid("duplicate_source_key")
        if not keys:
            return {}
        heads, bindings = {}, {key: [] for key in keys}
        sets = BusinessReferenceSet.__table__
        roots = tuple(dict.fromkeys((key.source_type.value, key.source_id) for key in keys))
        condition = or_(
            *(
                and_(sets.c.source_type == kind, sets.c.source_id == ident, sets.c.source_version == ROOT_GUARD_VERSION)
                for kind, ident in roots
            ),
            *(
                and_(
                    sets.c.source_type == key.source_type.value,
                    sets.c.source_id == key.source_id,
                    sets.c.source_version == key.source_version,
                )
                for key in keys
            ),
        )
        for row in await self._read(session, select(*sets.c).where(sets.c.tenant_id == tenant, condition)):
            identity = row["source_type"], row["source_id"], row["source_version"]
            if identity in heads:
                _invalid("duplicate_index_head")
            heads[identity] = dict(row)
        table, after = BusinessResourceReference.__table__, 0
        condition = or_(
            *(
                and_(
                    table.c.source_type == key.source_type.value,
                    table.c.source_id == key.source_id,
                    table.c.source_version == key.source_version,
                )
                for key in keys
            )
        )
        while True:
            page = await self._read(
                session,
                select(*table.c)
                .where(table.c.tenant_id == tenant, condition, table.c.id > after)
                .order_by(table.c.id)
                .limit(200),
            )
            for row in page:
                key = SourceKey(tenant, row["source_type"], row["source_id"], row["source_version"])
                bindings[key].append(dict(row))
            if len(page) < 200:
                break
            after = page[-1]["id"]
        return {
            key: (
                heads.get((key.source_type.value, key.source_id, ROOT_GUARD_VERSION)),
                heads.get((key.source_type.value, key.source_id, key.source_version)),
                tuple(bindings[key]),
            )
            for key in keys
        }

    async def awrite_registered_source(
        self, session, *, source_key, expected_snapshot, root_revision, rows, extractor_version, reference_digest
    ):
        """M4-only scalar effect after its frozen-registration checks, never a normal bind."""
        from sqlalchemy import delete, insert, update

        tenant, transaction = _scope(session)

        def current():
            if _scope(session)[0] != tenant:
                _invalid("tenant_changed")
            transaction.assert_current(session)

        key = _key(source_key, tenant)
        if session.new or session.dirty or session.deleted:
            _invalid("pending_caller_writes")
        sets, bindings = BusinessReferenceSet.__table__, BusinessResourceReference.__table__
        condition = (
            sets.c.tenant_id == tenant,
            sets.c.source_type == key.source_type.value,
            sets.c.source_id == key.source_id,
        )
        # The actual M4 service loaded this snapshot under the original Root
        # latch in this same TX; never stream the complete original BRR twice.
        root, source, old = expected_snapshot
        if root is None:
            await session.execute(
                insert(sets).values(
                    tenant_id=tenant,
                    source_type=key.source_type.value,
                    source_id=key.source_id,
                    source_version=ROOT_GUARD_VERSION,
                    record_kind="root_guard",
                    source_revision=root_revision,
                    extractor_version="root-guard-v1",
                    digest=reference_set_digest(()),
                    effective=False,
                    ready=False,
                )
            )
        elif root["source_revision"] != root_revision:
            await session.execute(
                update(sets)
                .where(*condition, sets.c.id == root["id"])
                .values(source_revision=root_revision, update_time=root["update_time"])
            )
        current()
        values = {
            "source_revision": root_revision,
            "extractor_version": extractor_version,
            "digest": reference_digest,
            "digest_version": "sha256-reference-set-v1",
            "effective": True,
            "ready": True,
        }
        if source is None:
            await session.execute(
                insert(sets).values(
                    tenant_id=tenant,
                    source_type=key.source_type.value,
                    source_id=key.source_id,
                    source_version=key.source_version,
                    record_kind="source",
                    **values,
                )
            )
        else:
            await session.execute(
                update(sets)
                .where(*condition, sets.c.id == source["id"])
                .values(**values, update_time=source["update_time"])
            )
        old_by_key = {(row["slot_key"], row["target_type"], row["target_id"]): row for row in old}
        wanted = {(row["slot_key"], row["target_type"], row["target_id"]): row for row in rows}
        for identity, row in old_by_key.items():
            current()
            if identity not in wanted:
                await session.execute(
                    delete(bindings).where(bindings.c.tenant_id == tenant, bindings.c.id == row["id"])
                )
        inserts = []
        for identity, template in wanted.items():
            original = old_by_key.get(identity)
            if original is None:
                inserts.append(
                    dict(
                        tenant_id=tenant,
                        source_type=key.source_type.value,
                        source_id=key.source_id,
                        source_version=key.source_version,
                        **template,
                    )
                )
            else:
                await session.execute(
                    update(bindings)
                    .where(bindings.c.tenant_id == tenant, bindings.c.id == original["id"])
                    .values(**template, update_time=original["update_time"])
                )
            current()
        for offset in range(0, len(inserts), 200):
            await session.execute(insert(bindings), inserts[offset : offset + 200])
            current()
        if _scope(session)[0] != tenant:
            _invalid("tenant_changed")
        return await self.aload_raw_snapshot(session, source_key=key)

    async def aassert_index_universe(self, session, *, source_keys, empty_roots=()):
        """Exhaust actual indexed rows, including orphan/excess tail rows."""
        tenant, transaction = _scope(session)
        keys = frozenset(_key(key, tenant) for key in source_keys)
        roots = {(key.source_type.value, key.source_id) for key in keys}
        roots.update((key.source_type.value, key.source_id) for key in empty_roots if key.tenant_id == tenant)
        for model in (BusinessReferenceSet, BusinessResourceReference):
            table, after = model.__table__, 0
            seen = set()
            while True:
                page = await self._read(
                    session,
                    select(table.c.id, table.c.source_type, table.c.source_id, table.c.source_version)
                    .where(table.c.tenant_id == tenant, table.c.id > after)
                    .order_by(table.c.id)
                    .limit(200),
                )
                for row in page:
                    if model is BusinessReferenceSet and row["source_version"] == ROOT_GUARD_VERSION:
                        if (row["source_type"], row["source_id"]) not in roots:
                            _invalid("unregistered_index_root")
                    else:
                        key = SourceKey(tenant, row["source_type"], row["source_id"], row["source_version"])
                        if key not in keys:
                            _invalid("unregistered_index_source")
                        if model is BusinessReferenceSet:
                            seen.add(key)
                if len(page) < 200:
                    break
                after = page[-1]["id"]
            if model is BusinessReferenceSet and seen != keys:
                _invalid("indexed_source_missing")
            transaction.assert_current(session)

    async def aload_raw_root(self, session, *, root_key):
        tenant, _ = _scope(session)
        from bisheng.resource_reference.application.contracts import SourceRootKey

        if type(root_key) is not SourceRootKey or root_key.tenant_id != tenant:
            _invalid("root_identity")
        sets = BusinessReferenceSet.__table__
        heads = await self._read(
            session,
            select(*sets.c)
            .where(
                sets.c.tenant_id == tenant,
                sets.c.source_type == root_key.source_type.value,
                sets.c.source_id == root_key.source_id,
            )
            .order_by(sets.c.id),
        )
        table, after, rows = BusinessResourceReference.__table__, 0, []
        while True:
            page = await self._read(
                session,
                select(*table.c)
                .where(
                    table.c.tenant_id == tenant,
                    table.c.source_type == root_key.source_type.value,
                    table.c.source_id == root_key.source_id,
                    table.c.id > after,
                )
                .order_by(table.c.id)
                .limit(200),
            )
            rows.extend(dict(row) for row in page)
            if len(page) < 200:
                break
            after = page[-1]["id"]
        return tuple(dict(row) for row in heads), tuple(rows)

    async def aclear_registered_retired(self, session, *, root_key, source_key=None, cleanup_empty_root=False):
        from sqlalchemy import delete

        tenant, transaction = _scope(session)
        if root_key.tenant_id != tenant or (
            source_key is not None
            and (source_key.tenant_id, source_key.source_type, source_key.source_id)
            != (root_key.tenant_id, root_key.source_type, root_key.source_id)
        ):
            _invalid("retired_scope")
        for model in (BusinessResourceReference, BusinessReferenceSet):
            table = model.__table__
            query = delete(table).where(
                table.c.tenant_id == tenant,
                table.c.source_type == root_key.source_type.value,
                table.c.source_id == root_key.source_id,
            )
            if source_key is not None:
                query = query.where(table.c.source_version == source_key.source_version)
            await session.execute(query)
            if _scope(session)[0] != tenant:
                _invalid("tenant_changed")
            transaction.assert_current(session)

        if source_key is not None and cleanup_empty_root:
            table = BusinessReferenceSet.__table__
            remaining = await self._read(
                session,
                select(table.c.id)
                .where(
                    table.c.tenant_id == tenant,
                    table.c.source_type == root_key.source_type.value,
                    table.c.source_id == root_key.source_id,
                    table.c.source_version != ROOT_GUARD_VERSION,
                )
                .limit(1),
            )
            if not remaining:
                bindings = BusinessResourceReference.__table__
                orphan = await self._read(
                    session,
                    select(bindings.c.id)
                    .where(
                        bindings.c.tenant_id == tenant,
                        bindings.c.source_type == root_key.source_type.value,
                        bindings.c.source_id == root_key.source_id,
                    )
                    .limit(1),
                )
                if orphan:
                    _invalid("retired_orphan_bindings")
                await session.execute(
                    delete(table).where(
                        table.c.tenant_id == tenant,
                        table.c.source_type == root_key.source_type.value,
                        table.c.source_id == root_key.source_id,
                        table.c.source_version == ROOT_GUARD_VERSION,
                    )
                )
                transaction.assert_current(session)

    async def ahas_tenant_tombstones(self, session):
        from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone

        tenant, _ = _scope(session)
        return bool(
            await self._read(
                session,
                select(ResourceReferenceTombstone.id).where(ResourceReferenceTombstone.tenant_id == tenant).limit(1),
            )
        )

    async def aload_root_guards(self, session, *, root_keys):
        from bisheng.resource_reference.application.contracts import SourceRootKey

        tenant, _ = _scope(session)
        if (
            type(root_keys) is not tuple
            or len(root_keys) > 200
            or any(type(key) is not SourceRootKey or key.tenant_id != tenant for key in root_keys)
        ):
            _invalid("root_batch_invalid")
        if not root_keys:
            return {}
        table = BusinessReferenceSet.__table__
        rows = await self._read(
            session,
            select(*table.c).where(
                table.c.tenant_id == tenant,
                table.c.source_version == ROOT_GUARD_VERSION,
                or_(
                    *(
                        and_(table.c.source_type == key.source_type.value, table.c.source_id == key.source_id)
                        for key in root_keys
                    )
                ),
            ),
        )
        result = dict.fromkeys(root_keys)
        for row in rows:
            key = SourceRootKey(tenant, row["source_type"], row["source_id"])
            if result[key] is not None:
                _invalid("duplicate_root_guard")
            result[key] = dict(row)
        return result
