"""Native, bounded version facts; every connection closes before authorization."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import bypass_tenant_filter, management_tenant_scope
from bisheng.core.database import tenant_filter
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.knowledge_version_read_repository import KnowledgeVersionReadRepository
from bisheng.knowledge.domain.schemas.knowledge_version_schema import VersionCandidatePage


def space(ident=10, tenant=101, kind=3):
    return Knowledge(id=ident, tenant_id=tenant, type=kind, name=f"space {ident}", user_id=7, state=4)


def chain(ident=1, count=1, *, space_id=10, tenant=101):
    primary = ident * 10000 + count
    rows = [KnowledgeDocument(id=ident, knowledge_id=space_id, primary_version_id=primary)]
    for version_no in range(1, count + 1):
        key = ident * 10000 + version_no
        rows.extend(
            [
                KnowledgeFile(
                    id=key,
                    knowledge_id=space_id,
                    tenant_id=tenant,
                    file_name=f"file {ident} v{version_no}.md",
                    file_type=1,
                    status=2,
                    user_id=7,
                    user_name=f"owner {key}",
                    split_rule="large-rule-must-not-be-read",
                ),
                KnowledgeDocumentVersion(
                    id=key, document_id=ident, knowledge_file_id=key, version_no=version_no, is_primary=key == primary
                ),
            ]
        )
    return rows


@pytest.fixture
async def catalog(tenant_context, monkeypatch):
    tenant_context(101)
    register_tenant_filter_events()
    monkeypatch.setattr(
        tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | {"knowledge", "knowledgefile"}
    )
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    metadata = sa.MetaData()
    for model in (Knowledge, KnowledgeFile, KnowledgeDocument, KnowledgeDocumentVersion):
        model.__table__.to_metadata(metadata)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    facts = SimpleNamespace(open_sessions=0, sql=[])

    @sa.event.listens_for(engine.sync_engine, "before_cursor_execute")
    def observed(_connection, _cursor, statement, parameters, _context, _many):
        facts.sql.append((statement, parameters))

    @asynccontextmanager
    async def sessions():
        facts.open_sessions += 1
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                yield session
        finally:
            facts.open_sessions -= 1

    async def seed(rows):
        async with sessions() as session:
            with bypass_tenant_filter():
                session.add_all(rows)
                await session.commit()
        facts.sql.clear()

    async def change(model, key, **values):
        async with sessions() as session:
            with bypass_tenant_filter():
                await session.execute(sa.update(model).where(model.id == key).values(**values))
                await session.commit()
        facts.sql.clear()

    try:
        yield SimpleNamespace(
            facts=facts,
            seed=seed,
            change=change,
            sessions=sessions,
            repository=KnowledgeVersionReadRepository(session_factory=sessions),
        )
    finally:
        await engine.dispose()


async def test_401_candidate_documents_have_stable_real_pk_seek_and_constant_sql_per_batch(catalog):
    await catalog.seed(
        [
            space(),
            space(20, tenant=202),
            *[item for ident in range(1, 402) for item in chain(ident)],
            *chain(500, space_id=20, tenant=202),
        ]
    )
    seen, after = [], None
    for _ in range(5):
        before = len(catalog.facts.sql)
        batch = await catalog.repository.alist_candidates(
            tenant_id=101, space_id=10, after_document_id=after, limit=100
        )
        seen.extend(item.document.id for item in batch.data)
        assert len(batch.data) <= 100 and catalog.facts.open_sessions == 0
        assert len(catalog.facts.sql) - before <= 6
        after = batch.next_after
        if not batch.has_more:
            break
    assert seen == list(range(1, 402))
    assert not batch.has_more and batch.next_after is None
    assert all("split_rule" not in sql.lower() and "user_metadata" not in sql.lower() for sql, _ in catalog.facts.sql)


async def test_anchor_and_201_history_rows_are_batched_without_primary_or_success_filter(catalog):
    await catalog.seed([space(), *chain(1, 201)])
    await catalog.change(KnowledgeFile, 10001, status=3)
    anchor = await catalog.repository.aget_anchor(tenant_id=101, file_id=10001)
    assert anchor.file.id == 10001 and anchor.file.status == 3
    assert anchor.version_count == 201 and anchor.document.primary_version_id == 10201
    found, after = [], None
    while True:
        batch = await catalog.repository.alist_chain(tenant_id=101, document_id=1, after_version_id=after)
        found.extend(item.version.id for item in batch.data)
        assert catalog.facts.open_sessions == 0
        if not batch.has_more:
            break
        after = batch.next_after
    assert found == list(range(10001, 10202))


async def test_foreign_anchor_never_becomes_a_current_tenant_file(catalog):
    await catalog.seed([space(20, 202), *chain(1, space_id=20, tenant=202)])
    assert await catalog.repository.aget_anchor(tenant_id=101, file_id=10001) is None


@pytest.mark.parametrize("corruption", ["missing_doc", "foreign_doc", "no_primary", "two_primaries", "duplicate_file"])
async def test_anchor_rejects_invalid_actual_chain_and_unique_relationship(catalog, corruption):
    rows = [space(), space(20, 202), *chain(1, 2)]
    if corruption == "missing_doc":
        rows = [item for item in rows if not isinstance(item, KnowledgeDocument)]
    elif corruption == "foreign_doc":
        next(item for item in rows if isinstance(item, KnowledgeDocument)).knowledge_id = 20
    elif corruption == "no_primary":
        next(item for item in rows if isinstance(item, KnowledgeDocumentVersion) and item.is_primary).is_primary = False
    elif corruption == "two_primaries":
        next(
            item for item in rows if isinstance(item, KnowledgeDocumentVersion) and not item.is_primary
        ).is_primary = True
    else:
        rows.extend(
            [
                KnowledgeDocument(id=2, knowledge_id=10, primary_version_id=20001),
                KnowledgeDocumentVersion(
                    id=20001, document_id=2, knowledge_file_id=10001, version_no=1, is_primary=True
                ),
            ]
        )
    await catalog.seed(rows)
    with pytest.raises(SpaceFileNotFoundError):
        await catalog.repository.aget_anchor(tenant_id=101, file_id=10001)


@pytest.mark.parametrize("corruption", ["missing", "foreign_tenant", "foreign_space", "folder"])
async def test_history_does_not_inner_join_away_missing_foreign_or_wrong_type_files(catalog, corruption):
    rows = [space(), space(20, 202), *chain(1, 2)]
    target = next(item for item in rows if isinstance(item, KnowledgeFile) and item.id == 10001)
    if corruption == "missing":
        rows.remove(target)
    elif corruption == "foreign_tenant":
        target.tenant_id = 202
    elif corruption == "foreign_space":
        target.knowledge_id = 20
    else:
        target.file_type = 0
    await catalog.seed(rows)
    with pytest.raises(SpaceFileNotFoundError):
        await catalog.repository.alist_chain(tenant_id=101, document_id=1)


@pytest.mark.parametrize("corruption", ["missing_primary", "wrong_doc", "foreign_file", "folder", "duplicate_file"])
async def test_candidates_keep_bad_primary_relations_visible_to_validation(catalog, corruption):
    rows = [space(), space(20, 202), *chain(1)]
    if corruption == "missing_primary":
        rows = [item for item in rows if not isinstance(item, KnowledgeDocumentVersion)]
    elif corruption == "wrong_doc":
        next(item for item in rows if isinstance(item, KnowledgeDocumentVersion)).document_id = 2
    elif corruption == "foreign_file":
        next(item for item in rows if isinstance(item, KnowledgeFile)).tenant_id = 202
    elif corruption == "folder":
        next(item for item in rows if isinstance(item, KnowledgeFile)).file_type = 0
    else:
        rows.extend(
            [
                KnowledgeDocument(id=2, knowledge_id=10, primary_version_id=20001),
                KnowledgeDocumentVersion(
                    id=20001, document_id=2, knowledge_file_id=10001, version_no=1, is_primary=True
                ),
            ]
        )
    await catalog.seed(rows)
    with pytest.raises(SpaceFileNotFoundError):
        await catalog.repository.alist_candidates(tenant_id=101, space_id=10)


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, 101])
async def test_batch_bounds_are_validated_before_sql(catalog, value):
    with pytest.raises(ValueError):
        await catalog.repository.alist_candidates(tenant_id=101, space_id=10, limit=value)
    assert catalog.facts.sql == []


async def test_actual_tenant_is_required_and_ambient_bypass_cannot_be_used_as_authority(catalog):
    with pytest.raises(PermissionDeniedError):
        await catalog.repository.aget_anchor(tenant_id=202, file_id=10001)
    with bypass_tenant_filter(), pytest.raises(PermissionDeniedError):
        await catalog.repository.aget_anchor(tenant_id=101, file_id=10001)
    with management_tenant_scope(202), pytest.raises(PermissionDeniedError):
        await catalog.repository.alist_chain(tenant_id=101, document_id=1)
    assert catalog.facts.sql == []


async def test_external_native_session_queries_do_not_flush_or_commit_unrelated_dirty_rows(catalog):
    await catalog.seed([space(), *chain(1)])
    async with catalog.sessions() as session, session.begin():
        loaded = await session.get(Knowledge, 10)
        loaded.name = "pending-name"

        @asynccontextmanager
        async def external():
            yield session

        repository = KnowledgeVersionReadRepository(session_factory=external)
        catalog.facts.sql.clear()
        assert (await repository.aget_anchor(tenant_id=101, file_id=10001)).document.id == 1
        assert loaded in session.dirty and session.in_transaction()
        assert all(statement.lstrip().upper().startswith("SELECT") for statement, _ in catalog.facts.sql)
        await session.rollback()


def test_cursor_page_is_explicit_and_does_not_invent_a_total():
    result = VersionCandidatePage(data=[], page_size=40, has_more=True, next_cursor="opaque")
    assert result.model_dump() == {"data": [], "page_size": 40, "has_more": True, "next_cursor": "opaque"}
