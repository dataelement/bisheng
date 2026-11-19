"""Selected inheritance repair uses native journals; no creator grants are inferred."""

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.permission.domain.models import PermissionGrant, PermissionProjectionOperation, ResourcePermissionMode
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from scripts import prepare_f118_history as history_script
from scripts import repair_f118_folder_inheritance as repair
from test.knowledge_unification import test_prepare_history as fixtures
from test.knowledge_unification.test_history_delete_recovery import sql_count
from test.knowledge_unification.test_model_share_projection_deferred import Transport

history, native, resource_native = fixtures.history, fixtures.native, fixtures.resource_native


@pytest.fixture
async def folders(history, monkeypatch):
    # SQLite autoincrement requires INTEGER PRIMARY KEY, unlike MySQL/DM8's
    # native BIGINT identity. Keep the same real table/constraints otherwise.
    async with history_script.global_session(history.sessions) as session:
        original_modes = [
            {column.key: getattr(row, column.key) for column in ResourcePermissionMode.__table__.columns}
            for row in (await session.exec(select(ResourcePermissionMode))).all()
        ]
    metadata = sa.MetaData()
    PermissionProjectionOperation.__table__.to_metadata(metadata)
    ResourcePermissionMode.__table__.to_metadata(metadata).c.id.type = sa.Integer()
    async with history.db.engine.begin() as connection:
        await connection.run_sync(lambda conn: ResourcePermissionMode.__table__.drop(conn))
        await connection.run_sync(metadata.create_all)
    await history.db.insert(ResourcePermissionMode, original_modes)
    await history.db.insert(
        ResourcePermissionMode,
        [
            {
                "id": 10,
                "tenant_id": 101,
                "resource_type": "knowledge_library",
                "resource_id": "10",
                "mode": "CUSTOM",
                "version": 1,
                "projection_state": "CURRENT",
            }
        ],
    )
    await history.db.insert(
        KnowledgeFile,
        [
            fixtures.resources.file(50, knowledge_id=10, file_type=0, file_level_path="", level=0),
            fixtures.resources.file(51, knowledge_id=10, file_type=0, file_level_path="/50", level=1),
            fixtures.resources.file(52, knowledge_id=10, file_type=0, file_level_path="/50/51", level=2),
        ],
    )
    history.fga.present.update(
        {
            ("user:*", "custom_mode", "knowledge_library:10"),
            ("service_account:*", "custom_mode", "knowledge_library:10"),
            ("user:*", "permission_enabled", "knowledge_library:10"),
            ("service_account:*", "permission_enabled", "knowledge_library:10"),
            ("user:7", "visible", "knowledge_library:10"),
        }
    )
    original_iter = history.fga.iter_tuples

    async def filtered(*, object=None, consistency):
        async for row in original_iter(consistency=consistency):
            if object is None or row["object"] == object:
                yield row

    async def strict_write(*, writes, deletes):
        assert not deletes
        assert all(delta.key not in history.fga.present for delta in writes)
        return await Transport.write_atomic(history.fga, writes=writes, deletes=deletes)

    monkeypatch.setattr(history.fga, "iter_tuples", filtered)
    monkeypatch.setattr(history.fga, "write_atomic", strict_write)
    return history


async def capture(folders, ids=(50, 51, 52)):
    return await repair.capture(
        sessions=folders.sessions, client=folders.fga, tenant_id=101, knowledge_id=10, folder_ids=ids, operator_id=7
    )


async def apply(folders, plan):
    return await repair.apply(
        plan,
        sessions=folders.sessions,
        client=folders.fga,
        projection=folders.runtime._projection,
        state=folders.runtime._state,
    )


async def test_selected_folders_inherit_in_parent_order_without_people_grants_or_file_changes(folders, tmp_path):
    plan = await capture(folders)
    assert folders.fga.writes == 0
    saved = tmp_path / "folders.json"
    history_script.save_plan(saved, plan)
    original = saved.read_bytes()
    root_before = {key for key in folders.fga.present if key[2] == "knowledge_library:10"}
    result = await apply(folders, history_script.load_plan(saved))
    assert result["ready"] and result["folder_ids"] == [50, 51, 52]
    async with history_script.global_session(folders.sessions) as session:
        modes = (
            await session.exec(
                select(ResourcePermissionMode).where(
                    ResourcePermissionMode.resource_type == "folder",
                    ResourcePermissionMode.resource_id.in_(["50", "51", "52"]),
                )
            )
        ).all()
        assert len(modes) == 3
        assert all((m.mode, m.version, m.projection_state) == ("INHERIT", 1, "CURRENT") for m in modes)
        assert not (
            await session.exec(
                select(PermissionGrant).where(
                    PermissionGrant.resource_type == "folder", PermissionGrant.resource_id.in_(["50", "51", "52"])
                )
            )
        ).all()
        for ident in result["folder_ids"]:
            row = await session.get(KnowledgeFile, ident)
            assert {key: getattr(row, key) for key in plan["files"][str(ident)]} == plan["files"][str(ident)]
    for ident in (50, 51, 52):
        _, expected = repair.projection_plan(plan, ident)
        assert {key for key in folders.fga.present if key[2] == f"folder:{ident}"} == {
            delta.key for delta in expected.deltas
        }
        assert len(expected.deltas) == 5
    assert root_before == {key for key in folders.fga.present if key[2] == "knowledge_library:10"}
    writes = folders.fga.writes
    assert await apply(folders, history_script.load_plan(saved)) == result
    assert folders.fga.writes == writes and saved.read_bytes() == original


@pytest.mark.parametrize("phase", ["prepared", "staged", "committed"])
async def test_inheritance_repair_resumes_same_ledger_after_interruptions(folders, monkeypatch, phase):
    plan = await capture(folders)
    projection = folders.runtime._projection
    fired = False
    if phase == "prepared":
        original = folders.runtime._state.prepare_owner

        async def interrupt(*args, **kwargs):
            nonlocal fired
            if not fired:
                fired = True
                raise asyncio.CancelledError()
            return await original(*args, **kwargs)

        monkeypatch.setattr(folders.runtime._state, "prepare_owner", interrupt)
    else:
        original = projection._transition

        async def interrupt(operation, **kwargs):
            nonlocal fired
            if not fired and kwargs["target"] == ("COMMITTED" if phase == "staged" else "FINALIZED"):
                fired = True
                raise asyncio.CancelledError()
            return await original(operation, **kwargs)

        monkeypatch.setattr(projection, "_transition", interrupt)
    with pytest.raises(asyncio.CancelledError):
        await apply(folders, plan)
    with tenant_execution_scope(101):
        repository = ProjectionRepository(folders.sessions)
        _, expected = repair.projection_plan(plan, 50)
        operation = await repository.aget_operation_by_idempotency(expected.idempotency_key)
        assert operation is not None
    result = await apply(folders, plan)
    assert result["permission_operation_ids"][0] == operation.id and result["ready"]


@pytest.mark.parametrize(
    "change", ["path", "tenant", "file_type", "root_type", "root_mode", "root_mode_shape", "foreign_mode", "fga", "pin"]
)
async def test_drift_before_apply_is_rejected_before_any_projection(folders, monkeypatch, change):
    plan = await capture(folders)
    if change == "fga":
        folders.fga.present.add(("user:88", "visible", "folder:52"))
    elif change == "foreign_mode":
        await folders.db.insert(
            ResourcePermissionMode,
            [
                {
                    "id": 2020,
                    "tenant_id": 202,
                    "resource_type": "folder",
                    "resource_id": "52",
                    "mode": "INHERIT",
                    "parent_type": "knowledge_library",
                    "parent_id": "10",
                    "version": 1,
                    "projection_state": "CURRENT",
                }
            ],
        )
    elif change == "pin":
        pin = deepcopy(plan["pin"])
        pin["model_id"] = "different"
        monkeypatch.setattr(history_script, "read_pin", AsyncMock(return_value=pin))
    else:
        async with folders.db.engine.begin() as connection:
            if change == "root_type":
                await connection.execute(sa.update(Knowledge).where(Knowledge.id == 10).values(type=2))
            elif change == "root_mode_shape":
                await connection.execute(
                    sa.update(ResourcePermissionMode).where(ResourcePermissionMode.id == 10).values(mode="INHERIT")
                )
            elif change == "root_mode":
                await connection.execute(
                    sa.update(ResourcePermissionMode)
                    .where(ResourcePermissionMode.id == 10)
                    .values(projection_state="PROJECTING")
                )
            else:
                await connection.execute(
                    sa.update(KnowledgeFile)
                    .where(KnowledgeFile.id == 52)
                    .values(
                        **{
                            "path": {"file_level_path": ""},
                            "tenant": {"tenant_id": 202},
                            "file_type": {"file_type": 1},
                        }[change]
                    )
                )
    with pytest.raises((KnowledgeOperationPlanConflictError, ValueError)):
        await apply(folders, plan)
    assert folders.fga.writes == 0


async def test_repair_does_not_overwrite_later_mode_or_new_relation(folders):
    plan = await capture(folders)
    await apply(folders, plan)
    writes = folders.fga.writes
    async with folders.db.engine.begin() as connection:
        await connection.execute(
            sa.update(ResourcePermissionMode)
            .where(ResourcePermissionMode.resource_type == "folder", ResourcePermissionMode.resource_id == "51")
            .values(mode="CUSTOM")
        )
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await apply(folders, plan)
    assert folders.fga.writes == writes


async def test_retired_private_files_are_retained_without_mode_or_depth_repair(folders):
    await folders.db.insert(Knowledge, [fixtures.resources.resource(11, type=2, model=None)])
    await folders.db.insert(
        KnowledgeFile,
        [
            fixtures.resources.file(60, knowledge_id=11, file_type=0, file_level_path="", level=0),
            fixtures.resources.file(61, knowledge_id=11, file_type=1, file_level_path="/60", level=0),
        ],
    )
    plan = await history_script.capture(folders.sessions, folders.fga)
    assert not any(row["id"] in {60, 61} for row in plan["blocked"] if row.get("table") == "knowledgefile")
    assert not any(row["before"]["id"] in {60, 61} for row in plan["levels"])
    assert folders.fga.writes == 0
    async with folders.sessions() as session:
        assert (await session.get(KnowledgeFile, 61)).level == 0
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await repair.capture(
            sessions=folders.sessions,
            client=folders.fga,
            tenant_id=101,
            knowledge_id=11,
            folder_ids=[60],
            operator_id=7,
        )


async def test_completed_original_history_plan_is_retained_and_new_followup_plan_certifies_ready(
    folders, monkeypatch, tmp_path
):
    async def write(*, writes, deletes):
        return await Transport.write_atomic(folders.fga, writes=writes, deletes=deletes)

    monkeypatch.setattr(folders.fga, "write_atomic", write)
    original = await history_script.capture(folders.sessions, folders.fga)
    assert {row["id"] for row in original["blocked"]} == {50, 51, 52}
    original_path = tmp_path / "history.json"
    history_script.save_plan(original_path, original)
    before = original_path.read_bytes()
    selected_result = await history_script.apply(
        original, sessions=folders.sessions, client=folders.fga, runtime=folders.runtime, operator_id=7
    )
    assert selected_result["preparation_complete"] is False
    inherited = await capture(folders)
    await apply(folders, inherited)
    followup = await history_script.capture(folders.sessions, folders.fga)
    assert followup["blocked"] == followup["purges"] == followup["parents"] == followup["levels"] == []
    history_script.save_plan(tmp_path / "history-followup.json", followup)
    final = await history_script.apply(
        followup, sessions=folders.sessions, client=folders.fga, runtime=folders.runtime, operator_id=7
    )
    assert final["preparation_complete"] is True
    assert original_path.read_bytes() == before


async def test_partial_commit_is_forward_recovered_with_original_fence(folders, monkeypatch):
    from bisheng.common.errcode.permission import PermissionProjectionFailedError

    plan = await capture(folders)
    original = folders.fga.write_atomic
    fired = False

    async def partial(*, writes, deletes):
        nonlocal fired
        if not fired and writes and writes[0].relation == "permission_enabled":
            fired = True
            folders.fga.present.add(writes[0].key)
            raise TimeoutError("partial commit")
        return await original(writes=writes, deletes=deletes)

    monkeypatch.setattr(folders.fga, "write_atomic", partial)
    with pytest.raises(PermissionProjectionFailedError):
        await apply(folders, plan)
    with tenant_execution_scope(101):
        _, expected = repair.projection_plan(plan, 50)
        operation = await ProjectionRepository(folders.sessions).aget_operation_by_idempotency(expected.idempotency_key)
        assert operation.status == "FAILED_CLOSED"
    result = await apply(folders, plan)
    assert result["permission_operation_ids"][0] == operation.id and result["ready"]


@pytest.mark.parametrize("count", [4, 8])
async def test_sibling_repairs_have_linear_sql_and_remote_writes(folders, count, record_property):
    ids = list(range(100, 100 + count))
    await folders.db.insert(
        KnowledgeFile,
        [fixtures.resources.file(i, knowledge_id=10, file_type=0, file_level_path="", level=0) for i in ids],
    )
    plan = await capture(folders, ids)
    with sql_count(folders.db.engine) as stats:
        await apply(folders, plan)
    record_property("folders", count)
    record_property("sql", len(stats.statements))
    record_property("commits", stats.commits)
    record_property("fga_writes", folders.fga.writes)
    assert folders.fga.writes == count * 2
    assert len(stats.statements) <= count * 55 + 50


def test_cli_requires_explicit_inherit_before_initialization(tmp_path, monkeypatch):
    run = AsyncMock()
    monkeypatch.setattr(repair, "arun", run)
    with pytest.raises(SystemExit) as raised:
        repair.main(["--plan", str(tmp_path / "plan.json"), "--apply"])
    assert raised.value.code == 2
    run.assert_not_awaited()


async def test_conditional_tuple_drift_is_not_certified_by_key_only(folders, monkeypatch):
    plan = await capture(folders)
    await apply(folders, plan)
    writes = folders.fga.writes
    original = repair.tuples

    async def changed(client, obj):
        rows = await original(client, obj)
        if obj == "folder:51" and rows:
            rows[0] = {**rows[0], "condition": {"name": "changed"}}
        return rows

    monkeypatch.setattr(repair, "tuples", changed)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await apply(folders, plan)
    assert folders.fga.writes == writes
