"""T861: native SQL conversions, with caller-owned real parent transactions."""

import asyncio
import importlib
import json
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from bisheng.knowledge.domain.repositories.unification_run_repository import KnowledgeUnificationRunRepository
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig as Default
from test.knowledge_unification import test_migration_conversion_plan as producer

resource_native = producer.native
raw = producer.original
IDENTITY = {
    "run_id": "m3-native",
    "writer_contract_version": "f118-v1",
    "baseline_hash": "a" * 64,
    "plan_hash": "b" * 64,
}
NOW = datetime(2026, 11, 7, 3, 4, 5)


@pytest.fixture
async def database(resource_native, monkeypatch):
    engine = resource_native.engine

    # aiosqlite's legacy transaction mode otherwise makes releasing the first
    # SAVEPOINT commit it. This test creates a genuine parent BEGIN explicitly.
    @sa.event.listens_for(engine.sync_engine, "begin")
    def real_parent(connection):
        connection.exec_driver_sql("BEGIN")

    from bisheng.core.database import tenant_filter

    previous = tenant_filter._discover_tenant_aware_tables()
    names = {KnowledgeUnificationRun.__tablename__, Default.__tablename__}
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: previous | names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    async with engine.begin() as connection:
        for model in (KnowledgeUnificationRun, Default):
            await connection.run_sync(lambda conn, model=model: model.__table__.create(conn))
    await resource_native.insert(
        raw.Knowledge,
        [
            raw.resource(9000, is_released=True),
            raw.resource(9001, type=3),
            raw.resource(9002, type=1),
            raw.resource(9003, type=2),
        ],
    )
    await resource_native.insert(
        raw.KnowledgeFile,
        [raw.file(1, status=3), raw.file(2, knowledge_id=9001), raw.file(3, file_type=0), raw.file(4, status=7)],
    )
    await resource_native.insert(raw.Tag, [raw.data("tags", 1), raw.data("tags", 2) | {"name": "second original tag"}])
    await resource_native.insert(
        raw.TagLink,
        [
            raw.data("tag_links", 1),
            raw.data("tag_links", 2) | {"tag_id": 1, "resource_id": "1", "resource_type": 8},
            raw.data("tag_links", 3) | {"tag_id": 2, "resource_id": "4"},
        ],
    )
    keys = ("linsight_llm", "knowledge_llm", "assistant_llm", "workflow_llm", "evaluation_llm")
    await resource_native.insert(
        Default,
        [
            {
                "id": i,
                "tenant_id": 101,
                "key": key,
                "value": json.dumps(
                    {
                        "models": [{"id": "11"}, {"id": "12"}],
                        "task_model": {"id": "12"},
                        "linsight_executor_mode": "old",
                        "custom": {"keep": False},
                    }
                )
                if i == 1
                else '{"keep":true}',
                "create_time": NOW,
                "update_time": NOW,
                "is_shared_to_children": 0,
            }
            for i, key in enumerate(keys, 1)
        ],
    )
    await resource_native.insert(
        Default,
        [
            {
                "id": 6,
                "tenant_id": 1,
                "key": "linsight_llm",
                "value": '{"root":"keep"}',
                "create_time": NOW,
                "update_time": NOW,
            }
        ],
    )
    runs = KnowledgeUnificationRunRepository()
    async with AsyncSession(engine) as session, session.begin():
        await runs.aget_or_create(
            session, run_id=IDENTITY["run_id"], writer_contract_version=IDENTITY["writer_contract_version"]
        )
        await runs.afreeze(
            session,
            run_id=IDENTITY["run_id"],
            writer_contract_version=IDENTITY["writer_contract_version"],
            baseline_ref={"object_key": "baseline/original", "sha256": IDENTITY["baseline_hash"]},
            plan_ref={"object_key": "plan/original", "sha256": IDENTITY["plan_hash"]},
        )
        await runs.aadvance(session, **IDENTITY, expected_phase="baseline_frozen", next_phase="converting")
    facts = await producer.acquire(resource_native)
    async with engine.connect() as connection:
        defaults = tuple(
            producer.DefaultRow(*row)
            for row in (
                await connection.execute(
                    sa.select(Default.id, Default.tenant_id, Default.key, Default.value, Default.update_time).where(
                        Default.tenant_id == 101
                    )
                )
            ).all()
        )
    builder = importlib.import_module(
        "bisheng.knowledge.application.unification_conversion_plan"
    ).ConversionPlanBuilder(
        run_id=IDENTITY["run_id"], writer_contract_version=IDENTITY["writer_contract_version"], planned_at=NOW
    )
    for kind in producer.KINDS:
        values = facts[kind]
        for offset in range(0, max(len(values), 1), 200):
            getattr(builder, "add_" + kind)(values[offset : offset + 200])
    builder.add_defaults(defaults)
    commands = tuple(builder.finish())
    return SimpleNamespace(
        engine=engine, insert=resource_native.insert, queries=resource_native.queries, commands=commands, runs=runs
    )


@pytest.fixture
def module():
    return importlib.import_module("bisheng.knowledge.domain.repositories.unification_conversion_repository")


@pytest.fixture
def repo(module):
    return module.UnificationConversionRepository()


async def snapshot(database):
    async with database.engine.connect() as connection:
        return {
            model.__tablename__: tuple(
                dict(row)
                for row in (await connection.execute(sa.select(model.__table__).order_by(model.id))).mappings()
            )
            for model in (*raw.MODELS.values(), Default, KnowledgeUnificationRun)
        }


async def apply(repo, session, commands):
    scope = await repo.alock_scope(session, **IDENTITY, commands=commands)
    return await repo.aapply_and_read_after(session, scope=scope)


async def test_all_five_real_commands_only_change_the_frozen_whitelist_and_preserve_every_file_column(repo, database):
    before = await snapshot(database)
    assert {command.operation for command in database.commands} == {
        "resource_conversion",
        "initialize_v1",
        "tag_conversion",
        "tag_link_conversion",
        "default_conversion",
    }
    async with AsyncSession(database.engine) as session, session.begin():
        outcomes = await apply(repo, session, database.commands)
        assert len(outcomes) == len(database.commands)
        assert {row.command_key for row in outcomes} == {command.command_key for command in database.commands}
        assert all(len(row.actual_after_digest) == 64 for row in outcomes)
        assert session.in_transaction() and not session.new and not session.dirty
    after = await snapshot(database)
    assert after["knowledgefile"] == before["knowledgefile"]
    roots = {row["id"]: row for row in after["knowledge"]}
    assert roots[9000] == dict(before["knowledge"][0]) | {
        "type": 3,
        "is_released": False,
        "migration_origin": IDENTITY["run_id"],
    }
    assert tuple(row for row in after["knowledge"] if row["id"] != 9000) == before["knowledge"][1:]
    versions = after["knowledge_document_version"]
    docs = {row["id"]: row for row in after["knowledge_document"]}
    assert {row["knowledge_file_id"] for row in versions} == {1, 2, 4}
    for version in versions:
        assert version["version_no"] == 1 and version["is_primary"]
        assert docs[version["document_id"]]["primary_version_id"] == version["id"]
        assert version["create_time"] == version["update_time"] == NOW
    links = {row["id"]: row for row in after["taglink"]}
    assert 1 not in links and links[2] == before["taglink"][1]
    assert links[3] == dict(before["taglink"][2]) | {"resource_type": 8}
    assert all(row["business_type"] == "knowledge_space" for row in after["tag"])
    own = {row["id"]: row for row in after["tenant_system_model_config"]}
    assert json.loads(own[1]["value"]) == {
        "models": [{"id": "11"}, {"id": "12"}],
        "custom": {"keep": False},
        "linsight_default_model_id": "12",
        "chat_default_model_id": "12",
    }
    assert own[1]["update_time"] == NOW
    assert tuple(own[i] for i in range(2, 7)) == before["tenant_system_model_config"][1:]
    assert after["knowledge_unification_run"] == before["knowledge_unification_run"]


async def test_outer_rollback_undoes_real_autoincrement_v1_and_every_other_conversion(repo, database):
    before = await snapshot(database)
    async with AsyncSession(database.engine) as session:
        await session.begin()
        outcomes = await apply(repo, session, database.commands)
        assert any(row.document_id and row.version_id for row in outcomes)
        await session.rollback()
    assert await snapshot(database) == before


@pytest.mark.parametrize("change", ["resource", "file", "tag", "link", "default", "foreign", "relation"])
async def test_frozen_before_and_exact_business_parent_chains_cannot_be_adopted_after_drift(repo, database, change):
    async with database.engine.begin() as connection:
        if change == "resource":
            statement = sa.update(raw.Knowledge).where(raw.Knowledge.id == 9000).values(model="99")
        elif change == "file":
            statement = sa.update(raw.KnowledgeFile).where(raw.KnowledgeFile.id == 1).values(remark="changed")
        elif change == "tag":
            statement = sa.update(raw.Tag).where(raw.Tag.id == 1).values(name="changed")
        elif change == "link":
            statement = sa.update(raw.TagLink).where(raw.TagLink.id == 2).values(user_id=99)
        elif change == "default":
            statement = sa.update(Default).where(Default.id == 1).values(value="{}")
        elif change == "foreign":
            statement = sa.update(raw.KnowledgeFile).where(raw.KnowledgeFile.id == 1).values(tenant_id=202)
        else:
            await connection.execute(
                raw.KnowledgeDocument.__table__.insert(), {"id": 400, "knowledge_id": 9000, "primary_version_id": None}
            )
            statement = raw.KnowledgeDocumentVersion.__table__.insert().values(
                id=401, document_id=400, knowledge_file_id=1, version_no=1, is_primary=False
            )
        await connection.execute(statement)
    before = await snapshot(database)
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await apply(repo, session, database.commands)
    assert await snapshot(database) == before


@pytest.mark.parametrize("table", ["knowledge", "knowledge_document", "tag", "taglink", "tenant_system_model_config"])
async def test_real_sql_timestamp_trigger_is_read_back_and_caught_commit_cannot_preserve_partial_writes(
    repo, database, table
):
    async with database.engine.begin() as connection:
        await connection.exec_driver_sql(
            f"CREATE TRIGGER force_time AFTER UPDATE ON {table} BEGIN UPDATE {table} SET update_time='2099-01-01 00:00:00' WHERE id=NEW.id; END"
        )
    before = await snapshot(database)
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await apply(repo, session, database.commands)
        assert session.in_transaction()
    assert await snapshot(database) == before


async def test_raw_scope_is_native_transaction_bound_and_cannot_be_forged_or_replayed(repo, database):
    async with AsyncSession(database.engine) as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.alock_scope(session, **IDENTITY, commands=database.commands)
        async with session.begin():
            scope = await repo.alock_scope(session, **IDENTITY, commands=database.commands)
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.aapply_and_read_after(session, scope=replace(scope))
        async with session.begin():
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.aapply_and_read_after(session, scope=scope)


async def test_pending_caller_state_is_rejected_without_automatic_flush_or_discard(repo, database):
    before = await snapshot(database)
    async with AsyncSession(database.engine) as session, session.begin():
        row = await session.get(raw.Knowledge, 9000)
        row.name = "caller unflushed"
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.alock_scope(session, **IDENTITY, commands=database.commands)
        assert row.name == "caller unflushed" and row in session.dirty
        await session.rollback()
    assert await snapshot(database) == before


async def test_invalid_batch_and_old_microsecond_plan_fail_before_mutation(repo, database):
    async with AsyncSession(database.engine) as session, session.begin():
        for commands in (list(database.commands), database.commands * 201, (object(),)):
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.alock_scope(session, **IDENTITY, commands=commands)
        v1 = next(command for command in database.commands if command.operation == "initialize_v1")
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.alock_scope(
                session, **IDENTITY, commands=(replace(v1, planned_at=NOW.replace(microsecond=123456)),)
            )


async def test_native_cancellation_after_sql_write_rolls_back_only_owned_savepoint(repo, database, monkeypatch):
    before = await snapshot(database)

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(repo, "aread_after", cancelled)
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(asyncio.CancelledError):
            await apply(repo, session, database.commands)
    assert await snapshot(database) == before


@pytest.mark.parametrize("change", ["incoming_nonknowledge", "same_name", "broken_primary"])
async def test_tag_conversion_rechecks_actual_owner_and_link_version_relations(repo, database, change):
    async with database.engine.begin() as connection:
        if change == "incoming_nonknowledge":
            await connection.execute(
                raw.TagLink.__table__.insert(),
                raw.data("tag_links", 90) | {"tag_id": 1, "resource_id": "app-uuid", "resource_type": 1},
            )
        elif change == "same_name":
            await connection.execute(
                raw.Tag.__table__.insert(), raw.data("tags", 90) | {"business_type": "knowledge_space"}
            )
        else:
            await connection.execute(
                raw.KnowledgeDocument.__table__.insert(), {"id": 400, "knowledge_id": 9000, "primary_version_id": None}
            )
            await connection.execute(
                raw.KnowledgeDocumentVersion.__table__.insert(),
                {"id": 401, "document_id": 400, "knowledge_file_id": 1, "version_no": 1, "is_primary": False},
            )
    commands = tuple(cmd for cmd in database.commands if cmd.operation in {"tag_conversion", "tag_link_conversion"})
    before = await snapshot(database)
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await apply(repo, session, commands)
    assert await snapshot(database) == before


async def test_actual_version_rows_are_not_rescanned_for_each_file_in_a_batch(repo, database, monkeypatch):
    await database.insert(raw.KnowledgeFile, [raw.file(ident) for ident in range(10, 411)])
    facts = await producer.acquire(database)
    builder = importlib.import_module(
        "bisheng.knowledge.application.unification_conversion_plan"
    ).ConversionPlanBuilder(
        run_id=IDENTITY["run_id"], writer_contract_version=IDENTITY["writer_contract_version"], planned_at=NOW
    )
    for kind in producer.KINDS:
        values = facts[kind]
        for offset in range(0, max(len(values), 1), 200):
            getattr(builder, "add_" + kind)(values[offset : offset + 200])
    builder.add_defaults(())
    commands = tuple(cmd for cmd in builder.finish() if cmd.operation == "initialize_v1")[:200]
    scans = []
    original = repo._load

    class MeasuredRows(dict):
        def values(self):
            for row in super().values():
                scans.append(True)
                yield row

    async def measured(*args):
        data = await original(*args)
        data["versions"] = MeasuredRows(data["versions"])
        return data

    monkeypatch.setattr(repo, "_load", measured)
    async with AsyncSession(database.engine) as session, session.begin():
        assert len(await apply(repo, session, commands)) == 200
    assert len(scans) <= 2000  # Actual native rows, not an N-file x N-version loop.


async def test_unknown_default_algorithm_is_not_executed_as_the_current_transform(repo, database):
    command = next(cmd for cmd in database.commands if cmd.operation == "default_conversion")
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await apply(repo, session, (replace(command, algorithm_version="unknown-algorithm"),))


async def test_locked_scope_rechecks_the_real_sql_checkpoint_before_any_business_write(repo, database):
    before = await snapshot(database)
    checkpoint = {"cursor": "sql-v1:1:" + "a" * 64, "processed_count": 1, "digest": "c" * 64, "complete": False}
    async with AsyncSession(database.engine) as session, session.begin():
        scope = await repo.alock_scope(session, **IDENTITY, commands=database.commands)
        await session.execute(
            sa.update(KnowledgeUnificationRun.__table__)
            .where(KnowledgeUnificationRun.run_id == IDENTITY["run_id"], KnowledgeUnificationRun.tenant_id == 101)
            .values(checkpoints={"converting": {"sql_conversion": checkpoint}})
        )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aapply_and_read_after(session, scope=scope)
    after = await snapshot(database)
    assert {key: value for key, value in after.items() if key != "knowledge_unification_run"} == {
        key: value for key, value in before.items() if key != "knowledge_unification_run"
    }
    assert after["knowledge_unification_run"][0]["checkpoints"]["converting"]["sql_conversion"] == checkpoint


async def test_core_sql_link_change_after_scope_lock_is_not_erased_by_planned_deletion(repo, database):
    async with AsyncSession(database.engine) as session, session.begin():
        scope = await repo.alock_scope(session, **IDENTITY, commands=database.commands)
        await session.execute(sa.update(raw.TagLink.__table__).where(raw.TagLink.id == 1).values(resource_id="2"))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aapply_and_read_after(session, scope=scope)
    after = await snapshot(database)
    assert next(row for row in after["taglink"] if row["id"] == 1)["resource_id"] == "2"
    assert after["knowledge_document"] == after["knowledge_document_version"] == ()
    assert after["knowledge"][0]["type"] == 0


async def test_every_native_update_or_delete_has_an_explicit_tenant_predicate(repo, database):
    writes = []

    @sa.event.listens_for(database.engine.sync_engine, "before_cursor_execute")
    def seen(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.upper().startswith(("UPDATE ", "DELETE ")):
            writes.append(statement)

    try:
        async with AsyncSession(database.engine) as session, session.begin():
            await apply(repo, session, database.commands)
    finally:
        sa.event.remove(database.engine.sync_engine, "before_cursor_execute", seen)
    assert writes and all("tenant_id" in statement.split(" WHERE ", 1)[1] for statement in writes)
