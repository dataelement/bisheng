"""New-Run CLI uses real history preparation, planners, transactions and Coverage."""

import importlib
import shutil
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.config.openfga import OpenFGAConf
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.application.unification_inventory import UnificationInventoryApplication
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from bisheng.knowledge.domain.repositories.unification_history_repository import global_session, read_pin
from bisheng.permission.application.migration_history import open_history_runtime
from bisheng.permission.domain.models import (
    PermissionProjectionOperation,
    PermissionProjectionTuple,
    ResourcePermissionMode,
)
from bisheng.user.domain.models.user import User
from test.knowledge_unification.permission_publication_native import (
    complete as complete,
)
from test.knowledge_unification.permission_publication_native import (
    native as native,
)
from test.knowledge_unification.permission_publication_native import (
    published_input as published_input,
)
from test.knowledge_unification.permission_publication_native import (
    raw_resource_native as raw_resource_native,
)
from test.knowledge_unification.permission_publication_native import (
    resource_native as resource_native,
)
from test.knowledge_unification.permission_publication_native import (
    transport as transport,
)
from test.knowledge_unification.test_migration_references_application import no_real_network as no_real_network


def entry():
    return importlib.import_module("scripts.unify_knowledge_spaces")


async def seed_actor(database):
    from bisheng.common.models.config import Config

    async with database.engine.begin() as conn:
        await conn.run_sync(lambda c: Config.__table__.create(c, checkfirst=True))
        await conn.execute(sa.update(User.__table__).where(User.user_id == 7).values(delete=0))
        # SQLite's native integer identity transport, retaining real remaining
        # schema/constraints. This is no evidence about MySQL/DM autoincrement.
        for model in (PermissionProjectionOperation, PermissionProjectionTuple, ResourcePermissionMode):
            await conn.run_sync(lambda c, model=model: model.__table__.create(c, checkfirst=True))
            rows = [dict(row) for row in (await conn.execute(sa.select(model.__table__))).mappings()]
            clone = model.__table__.to_metadata(sa.MetaData())
            clone.c.id.type = sa.Integer()
            for target in model.__table__.foreign_keys:
                target.column.table.to_metadata(clone.metadata)
            await conn.run_sync(model.__table__.drop)
            await conn.run_sync(clone.create)
            if rows:
                await conn.execute(clone.insert(), rows)


def args(value, directory, *extra):
    return entry().parser().parse_args(["--run-id", value.input["run_id"], "--materials-dir", str(directory), *extra])


def runtime(value):
    class Lease:
        async def ensure(self):
            pass

    @asynccontextmanager
    async def lock():
        yield Lease()

    @asynccontextmanager
    async def opened(arguments):
        # Inventory's native read-only SQL snapshot includes pinned remote
        # reads; actual FGA mutations still require every SQL session closed.
        value.store.allow_read_transactions = True

        @asynccontextmanager
        async def history():
            async with global_session(value.sessions) as session:
                pin = await read_pin(session)
            async with open_history_runtime(
                SimpleNamespace(openfga=OpenFGAConf()),
                pin=pin,
                sessions=value.sessions,
                apply=arguments.apply,
                store=value.artifacts.store,
                sharing_reader_factory=value.artifacts.reader_factory,
            ) as owned:
                yield owned

        yield SimpleNamespace(
            store=value.artifacts.store,
            sessions=value.sessions,
            engine=value.database.engine,
            history=history,
            sharing_reader_factory=value.artifacts.reader_factory,
            executor_lock=lock,
        )

    return opened


@pytest.mark.parametrize("published_input", [{"freeze": False, "reference_seed": seed_actor}], indirect=True)
async def test_new_run_preview_has_no_native_writes_and_same_plan_reaches_coverage(published_input, tmp_path):
    value = published_input
    directory = tmp_path / "new-run"
    writes = []

    def observed(conn, cursor, statement, params, context, many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    original_graph = set(value.store.tuples)
    original_objects = dict(value.artifacts.objects)
    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", observed)
    try:
        preview = await entry().arun(args(value, directory, "--dry-run"), runtime_factory=runtime(value))
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observed)
    assert not writes and value.store.tuples == original_graph and value.artifacts.objects == original_objects
    assert preview["can_apply"] and preview["preflight_complete"] and not preview["ready"], preview
    assert list((directory / "private").glob("history-*.json"))
    result = await entry().arun(args(value, directory, "--apply", "--operator-id", "7"), runtime_factory=runtime(value))
    assert result["ready"] and result["complete"] and result["coverage_epoch"] > 0
    async with value.sessions() as session, session.begin():
        assert not (await session.execute(sa.select(Run.id).where(Run.phase != "completed"))).all()
    value.sessions.assert_closed()


@pytest.mark.parametrize("published_input", [{"freeze": False, "reference_seed": seed_actor}], indirect=True)
@pytest.mark.parametrize("interruption", ["before_history", "before_freeze"])
async def test_preparing_shared_replay_survives_loss_of_all_local_materials(
    published_input, tmp_path, monkeypatch, interruption
):
    from bisheng.knowledge.application.unification_upgrade import UnificationUpgradeApplication

    value, directory = published_input, tmp_path / "preparing-shared-replay"
    preview = await entry().arun(args(value, directory, "--dry-run"), runtime_factory=runtime(value))
    assert preview["can_apply"]
    original = UnificationInventoryApplication.arun

    async def fail_before_freeze(self, session, **inputs):
        if inputs.get("freeze", True) and inputs.get("flow_binding"):
            raise KnowledgeOperationPlanConflictError(reason="test_interrupted_after_history_before_freeze")
        return await original(self, session, **inputs)

    with monkeypatch.context() as injected:
        if interruption == "before_freeze":
            injected.setattr(UnificationInventoryApplication, "arun", fail_before_freeze)
        else:

            async def fail_before_history(*_args, **_kwargs):
                raise KnowledgeOperationPlanConflictError(reason="test_interrupted_before_history")

            injected.setattr(UnificationUpgradeApplication, "_history_and_freeze", fail_before_history)
        with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
            await entry().arun(args(value, directory, "--apply", "--operator-id", "7"), runtime_factory=runtime(value))
    assert caught.value.kwargs["reason"] in {
        "test_interrupted_after_history_before_freeze",
        "test_interrupted_before_history",
    }
    async with value.sessions() as session, session.begin():
        with bypass_tenant_filter():
            rows = (await session.execute(sa.select(Run))).scalars().all()
        assert len(rows) == 3 and all(row.phase == "preparing" for row in rows)
        assert all(row.checkpoints["preparing"]["flow_identity_v1"]["complete"] for row in rows)
        assert all(row.baseline_ref == {} and row.plan_ref == {} for row in rows)
    shutil.rmtree(directory)
    native_writes, graph_writes, objects = [], value.store.writes, dict(value.artifacts.objects)

    def observed(conn, cursor, statement, params, context, many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            native_writes.append(statement)

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", observed)
    try:
        replayed = await entry().arun(args(value, directory, "--dry-run"), runtime_factory=runtime(value))
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observed)
    assert replayed["can_apply"] and replayed["flow_ref"] == preview["flow_ref"], replayed
    assert not native_writes and graph_writes == value.store.writes and objects == value.artifacts.objects
    completed = await entry().arun(
        args(value, directory, "--apply", "--operator-id", "7"), runtime_factory=runtime(value)
    )
    assert completed["ready"] and completed["coverage_epoch"] > 0
    value.sessions.assert_closed()
