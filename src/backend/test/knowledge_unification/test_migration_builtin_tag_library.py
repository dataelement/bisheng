"""Historical F038 system libraries stay original M2 facts, not User(0).

Execute the actual old seed against native tables. No migration production
data, creator, grant or original resource is repaired by these tests.
"""

import hashlib
import importlib
import json

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_inventory_codec import decode_inventory_page, encode_inventory_page
from test.knowledge_unification import test_migration_inventory_application as inventory
from test.knowledge_unification import test_migration_preflight as checks
from test.knowledge_unification import test_migration_resource_repository as resources

resource_native = checks.resource_native
native = checks.native
complete = inventory.complete
transport = inventory.transport


async def seed_builtin(database, monkeypatch):
    seed = importlib.import_module("bisheng.core.database.alembic.versions.v2_6_0_f038_knowledge_space_auto_tags")

    def apply(connection):
        with monkeypatch.context() as patch:
            patch.setattr(seed.op, "get_bind", lambda: connection)
            patch.setattr(seed, "table_exists", lambda name: sa.inspect(connection).has_table(name))
            seed._seed_builtin_libraries()

    async with database.engine.begin() as connection:
        await connection.run_sync(apply)


async def original_libraries(database):
    async with database.engine.connect() as connection:
        return [
            dict(row)
            for row in (
                await connection.execute(
                    sa.select(resources.KnowledgeSpaceTagLibrary.__table__).order_by(
                        resources.KnowledgeSpaceTagLibrary.id
                    )
                )
            ).mappings()
        ]


async def test_actual_f038_seed_is_frozen_unchanged_without_a_fake_zero_creator(native, monkeypatch):
    await seed_builtin(native, monkeypatch)
    before = await original_libraries(native)
    assert len(before) == 3 and all(
        row["user_id"] == 0 and row["is_builtin"] is True and row["owner_knowledge_id"] is None for row in before
    )
    native.queries.clear()
    preflight = importlib.import_module("bisheng.knowledge.application.unification_preflight")
    async with AsyncSession(native.engine) as session, session.begin():
        records = await checks.collect(preflight, session)
        assert not session.new and not session.dirty and not session.deleted
    libraries = [item for _, item in records if item.record_type == "tag_library"]
    assert len(libraries) == 1 and libraries[0].data["tenant_id"] == 101
    row = libraries[0].data
    assert row["user_id"] == 0 and row["is_builtin"] is True and row["owner_knowledge_id"] is None
    assert not any(item.record_type == "creator" for _, item in records)
    assert not any("m2_exact_creator" in sql for sql, _ in native.queries)
    identity = {"run_id": "formal-run", "section": "resources", "scope": "tenant", "tenant_id": 101, "page_index": 0}
    content = encode_inventory_page(records=tuple(libraries), **identity)
    decoded = decode_inventory_page(content, **identity)
    assert decoded.records == tuple(libraries)
    assert encode_inventory_page(records=decoded.records, **identity) == content
    assert (await original_libraries(native)) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": -1},
        {"is_builtin": False},
        {"owner_knowledge_id": 9000},
        {"user_id": 888},
        {"is_builtin": False, "user_id": 888},
    ],
)
async def test_only_exact_public_builtin_zero_may_skip_creator_lookup(native, changes):
    await native.insert(resources.Knowledge, [resources.resource(9000, type=3)])
    row = resources.data("tag_libraries", 1) | {
        "user_id": 0,
        "is_builtin": True,
        "owner_knowledge_id": None,
        **changes,
    }
    await native.insert(resources.KnowledgeSpaceTagLibrary, [row])
    before = await original_libraries(native)
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await checks.collect(
                importlib.import_module("bisheng.knowledge.application.unification_preflight"), session
            )
        assert not session.new and not session.dirty and not session.deleted
    assert (await original_libraries(native)) == before


@pytest.mark.parametrize("kind", [0, 1, 2, 3])
async def test_zero_creator_on_knowledge_never_inherits_the_library_sentinel_exception(native, kind):
    await native.insert(resources.Knowledge, [resources.resource(9000, type=kind, user_id=0)])
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await checks.collect(
                importlib.import_module("bisheng.knowledge.application.unification_preflight"), session
            )


async def test_native_m2_freezes_all_seeded_libraries_in_verified_baseline_pages(complete, transport, monkeypatch):
    await seed_builtin(complete, monkeypatch)
    before = await original_libraries(complete)
    app = inventory.application(
        importlib.import_module("bisheng.knowledge.application.unification_inventory"),
        transport,
        physical_reader=inventory.Physical(),
        queued_task_reader=inventory.Queued(),
    )
    async with AsyncSession(complete.engine) as session, session.begin():
        result = await app.arun(session, **transport.inputs)
    assert result.tenant_ids == (1, 101, 202)
    frozen = []
    for key, content in transport.objects.items():
        value = json.loads(content)
        if not any(row.get("record_type") == "tag_library" for row in value["records"]):
            continue
        header = value["records"][0]
        page = decode_inventory_page(
            content,
            run_id=value["run_id"],
            kind=value["kind"],
            **{field: header[field] for field in ("section", "scope", "tenant_id", "page_index")},
        )
        assert key.endswith(hashlib.sha256(content).hexdigest() + ".json")
        frozen.extend(row.data for row in page.records if row.record_type == "tag_library")
    assert {row["tenant_id"] for row in frozen} == {1, 101, 202}
    assert len(frozen) == 3 and all(
        row["user_id"] == 0 and row["is_builtin"] is True and row["owner_knowledge_id"] is None for row in frozen
    )
    assert (await original_libraries(complete)) == before
