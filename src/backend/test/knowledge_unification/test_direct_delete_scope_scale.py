"""T955: real 401/10001 closures must seek pages, not query per document."""

import math

import pytest
import sqlalchemy as sa

from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Document
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from test.knowledge_unification.test_direct_delete_scope import assert_read_only, read
from test.knowledge_unification.test_direct_delete_scope import db as db
from test.knowledge_unification.test_direct_delete_scope import deletion_tenant as deletion_tenant


@pytest.mark.parametrize("count", [200, 201, 401, 10001])
async def test_complete_history_is_bounded_without_per_version_chain_rescans(db, count):
    files = [
        {
            "id": 1000 + n,
            "tenant_id": 101,
            "knowledge_id": 1,
            "file_name": f"history-{n}",
            "file_type": 1,
            "file_level_path": "/10/20",
            "level": 2,
            "status": 2,
        }
        for n in range(count - 2)
    ]
    versions = [
        {"id": 10000 + n, "document_id": 100, "knowledge_file_id": row["id"], "version_no": n + 3, "is_primary": False}
        for n, row in enumerate(files)
    ]
    async with db.sessions() as session:
        await session.execute(sa.insert(File.__table__), files)
        await session.execute(sa.insert(Version.__table__), versions)
        await session.commit()
    db.statements.clear()
    result = await read(db, ("folder", 20))
    assert len(result.versions) == count and len(result.resources) == count + 1
    assert len(result.units) == 1 and len(result.units[0].version_ids) == count
    assert_read_only(db)
    selects = [(query, params) for query, params in db.statements if query.lstrip().upper().startswith("SELECT")]
    assert len(selects) <= 15 + 5 * math.ceil(count / 200)
    paged = [(query, params) for query, params in selects if "LIMIT" in query.upper()]
    assert paged and all(params[-2] <= 201 for _, params in paged)
    assert len([query for query, _ in selects if "knowledge_document_version" in query]) <= 6 + 3 * math.ceil(
        count / 200
    )
    print({"history": count, "selects": len(selects), "paged_selects": len(paged)})


@pytest.mark.parametrize("lock", [False, True])
async def test_401_documents_are_read_as_sets_with_exact_stable_lock_phases(db, lock):
    count = 401
    async with db.sessions() as session:
        await session.execute(
            sa.insert(File.__table__),
            [
                {
                    "id": 1000 + n,
                    "tenant_id": 101,
                    "knowledge_id": 1,
                    "file_name": f"doc-{n}",
                    "file_type": 1,
                    "file_level_path": "/10/20",
                    "level": 2,
                    "status": 2,
                }
                for n in range(count)
            ],
        )
        await session.execute(
            sa.insert(Document.__table__),
            [
                {
                    "id": 1000 + n,
                    "knowledge_id": 1,
                    "primary_version_id": 1000 + n,
                    "file_level_path": "/10/20",
                    "level": 2,
                }
                for n in range(count)
            ],
        )
        await session.execute(
            sa.insert(Version.__table__),
            [
                {
                    "id": 1000 + n,
                    "document_id": 1000 + n,
                    "knowledge_file_id": 1000 + n,
                    "version_no": 1,
                    "is_primary": True,
                }
                for n in range(count)
            ],
        )
        await session.commit()
    phases, locks = [], []

    def record(_conn, clause, _args, _kwargs, _options):
        if getattr(clause, "_for_update_arg", None) is not None:
            phases.append(next(iter(clause.selected_columns)).table.name)
            locks.append(clause)

    sa.event.listen(db.engine.sync_engine, "before_execute", record)
    db.statements.clear()
    result = await read(db, ("folder", 20), lock=lock)
    assert len(result.documents) == count + 1 and len(result.versions) == count + 2
    assert len(result.units) == 1 and len(result.units[0].deleted_document_ids) == count + 1
    assert len(db.statements) <= (65 if lock else 40)
    if lock:
        assert phases[0] == "knowledge"
        rank = {"knowledge": 0, "knowledgefile": 1, "knowledge_document": 2, "knowledge_document_version": 3}
        assert [rank[name] for name in phases] == sorted(rank[name] for name in phases)
        assert set(phases) == set(rank)
        assert all(
            len(query.get_final_froms()) == 1 and not isinstance(query.get_final_froms()[0], sa.Join) for query in locks
        )
        for query in locks[1:]:
            ids = query._where_criteria[0].right.value
            assert ids == sorted(set(ids)) and len(ids) <= 200
            assert [column.name for column in query._order_by_clauses] == ["id"]
    else:
        assert phases == []
    assert_read_only(db)
    print({"documents": count + 1, "lock": lock, "selects": len(db.statements)})


@pytest.mark.parametrize("count", [401, 10001])
async def test_historical_units_compile_the_shared_chain_once_in_actual_native_read(db, monkeypatch, count):
    from bisheng.knowledge.domain.repositories.knowledge_space_delete_repository import KnowledgeSpaceDeleteRepository
    from test.knowledge_unification.test_direct_delete_scope import selections

    async with db.sessions() as session:
        await session.execute(
            sa.insert(File.__table__),
            [
                {
                    "id": 1000 + n,
                    "tenant_id": 101,
                    "knowledge_id": 1,
                    "file_name": f"selected-{n}",
                    "file_type": 1,
                    "file_level_path": "",
                    "status": 2,
                }
                for n in range(count)
            ],
        )
        await session.execute(
            sa.insert(Version.__table__),
            [
                {
                    "id": 1000 + n,
                    "document_id": 100,
                    "knowledge_file_id": 1000 + n,
                    "version_no": n + 3,
                    "is_primary": False,
                }
                for n in range(count)
            ],
        )
        await session.execute(sa.update(Version.__table__).where(Version.id == 300).values(id=100000))
        await session.execute(sa.update(Document.__table__).where(Document.id == 100).values(primary_version_id=100000))
        await session.commit()
    original, visited = KnowledgeSpaceDeleteRepository._delete_units, [0]

    class CountedChain(list):
        def __iter__(self):
            for row in super().__iter__():
                visited[0] += 1
                yield row

    def measured(groups, by_file, by_document, resources):
        chains = {key: CountedChain(value) for key, value in by_document.items()}
        return original(groups, by_file, chains, resources)

    monkeypatch.setattr(KnowledgeSpaceDeleteRepository, "_delete_units", staticmethod(measured))
    db.statements.clear()
    async with db.sessions() as session, session.begin():
        scope = await KnowledgeSpaceDeleteRepository().aread_delete_scope(
            session, space_id=1, selections=selections(*(("knowledge_file", 1000 + n) for n in range(count)))
        )
    assert len(scope.units) == count and len(scope.versions) == count + 2
    assert all(not unit.deleted_document_ids and len(unit.resource_ids) == 1 for unit in scope.units)
    assert visited[0] <= 2 * (count + 2)
    assert len(db.statements) <= 20 + 5 * math.ceil(count / 200)
    assert_read_only(db)
    print({"historical_units": count, "chain_rows_visited": visited[0], "selects": len(db.statements)})
