"""Native history repair closes only residual markers and preserves payloads."""

import pytest
import sqlalchemy as sa
from sqlmodel import select

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.permission.domain.models import PermissionProjectionOperation, ResourcePermissionMode
from scripts import f118_delete_closure as closure
from scripts import prepare_f118_history as script
from test.knowledge_unification import test_prepare_history as original
from test.knowledge_unification.test_migration_deleted_permission_retention import receipt

resource_native, native, history = original.resource_native, original.native, original.history


async def seed(history, *, marker=True):
    async with script.global_session(history.sessions) as session:
        pin = await script.read_pin(session)
        mode = await session.get(ResourcePermissionMode, 30)
        operation, rows = receipt(
            7001,
            mode.resource_type,
            mode.resource_id,
            mode.version,
            store_id=pin["store_id"],
            model_id=pin["model_id"],
            subjects=("user:*",),
        )
        session.add_all([operation, *rows])
        mode.version, mode.operation_id = operation.target_version, operation.id
        session.add(mode)
    if marker:
        history.fga.present.add(("service_account:*", "permission_enabled", "knowledge_file:30"))
    original_write = history.fga.write_atomic

    async def strict(*, writes, deletes):
        assert not writes
        assert all(delta.key in history.fga.present for delta in deletes), "never DELETE an already absent tuple"
        return await original_write(writes=writes, deletes=deletes)

    history.fga.write_atomic = strict
    return pin


@pytest.mark.parametrize("marker", [False, True])
async def test_default_history_folds_parent_repair_and_closes_both_subjects_without_deleting_payload(
    history, marker, tmp_path
):
    await seed(history, marker=marker)
    plan = await script.capture(history.sessions, history.fga)
    assert not plan["blocked"]
    assert len(plan["delete_closures"]) == 1 and not plan["parents"]
    assert plan["schema"] == 2
    filename = tmp_path / "history-schema2.json"
    script.save_plan(filename, plan)
    assert script.load_plan(filename) == plan and filename.stat().st_mode & 0o777 == 0o600
    assert len(plan["delete_closures"][0]["parent_deletes"]) == 1
    before = plan["delete_closures"][0]
    result = await script.apply(
        plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7
    )
    assert result["preparation_complete"] and result["delete_closures"] == 1
    writes = history.fga.writes
    assert (
        await script.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    )["preparation_complete"]
    assert history.fga.writes == writes
    assert not any(rel == "permission_enabled" and obj == "knowledge_file:30" for _, rel, obj in history.fga.present)
    async with script.global_session(history.sessions) as session:
        row = await session.get(original.KnowledgeFile, 30)
        assert row is not None and row.level == 1
        mode = await session.get(ResourcePermissionMode, 30)
        assert mode.version == before["mode"]["version"] + 1 and mode.projection_state == "CURRENT"
    followup = await script.capture(history.sessions, history.fga)
    assert not followup["delete_closures"] and len(followup["permission_delete_retained"]) == 1


@pytest.mark.parametrize("drift", ["payload", "user_marker", "receipt", "pin"])
async def test_changed_selected_facts_block_before_closure_writes(history, drift):
    pin = await seed(history)
    items, retained = await closure.capture(history.sessions, history.fga, pin=pin)
    plan = {"pin": pin, "delete_closures": items, "permission_delete_retained": retained}
    if drift == "user_marker":
        history.fga.present.add(("user:*", "permission_enabled", "knowledge_file:30"))
    elif drift == "payload":
        async with script.global_session(history.sessions) as session:
            row = await session.get(original.KnowledgeFile, 30)
            row.file_name = "changed"
            session.add(row)
    elif drift == "receipt":
        async with script.global_session(history.sessions) as session:
            row = await session.get(PermissionProjectionOperation, 7001)
            row.request_checksum = "f" * 64
            session.add(row)
    else:
        plan["pin"] = pin | {"model_checksum": "f" * 64}
    writes = history.fga.writes
    with pytest.raises(BaseErrorCode):
        await closure.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    assert history.fga.writes == writes


@pytest.mark.parametrize("boundary", ["prepared", "ack", "finalized"])
async def test_original_plan_resumes_across_reservation_unknown_commit_and_finalize(history, monkeypatch, boundary):
    pin = await seed(history)
    items, retained = await closure.capture(history.sessions, history.fga, pin=pin)
    plan = {"pin": pin, "delete_closures": items, "permission_delete_retained": retained}
    projection = history.runtime._projection
    original_call = projection.prepare if boundary == "prepared" else projection.recover_failed_closed_operation
    fired = False

    async def fail(*args, **kwargs):
        nonlocal fired
        result = await original_call(*args, **kwargs)
        if not fired:
            fired = True
            raise RuntimeError("lost response")
        return result

    if boundary == "ack":
        original_write = history.fga.write_atomic

        async def unknown(**kwargs):
            nonlocal fired
            result = await original_write(**kwargs)
            if not fired:
                fired = True
                raise TimeoutError("unknown commit")
            return result

        monkeypatch.setattr(history.fga, "write_atomic", unknown)
    else:
        monkeypatch.setattr(
            projection, "prepare" if boundary == "prepared" else "recover_failed_closed_operation", fail
        )
    try:
        await closure.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    except (RuntimeError, BaseErrorCode):
        pass  # Expected injected boundary; the same native plan must resume.
    assert fired
    receipts = await closure.apply(
        plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7
    )
    assert len(receipts) == 1
    with tenant_execution_scope(101):
        async with history.sessions() as session, session.begin():
            rows = (
                await session.exec(
                    select(PermissionProjectionOperation).where(
                        PermissionProjectionOperation.idempotency_key.like("history-delete-closure:%")
                    )
                )
            ).all()
            assert len(rows) == 1 and rows[0].status == "FINALIZED"


@pytest.mark.parametrize("count", [4, 8])
async def test_selected_closure_preview_apply_verify_and_resume_have_linear_cost(history, count, record_property):
    from test.knowledge_unification.test_migration_resource_repository import file

    async with script.global_session(history.sessions) as session:
        pin = await script.read_pin(session)
        for i in range(count):
            ident = 100 + i
            session.add(original.KnowledgeFile(**file(ident, knowledge_id=10)))
            operation, tuples = receipt(
                9000 + i,
                "knowledge_file",
                str(ident),
                1,
                store_id=pin["store_id"],
                model_id=pin["model_id"],
                subjects=("user:*",),
            )
            session.add_all(
                [
                    operation,
                    *tuples,
                    ResourcePermissionMode(
                        id=ident,
                        tenant_id=101,
                        resource_type="knowledge_file",
                        resource_id=str(ident),
                        mode="INHERIT",
                        parent_type="knowledge_library",
                        parent_id="10",
                        version=2,
                        operation_id=operation.id,
                        projection_state="CURRENT",
                    ),
                ]
            )
            history.fga.present.add(("service_account:*", "permission_enabled", f"knowledge_file:{ident}"))
    statements, commits = [], []

    def statement(_conn, _cursor, sql, _parameters, _context, _many):
        statements.append(sql)

    def commit(_connection):
        commits.append(True)

    sa.event.listen(history.db.engine.sync_engine, "before_cursor_execute", statement)
    sa.event.listen(history.db.engine.sync_engine, "commit", commit)
    items, retained = await closure.capture(history.sessions, history.fga, pin=pin)
    plan = {"pin": pin, "delete_closures": items, "permission_delete_retained": retained}
    await closure.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    writes = history.fga.writes
    await closure.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    assert len(items) == count and history.fga.writes == writes == count
    assert len(statements) < count * 230 + 40
    record_property("resources", count)
    record_property("sql", len(statements))
    record_property("commits", len(commits))
    record_property("atomic_writes", writes)
