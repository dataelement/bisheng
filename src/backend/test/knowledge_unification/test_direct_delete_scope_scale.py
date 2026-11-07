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


@pytest.mark.parametrize("count", [401, 10001])
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
    phases = []

    def record(_conn, clause, _args, _kwargs, _options):
        if getattr(clause, "_for_update_arg", None) is not None:
            phases.append(next(iter(clause.selected_columns)).table.name)

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
    else:
        assert phases == []
    assert_read_only(db)
    print({"documents": count + 1, "lock": lock, "selects": len(db.statements)})
