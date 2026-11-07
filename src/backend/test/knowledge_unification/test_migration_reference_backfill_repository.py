"""T895: exact current-tenant scalar index facts, without backfill authority."""

import hashlib
import importlib
from dataclasses import FrozenInstanceError, fields
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import SQLModel

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    visible_tenant_ids,
)
from bisheng.core.database import tenant_filter
from bisheng.resource_reference.application.contracts import ROOT_GUARD_VERSION, SourceKey
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet as Head
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference as Binding
from bisheng.resource_reference.domain.repositories.source_read_repository import ReferenceReadRow, SourceSetReadFact


def api():
    return importlib.import_module("bisheng.resource_reference.domain.repositories.reference_backfill_repository")


def key(ident="one", version="current", kind="assistant", tenant=101):
    return SourceKey(tenant, kind, ident, version)


def head(source, *, root=False, **changes):
    return {
        "tenant_id": source.tenant_id,
        "source_type": source.source_type.value,
        "source_id": source.source_id,
        "source_version": ROOT_GUARD_VERSION if root else source.source_version,
        "record_kind": "root_guard" if root else "source",
        "source_revision": 7 if root else 3,
        "extractor_version": "actual-v1",
        "digest": "a" * 64,
        "effective": not root,
        "ready": not root,
        **changes,
    }


def binding(source, ident=13, **changes):
    return {
        "id": ident,
        "tenant_id": source.tenant_id,
        "source_type": source.source_type.value,
        "source_id": source.source_id,
        "source_version": source.source_version,
        "slot_key": f"slot-{ident}",
        "target_type": "model",
        "target_id": str(ident),
        "target_tenant_id": 101,
        "source_revision": 3,
        "target_space_id": None,
        "legacy_invalid_reason": None,
        "legacy_run_id": None,
        "legacy_evidence_key": None,
        **changes,
    }


@pytest.fixture
async def database(monkeypatch):
    names = {Head.__tablename__, Binding.__tablename__}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    tenant_filter.register_tenant_filter_events()
    tenant = set_current_tenant_id(101)
    visible = visible_tenant_ids.set(frozenset({1, 101, 202}))
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda active: SQLModel.metadata.create_all(active, tables=[Head.__table__, Binding.__table__])
        )
    statements = []

    @sa.event.listens_for(engine.sync_engine, "before_cursor_execute")
    def seen(_connection, _cursor, statement, parameters, _context, _many):
        statements.append((statement, parameters))

    async def insert(model, rows):
        async with engine.begin() as connection:
            await connection.execute(model.__table__.insert(), rows)

    try:
        yield SimpleNamespace(engine=engine, statements=statements, insert=insert)
    finally:
        visible_tenant_ids.reset(visible)
        current_tenant_id.reset(tenant)
        await engine.dispose()


async def test_200_complete_keys_use_two_queries_without_cross_product_or_orm_rows(database):
    keys = tuple(
        key(f"resource-{i // 2}", f"version-{i % 3}", "assistant" if i % 2 else "workflow_version") for i in range(200)
    )
    sources = {
        (row["tenant_id"], row["source_type"], row["source_id"], row["source_version"]): row
        for row in (head(item) for item in keys)
    }
    bait = [
        key("resource-0", "version-2", "assistant"),
        key("resource-99", "version-0", "workflow_version"),
        key("resource-0", tenant=202),
    ]
    for item in bait:
        value = head(item, source_revision=991)
        sources.setdefault((item.tenant_id, item.source_type.value, item.source_id, item.source_version), value)
    await database.insert(Head, list(sources.values()) + [head(item, root=True) for item in keys])
    async with AsyncSession(database.engine) as session, session.begin():
        database.statements.clear()
        result = await api().ReferenceBackfillRepository().aload_heads(session, source_keys=tuple(reversed(keys)))
        assert tuple(item.source_key for item in result) == tuple(reversed(keys))
        assert len(result) == 200 and all(
            item.source.source_revision == 3 and item.root.source_revision == 7 for item in result
        )
        assert len(database.statements) == 2
        assert all("JOIN" not in sql.upper() and sql.upper().startswith("SELECT") for sql, _ in database.statements)
        assert all(" IN (" not in sql.upper() for sql, _ in database.statements)
        assert not session.identity_map and not session.new and not session.dirty
        assert type(result[0].source) is SourceSetReadFact and type(result[0].root) is SourceSetReadFact
        with pytest.raises(FrozenInstanceError):
            result[0].root = None


async def test_missing_and_malformed_head_facts_are_returned_not_filtered_or_repaired(database):
    await database.insert(Head, [head(key(), ready=False, effective=False), head(key(version="v2"))])
    # Simulate an old/corrupt row: production code must return its raw fact,
    # rather than turning an invalid record_kind into a deceptively missing head.
    async with database.engine.begin() as connection:
        await connection.execute(sa.text("PRAGMA ignore_check_constraints=ON"))
        await connection.execute(Head.__table__.insert(), head(key("bad"), root=True, record_kind="unknown"))
        await connection.execute(sa.text("PRAGMA ignore_check_constraints=OFF"))
    async with AsyncSession(database.engine) as session, session.begin():
        result = (
            await api()
            .ReferenceBackfillRepository()
            .aload_heads(session, source_keys=(key(), key(version="v2"), key("bad"), key("missing")))
        )
        assert result[0].root is None and result[1].root is None
        assert result[0].source.ready is False and result[0].source.effective is False
        assert result[2].root.record_kind == "unknown" and result[2].source is None
        assert result[3].root is None and result[3].source is None
        assert not session.new and not session.dirty and not session.deleted


@pytest.mark.parametrize("page_size", [37, 200])
async def test_10001_actual_ids_with_gaps_seek_complete_rows_and_the_same_digest(database, page_size):
    source = key()
    rows = [binding(source, ident=11 + 3 * i) for i in range(1, 10002)]
    rows[-1].update(
        target_tenant_id=None,
        legacy_invalid_reason="target_missing",
        legacy_run_id="run",
        legacy_evidence_key="evidence",
    )
    await database.insert(Binding, rows)
    await database.insert(
        Binding, [binding(key(tenant=202), ident=999999), binding(key(version="history"), ident=999998)]
    )
    expected = hashlib.sha256()
    for row in rows:
        expected.update(
            repr(ReferenceReadRow(**{item.name: row[item.name] for item in fields(ReferenceReadRow)})).encode()
        )
    observed, actual = [], hashlib.sha256()
    async with AsyncSession(database.engine) as session, session.begin():
        repo, after = api().ReferenceBackfillRepository(), 0
        database.statements.clear()
        while True:
            page = await repo.alist_source_rows(session, source_key=source, after_id=after, limit=page_size)
            for item in page.items:
                assert type(item.fact) is ReferenceReadRow
                observed.append(item.id)
                actual.update(repr(item.fact).encode())
            if page.next_after is None:
                break
            assert page.next_after == page.items[-1].id and page.next_after > after
            after = page.next_after
        assert observed == [row["id"] for row in rows] and actual.digest() == expected.digest()
        assert len(database.statements) == (10001 + page_size - 1) // page_size
        assert all(
            "OFFSET" not in sql.upper() and "COUNT(" not in sql.upper() and "ORDER BY" in sql.upper()
            for sql, _ in database.statements
        )
        assert not session.identity_map


async def test_full_last_page_has_real_cursor_then_empty_eof_and_changed_page_size_is_valid(database):
    await database.insert(Binding, [binding(key(), ident=5 * i) for i in range(1, 201)])
    async with AsyncSession(database.engine) as session, session.begin():
        repo = api().ReferenceBackfillRepository()
        page = await repo.alist_source_rows(session, source_key=key(), limit=200)
        assert len(page.items) == 200 and page.next_after == 1000
        eof = await repo.alist_source_rows(session, source_key=key(), after_id=1000, limit=17)
        assert eof.items == () and eof.next_after is None
        page = await repo.alist_source_rows(session, source_key=key(), after_id=35, limit=7)
        assert [item.id for item in page.items] == list(range(40, 75, 5)) and page.next_after == 70


async def test_cached_dirty_expired_and_pending_objects_are_not_refreshed_flushed_or_overwritten(database):
    await database.insert(Head, [head(key()), head(key("stale")), head(key(), root=True)])
    await database.insert(Binding, [binding(key())])
    async with AsyncSession(database.engine, expire_on_commit=False, autoflush=True) as session, session.begin():
        dirty = (
            await session.execute(sa.select(Head).where(Head.source_id == "one", Head.source_version == "current"))
        ).scalar_one()
        stale = (await session.execute(sa.select(Head).where(Head.source_id == "stale"))).scalar_one()
        expired = (await session.execute(sa.select(Head).where(Head.source_version == ROOT_GUARD_VERSION))).scalar_one()
        row = await session.get(Binding, 13)
        dirty.source_revision = 999
        row.slot_key = "caller-dirty-slot"
        pending = Binding(**binding(key("pending"), ident=101))
        session.add(pending)
        with session.no_autoflush:
            await session.execute(sa.update(Head.__table__).where(Head.id == stale.id).values(source_revision=8))
        session.expire(expired, ["source_revision"])
        flushes = []
        sa.event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(True))
        before_map = set(session.identity_map)
        repo = api().ReferenceBackfillRepository()
        result = await repo.aload_heads(session, source_keys=(key(), key("stale")))
        page = await repo.alist_source_rows(session, source_key=key())
        assert result[0].source.source_revision == 3 and result[1].source.source_revision == 8
        assert page.items[0].fact.slot_key == "slot-13"
        assert dirty.source_revision == 999 and stale.source_revision == 3 and row.slot_key == "caller-dirty-slot"
        assert "source_revision" in sa.inspect(expired).unloaded
        assert pending in session.new and dirty in session.dirty and row in session.dirty and not flushes
        assert set(session.identity_map) == before_map
        await session.rollback()


@pytest.mark.parametrize(
    "case", ["list", "duplicate", "oversize", "foreign", "mixed", "none", "bypass", "no_transaction", "wrong_session"]
)
async def test_invalid_head_scope_is_rejected_before_any_sql(database, case):
    repo = api().ReferenceBackfillRepository()
    async with AsyncSession(database.engine) as session:
        if case != "no_transaction":
            await session.begin()
        keys = (key(),)
        if case == "list":
            keys = list(keys)
        elif case == "duplicate":
            keys = keys * 2
        elif case == "oversize":
            keys = tuple(key(str(i)) for i in range(201))
        elif case == "foreign":
            keys = (key(tenant=202),)
        elif case == "mixed":
            keys = (key(), key(tenant=202))
        token = set_current_tenant_id(None) if case == "none" else None
        database.statements.clear()
        try:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                if case == "bypass":
                    with bypass_tenant_filter():
                        await repo.aload_heads(session, source_keys=keys)
                else:
                    await repo.aload_heads(object() if case == "wrong_session" else session, source_keys=keys)
            assert not database.statements
        finally:
            if token is not None:
                current_tenant_id.reset(token)


@pytest.mark.parametrize(
    "after,limit",
    [(True, 200), (-1, 200), (1.0, 200), (None, 200), (2**64, 200), (0, True), (0, 0), (0, 201), (0, "20")],
)
async def test_cursor_and_page_size_do_not_coerce_invalid_values_or_query(database, after, limit):
    async with AsyncSession(database.engine) as session, session.begin():
        database.statements.clear()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await (
                api()
                .ReferenceBackfillRepository()
                .alist_source_rows(session, source_key=key(), after_id=after, limit=limit)
            )
        assert not database.statements


async def test_empty_batch_zero_sql_and_rollback_leaves_every_raw_index_row_unchanged(database):
    await database.insert(Head, [head(key())])
    await database.insert(Binding, [binding(key())])
    async with AsyncSession(database.engine) as session, session.begin():
        before = []
        for model in (Head, Binding):
            before.append(tuple((await session.execute(sa.select(model.__table__))).all()))
        repo = api().ReferenceBackfillRepository()
        database.statements.clear()
        assert await repo.aload_heads(session, source_keys=()) == ()
        assert not database.statements
        await repo.aload_heads(session, source_keys=(key(),))
        await repo.alist_source_rows(session, source_key=key())
        assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in database.statements)
        assert not session.new and not session.dirty and not session.deleted
        await session.rollback()
    async with AsyncSession(database.engine) as fresh, fresh.begin():
        after = []
        for model in (Head, Binding):
            after.append(tuple((await fresh.execute(sa.select(model.__table__))).all()))
        assert after == before


async def test_multiple_versions_share_exactly_one_root_predicate_and_preserve_missing_sources(database):
    await database.insert(Head, [head(key("same", "v1")), head(key("same"), root=True)])
    async with AsyncSession(database.engine) as session, session.begin():
        database.statements.clear()
        heads = (
            await api()
            .ReferenceBackfillRepository()
            .aload_heads(session, source_keys=(key("same", "v2"), key("same", "v1")))
        )
        assert heads[0].source is None and heads[1].source.source_version == "v1"
        assert heads[0].root == heads[1].root
        assert sorted(len(params) for _, params in database.statements) == [4, 8]


@pytest.mark.parametrize("case", ["foreign", "bypass", "no_transaction"])
async def test_row_scope_also_fails_before_sql(database, case):
    async with AsyncSession(database.engine) as session:
        if case != "no_transaction":
            await session.begin()
        database.statements.clear()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            if case == "bypass":
                with bypass_tenant_filter():
                    await api().ReferenceBackfillRepository().alist_source_rows(session, source_key=key())
            else:
                await (
                    api()
                    .ReferenceBackfillRepository()
                    .alist_source_rows(session, source_key=key(tenant=202) if case == "foreign" else key())
                )
        assert not database.statements
