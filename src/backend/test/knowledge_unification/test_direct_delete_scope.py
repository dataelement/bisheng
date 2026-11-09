"""T955: native delete closures are complete facts, never permission or cutover."""

import importlib
from contextlib import asynccontextmanager, nullcontext
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context import tenant as scope_context
from bisheng.core.database import tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Document
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.knowledge.domain.repositories.knowledge_space_delete_repository import KnowledgeSpaceDeleteRepository
from bisheng.knowledge.domain.repositories.knowledge_version_mutation_repository import (
    VersionDocumentFact,
    VersionRowFact,
)


def dto():
    return importlib.import_module("bisheng.knowledge.domain.schemas.direct_delete_scope")


def selections(*keys):
    return tuple(dto().DeleteSelection(kind, ident) for kind, ident in keys)


@pytest.fixture
def deletion_tenant(tenant_context):
    tenant_context(101)


@pytest.fixture
async def db(deletion_tenant, monkeypatch):
    monkeypatch.setattr(
        tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | {"knowledge", "knowledgefile"}
    )
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: Knowledge.metadata.create_all(
                conn, tables=[model.__table__ for model in (Knowledge, File, Document, Version)]
            )
        )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    async with sessions() as session:
        for ident, tenant in ((1, 101), (2, 101), (9, 202)):
            await session.execute(
                sa.insert(Knowledge.__table__).values(
                    id=ident,
                    tenant_id=tenant,
                    user_id=7,
                    name=f"space-{ident}",
                    type=3,
                    model="old-model",
                    index_name=f"es-{ident}",
                    collection_name=f"mv-{ident}",
                )
            )
        rows = [
            (10, 0, "", 0, 5),
            (20, 0, "/10", 1, 5),
            (200, 0, "/10", 1, 2),
            (30, 1, "/10/20", 2, 2),
            (31, 1, "/10", 1, 3),
            (40, 1, "/10/200", 2, 3),
            (50, 0, None, 0, 5),
            (60, 1, None, 0, 3),
            (61, 1, "", 0, None),
            (62, 1, "", 0, 999),
        ]
        for ident, kind, path, level, status in rows:
            await session.execute(
                sa.insert(File.__table__).values(
                    id=ident,
                    tenant_id=101,
                    knowledge_id=1,
                    user_id=7,
                    file_name=f"f-{ident}",
                    file_type=kind,
                    file_level_path=path,
                    level=level,
                    status=status,
                    object_name=f"obj/{ident}" if kind else None,
                    preview_file_object_name=f"preview/{ident}" if kind else None,
                    update_time=datetime(2026, 11, 7, 1, 0),
                )
            )
        await session.execute(
            sa.insert(Document.__table__).values(
                id=100, knowledge_id=1, primary_version_id=300, file_level_path="/10/20", level=2
            )
        )
        await session.execute(
            sa.insert(Version.__table__),
            [
                {"id": 300, "document_id": 100, "knowledge_file_id": 30, "version_no": 1, "is_primary": True},
                {"id": 301, "document_id": 100, "knowledge_file_id": 31, "version_no": 2, "is_primary": False},
            ],
        )
        await session.commit()
    statements = []
    sa.event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        lambda _c, _cu, sql, params, _ctx, _many: statements.append((sql, params)),
    )
    try:
        yield type(
            "DeleteDatabase", (), {"engine": engine, "sessions": staticmethod(sessions), "statements": statements}
        )()
    finally:
        await engine.dispose()


async def read(db, *keys, lock=False, session=None):
    repo = KnowledgeSpaceDeleteRepository()
    if session is not None:
        return await repo.aread_delete_scope(session, space_id=1, selections=selections(*keys), for_update=lock)
    async with db.sessions() as active, active.begin():
        return await repo.aread_delete_scope(active, space_id=1, selections=selections(*keys), for_update=lock)


def assert_read_only(db):
    assert all(
        not sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")) for sql, _ in db.statements
    )


@pytest.mark.parametrize(
    "kind,ident", [("file", 1), ("folder", True), ("knowledge_file", 1.0), ("folder", 0), ("folder", -1)]
)
def test_selection_does_not_coerce_native_ids_or_invent_resource_kinds(kind, ident):
    with pytest.raises((TypeError, ValueError)):
        dto().DeleteSelection(kind, ident)


async def test_empty_selection_is_zero_sql_and_does_not_assert_root_existence(db):
    async with db.sessions() as session:
        value = await KnowledgeSpaceDeleteRepository().aread_delete_scope(session, space_id=888, selections=())
        assert not value.units and not value.resources and not value.documents and not value.versions
        assert value.space_id == 888 and not value.cleanup_identity
        assert not db.statements and not session.in_transaction()


@pytest.mark.parametrize("lock", [False, True])
async def test_folder_expands_primary_and_all_history_but_never_prefix_neighbor(db, lock):
    value = await read(db, ("folder", 20), lock=lock)
    (unit,) = value.units
    assert unit.resource_ids == (20, 30, 31) and unit.version_ids == (300, 301)
    assert unit.deleted_document_ids == (100,) and not unit.unregistered_file_ids
    assert unit.selection_positions == (0,) and not unit.processing_file_ids
    assert [row.id for row in value.resources] == [20, 30, 31]
    assert type(value.documents[0]) is VersionDocumentFact and type(value.versions[0]) is VersionRowFact
    assert value.cleanup_identity == {
        "id": 1,
        "name": "space-1",
        "type": 3,
        "tenant_id": 101,
        "user_id": 7,
        "model": "old-model",
        "index_name": "es-1",
        "collection_name": "mv-1",
    }
    assert value.object_names == ("30", "31", "obj/30", "obj/31", "preview/30", "preview/31")
    assert "obj/30" not in repr(value) and "old-model" not in repr(value)
    assert all("obj/30" not in repr(row) for row in value.resources)
    assert_read_only(db)


async def test_historical_delete_keeps_the_document_and_primary_but_returns_full_version_facts(db):
    value = await read(db, ("knowledge_file", 31))
    (unit,) = value.units
    assert unit.resource_ids == (31,) and unit.version_ids == (301,) and not unit.deleted_document_ids
    assert {row.id for row in value.versions} == {300, 301}
    assert value.documents[0].primary_version_id == 300
    assert {row.id for row in value.resources} == {31}
    assert value.resources[0].object_names == ("31", "obj/31", "preview/31")
    assert_read_only(db)


async def test_unregistered_file_and_waiting_empty_folder_remain_explicit_facts(db):
    value = await read(db, ("knowledge_file", 60), ("folder", 50))
    assert len(value.units) == 2 and not value.documents and not value.versions
    assert value.units[0].unregistered_file_ids == (60,)
    assert not value.units[1].processing_file_ids
    assert next(row for row in value.resources if row.id == 50).file_level_path is None
    assert next(row for row in value.resources if row.id == 50).status == 5
    assert_read_only(db)


@pytest.mark.parametrize("status", [1, 2, 3, 4, 5, 6, 7, None, 999])
async def test_status_is_never_shrunk_or_rewritten_into_success(db, status):
    async with db.sessions() as session:
        await session.execute(sa.update(File.__table__).where(File.id == 31).values(status=status))
        await session.commit()
    db.statements.clear()
    value = await read(db, ("folder", 20))
    assert value.units[0].resource_ids == (20, 30, 31)
    assert next(row for row in value.resources if row.id == 31).status == status
    assert value.units[0].processing_file_ids == ((31,) if status in (1, 4, 5) else ())
    assert_read_only(db)


async def test_duplicate_and_ancestor_selected_positions_are_kept_without_copying_facts(db):
    value = await read(db, ("knowledge_file", 30), ("folder", 20), ("folder", 20), ("folder", 10))
    (unit,) = value.units
    assert unit.selection_positions == (0, 1, 2, 3)
    assert unit.resource_ids == (10, 20, 30, 31, 40, 200)
    assert len(value.resources) == 6 and len(value.versions) == 2


@pytest.mark.parametrize(
    "order",
    [
        [("knowledge_file", 30), ("knowledge_file", 31), ("knowledge_file", 60)],
        [("knowledge_file", 31), ("knowledge_file", 60), ("knowledge_file", 30)],
    ],
)
async def test_actual_expansion_overlap_merges_units_without_losing_dsu_keys(db, order):
    value = await read(db, *order)
    assert len(value.units) == 2
    joined = next(unit for unit in value.units if 30 in unit.resource_ids)
    assert joined.resource_ids == (30, 31) and joined.version_ids == (300, 301)
    assert joined.selection_positions == tuple(i for i, key in enumerate(order) if key[1] in (30, 31))
    assert next(unit for unit in value.units if 60 in unit.resource_ids).unregistered_file_ids == (60,)


async def test_historical_selections_sharing_only_a_retained_document_do_not_merge(db):
    async with db.sessions() as session:
        await session.execute(
            sa.insert(File.__table__).values(
                id=32,
                tenant_id=101,
                knowledge_id=1,
                file_name="other-history",
                file_type=1,
                file_level_path="",
                status=2,
            )
        )
        await session.execute(
            sa.insert(Version.__table__).values(
                id=302, document_id=100, knowledge_file_id=32, version_no=3, is_primary=False
            )
        )
        await session.commit()
    value = await read(db, ("knowledge_file", 31), ("knowledge_file", 32))
    assert [unit.resource_ids for unit in value.units] == [(31,), (32,)]
    assert all(not unit.deleted_document_ids for unit in value.units)
    assert len(value.documents) == 1 and len(value.versions) == 3


async def test_missing_foreign_and_mismatched_requests_are_positioned_issues_not_silent_empty_units(db):
    async with db.sessions() as session:
        await session.execute(
            sa.insert(File.__table__).values(
                id=90, tenant_id=202, knowledge_id=9, file_name="foreign private", file_type=1, status=2
            )
        )
        await session.commit()
    value = await read(
        db,
        ("knowledge_file", 90),
        ("knowledge_file", 777),
        ("folder", 31),
        ("knowledge_file", 777),
        ("knowledge_file", 60),
    )
    assert {(issue.positions, issue.reason) for issue in value.issues} == {
        ((0,), "not_found"),
        ((1, 3), "not_found"),
        ((2,), "type_mismatch"),
    }
    assert value.units[0].selection_positions == (4,) and value.units[0].resource_ids == (60,)
    assert "foreign private" not in repr(value)


@pytest.mark.parametrize(
    "bad",
    [
        "foreign-child",
        "missing-file",
        "missing-doc",
        "foreign-doc",
        "duplicate-file",
        "directory-version",
        "double-primary",
        "missing-primary",
        "bad-ancestor",
        "cycle",
    ],
)
async def test_real_fk_errors_cannot_be_inner_joined_or_tenant_filtered_away(db, bad):
    async with db.sessions() as session:
        if bad == "foreign-child":
            await session.execute(
                sa.insert(File.__table__).values(
                    id=33,
                    tenant_id=202,
                    knowledge_id=1,
                    file_name="bad",
                    file_type=0,
                    file_level_path="/10/20",
                    status=2,
                )
            )
        elif bad == "missing-file":
            await session.execute(sa.delete(File.__table__).where(File.id == 31))
        elif bad == "missing-doc":
            await session.execute(sa.delete(Document.__table__).where(Document.id == 100))
        elif bad == "foreign-doc":
            await session.execute(sa.update(Document.__table__).where(Document.id == 100).values(knowledge_id=9))
        elif bad == "duplicate-file":
            await session.execute(
                sa.insert(Version.__table__).values(
                    id=303, document_id=100, knowledge_file_id=30, version_no=3, is_primary=False
                )
            )
        elif bad == "directory-version":
            await session.execute(
                sa.insert(Version.__table__).values(
                    id=303, document_id=100, knowledge_file_id=20, version_no=3, is_primary=False
                )
            )
        elif bad == "double-primary":
            await session.execute(sa.update(Version.__table__).where(Version.id == 301).values(is_primary=True))
        elif bad == "missing-primary":
            await session.execute(
                sa.update(Document.__table__).where(Document.id == 100).values(primary_version_id=888)
            )
        elif bad == "bad-ancestor":
            await session.execute(sa.update(File.__table__).where(File.id == 10).values(file_type=1))
        else:
            await session.execute(sa.update(File.__table__).where(File.id == 20).values(file_level_path="/10/20"))
        await session.commit()
    db.statements.clear()
    with pytest.raises(Exception) as failure:
        await read(db, ("folder", 20))
    assert type(failure.value).__module__.startswith("bisheng.common.errcode")
    assert_read_only(db)


async def test_native_fact_reads_preserve_unrelated_pending_and_cached_objects(db):
    async with db.sessions() as session:
        cached = await session.get(File, 60)
        cached.remark = "caller pending remains"
        pending = File(tenant_id=101, knowledge_id=2, file_name="unrelated", status=2)
        session.add(pending)
        db.statements.clear()
        value = await read(db, ("folder", 20), session=session)
        assert value.units[0].resource_ids == (20, 30, 31)
        assert cached in session.dirty and pending in session.new and pending.id is None
        assert cached.remark == "caller pending remains"
        assert_read_only(db)


@pytest.mark.parametrize("invalid", ["bypass", "missing-tenant", "bool-lock", "non-native", "no-transaction"])
async def test_invalid_execution_context_is_rejected_before_io(db, invalid):
    async with db.sessions() as session:
        repo = KnowledgeSpaceDeleteRepository()
        params = {"space_id": 1, "selections": selections(("folder", 20))}
        with scope_context.bypass_tenant_filter() if invalid == "bypass" else nullcontext():
            token = scope_context.set_current_tenant_id(None) if invalid == "missing-tenant" else None
            try:
                if invalid == "bool-lock":
                    params["for_update"] = 1
                with pytest.raises((TypeError, ValueError, RuntimeError)):
                    await repo.aread_delete_scope(object() if invalid == "non-native" else session, **params)
            finally:
                if invalid == "missing-tenant":
                    scope_context.current_tenant_id.reset(token)
        assert not db.statements


async def test_original_prepare_retains_its_historical_only_scope_and_native_lock_path(db):
    async with db.sessions() as session, session.begin():
        resource = await session.get(File, 31)
        manifest = await KnowledgeSpaceDeleteRepository().prepare(session, resource)
        assert manifest["rows"] == [31] and manifest["version_ids"] == [301]
        assert manifest["document_ids"] == []
    assert_read_only(db)


@pytest.mark.parametrize("change", ["tenant", "bypass"])
async def test_execution_tenant_change_during_native_read_cannot_return_the_prior_tenant_scope(db, monkeypatch, change):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

    repo = KnowledgeSpaceDeleteRepository()
    original = repo._delete_ids
    tokens = []

    async def changed(*args, **kwargs):
        rows = await original(*args, **kwargs)
        if not tokens:
            if change == "tenant":
                tokens.append(scope_context.set_current_tenant_id(202))
            else:
                context = scope_context.bypass_tenant_filter()
                context.__enter__()
                tokens.append(context)
        return rows

    monkeypatch.setattr(repo, "_delete_ids", changed)
    async with db.sessions() as session, session.begin():
        try:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.aread_delete_scope(session, space_id=1, selections=selections(("knowledge_file", 60)))
        finally:
            if change == "tenant":
                scope_context.current_tenant_id.reset(tokens[0])
            else:
                tokens[0].__exit__(None, None, None)
    assert_read_only(db)


async def test_native_lock_reread_rejects_changed_facts_before_returning_scope(db, monkeypatch):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

    async with db.sessions() as session, session.begin():
        original, injected = session.execute, []

        async def execute(statement, *args, **kwargs):
            if (
                not injected
                and getattr(statement, "_for_update_arg", None) is not None
                and next(iter(statement.selected_columns)).table.name == "knowledgefile"
            ):
                injected.append(True)
                await original(sa.update(File.__table__).where(File.id == 31).values(status=4))
            return await original(statement, *args, **kwargs)

        monkeypatch.setattr(session, "execute", execute)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await read(db, ("folder", 20), lock=True, session=session)
        assert injected == [True]
    assert len([sql for sql, _ in db.statements if sql.startswith("UPDATE")]) == 1
