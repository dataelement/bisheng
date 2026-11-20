"""Native history apply/replay with OpenFGA's strict atomic delete semantics."""

import asyncio
import time
import tracemalloc
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.permission import PermissionProjectionFailedError, PermissionVersionConflictError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.permission.domain.models import (
    PermissionProjectionOperation,
    PermissionProjectionTuple,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.deleted_resource_repository import DeletedResourceRepository
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from scripts import prepare_f118_history as module
from test.knowledge_unification import test_prepare_history as fixtures

history, native, resource_native = fixtures.history, fixtures.native, fixtures.resource_native


@pytest.fixture
def strict_fga(history, monkeypatch):
    transport = history.fga
    original = transport.write_atomic
    original_read = transport.read_present
    stats = SimpleNamespace(attempts=[], reads=0, keys=0)

    async def write_atomic(*, writes, deletes):
        stats.attempts.append(tuple(delta.key for delta in deletes))
        # OpenFGA rejects the entire atomic request if any DELETE is absent.
        if any(delta.key not in transport.present for delta in deletes):
            raise RuntimeError("cannot delete a tuple which does not exist")
        return await original(writes=writes, deletes=deletes)

    async def read_present(deltas, *, consistency):
        assert consistency == "HIGHER_CONSISTENCY"
        stats.reads += 1
        stats.keys += len(deltas)
        return await original_read(deltas, consistency=consistency)

    monkeypatch.setattr(transport, "write_atomic", write_atomic)
    monkeypatch.setattr(transport, "read_present", read_present)
    return stats


def marker(subject, resource_id=999):
    return (subject, "permission_enabled", f"knowledge_file:{resource_id}")


async def apply(history, plan):
    return await module.apply(
        plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7
    )


async def delete_operation(history, plan):
    key = f"history-delete:{module.checksum(plan)[:32]}:999"
    with tenant_execution_scope(101):
        return await DeletedResourceRepository(history.sessions).aget_operation_by_idempotency(key)


async def stop_like_old_script(history, plan, monkeypatch):
    """Use the unmodified runtime to leave the same durable old-script failure."""

    async def ordinary_delete(**kwargs):
        return await kwargs["runtime"].project_delete(
            actor=kwargs["actor"], target=kwargs["target"], idempotency_key=kwargs["key"]
        )

    with monkeypatch.context() as patch:
        patch.setattr(module, "project_history_delete", ordinary_delete)
        with pytest.raises(PermissionProjectionFailedError):
            await apply(history, plan)
    operation = await delete_operation(history, plan)
    assert operation.status == "FAILED_CLOSED"
    return operation


async def assert_completed(history, plan, operation_id=None):
    async with module.global_session(history.sessions) as session:
        assert await session.get(ResourcePermissionMode, 999) is None
        assert (await session.get(KnowledgeFile, 30)).level == 1
        operations = (await session.exec(select(PermissionProjectionOperation))).all()
        assert len(operations) == 3
        assert all(operation.status == "FINALIZED" for operation in operations)
        original = next(operation for operation in operations if operation.operation_type == "RESOURCE_DELETE")
        assert original.idempotency_key == f"history-delete:{module.checksum(plan)[:32]}:999"
        assert (original.expected_version, original.target_version) == (1, 2)
        if operation_id is not None:
            assert original.id == operation_id
        rows = (
            await session.exec(
                select(PermissionProjectionTuple).where(PermissionProjectionTuple.operation_id == original.id)
            )
        ).all()
        assert {(row.action, row.fga_user, row.relation, row.fga_object) for row in rows} == {
            ("DELETE", subject, "permission_enabled", "knowledge_file:999")
            for subject in ("user:*", "service_account:*")
        }
        assert not any(row.fga_object == "knowledge_file:30" and row.relation != "parent" for row in rows)
    assert not any(obj == "knowledge_file:999" for _, _, obj in history.fga.present)
    assert ("folder:20", "parent", "knowledge_file:30") in history.fga.present


@pytest.mark.parametrize("absent", [(), ("user:*",), ("service_account:*",), ("user:*", "service_account:*")])
async def test_fresh_apply_and_replay_with_strict_fga_preserve_original_plan(
    history, strict_fga, absent, monkeypatch, tmp_path
):
    for subject in absent:
        history.fga.present.remove(marker(subject))
    plan = await module.capture(history.sessions, history.fga)
    path = tmp_path / "history.json"
    module.save_plan(path, plan)
    raw = path.read_bytes()
    inspect = AsyncMock(wraps=history.runtime._projection.inspect_failed_closed_recovery)
    monkeypatch.setattr(history.runtime._projection, "inspect_failed_closed_recovery", inspect)
    await apply(history, module.load_plan(path))
    await assert_completed(history, plan)
    assert inspect.await_count == (2 if len(absent) == 1 else 0)  # preview + recovery's checksum recheck
    attempts = len(strict_fga.attempts)
    await apply(history, module.load_plan(path))
    assert len(strict_fga.attempts) == attempts
    assert path.read_bytes() == raw
    await assert_completed(history, plan)


async def test_old_failed_operation_recovers_in_place_then_replays_without_writes(history, strict_fga, monkeypatch):
    history.fga.present.remove(marker("user:*"))
    plan = await module.capture(history.sessions, history.fga)
    before = deepcopy(plan)
    original = await stop_like_old_script(history, plan, monkeypatch)
    attempts = len(strict_fga.attempts)
    await apply(history, plan)
    assert strict_fga.attempts[attempts] == (marker("service_account:*"),)
    await assert_completed(history, plan, original.id)
    attempts = len(strict_fga.attempts)
    await apply(history, plan)
    assert len(strict_fga.attempts) == attempts and plan == before


@pytest.mark.parametrize("interruption", ["after_fga", "finalize", "sql_purge"])
async def test_recovery_interruption_resumes_original_operation_without_repeating_fga(
    history, strict_fga, monkeypatch, interruption
):
    history.fga.present.remove(marker("user:*"))
    plan = await module.capture(history.sessions, history.fga)
    fired = False
    service = history.runtime._projection
    if interruption == "after_fga":
        original = service._transition

        async def interrupt(operation, **kwargs):
            nonlocal fired
            if not fired and kwargs["expected"] == "FAILED_CLOSED" and kwargs["target"] == "COMMITTED":
                fired = True
                raise asyncio.CancelledError()
            return await original(operation, **kwargs)

        monkeypatch.setattr(service, "_transition", interrupt)
        expected_error = asyncio.CancelledError
    elif interruption == "finalize":
        original = service._finalizer.finalize

        async def interrupt(projection, operation_id):
            nonlocal fired
            if not fired and projection.idempotency_key.startswith("history-delete:"):
                fired = True
                raise RuntimeError("SQL finalize unavailable")
            return await original(projection, operation_id)

        monkeypatch.setattr(service._finalizer, "finalize", interrupt)
        expected_error = PermissionProjectionFailedError
    else:
        original = DeletedResourceRepository.purge

        async def interrupt(repository, *args):
            nonlocal fired
            if not fired:
                fired = True
                raise RuntimeError("SQL purge unavailable")
            return await original(repository, *args)

        monkeypatch.setattr(DeletedResourceRepository, "purge", interrupt)
        expected_error = RuntimeError
    with pytest.raises(expected_error):
        await apply(history, plan)
    assert fired
    operation = await delete_operation(history, plan)
    assert (
        operation.status
        == {"after_fga": "FAILED_CLOSED", "finalize": "COMMITTED", "sql_purge": "FINALIZED"}[interruption]
    )
    attempts = len(strict_fga.attempts)
    await apply(history, plan)
    # Derived purge has not run for the first two interruptions; only its write is new.
    assert len(strict_fga.attempts) == attempts + (interruption != "sql_purge")
    assert all(
        marker(subject) not in batch
        for batch in strict_fga.attempts[attempts:]
        for subject in ("user:*", "service_account:*")
    )
    await assert_completed(history, plan, operation.id)


async def test_full_original_marker_pair_does_not_authorize_unrelated_mixed_recovery(history, strict_fga, monkeypatch):
    plan = await module.capture(history.sessions, history.fga)
    # Simulate a different partial failure after a healthy baseline was frozen.
    history.fga.present.remove(marker("user:*"))
    item = plan["purges"][0]
    with tenant_execution_scope(101), pytest.raises(PermissionProjectionFailedError):
        await history.runtime.project_delete(
            actor=PermissionActor(user_id=7, current_tenant_id=101),
            target=module.target_for(item["mode"]),
            idempotency_key=f"history-delete:{module.checksum(plan)[:32]}:999",
        )
    recover = AsyncMock(wraps=history.runtime._projection.recover_failed_closed_operation)
    monkeypatch.setattr(history.runtime._projection, "recover_failed_closed_operation", recover)
    with pytest.raises(PermissionProjectionFailedError) as raised:
        await apply(history, plan)
    assert raised.value.kwargs["reason"] == "history_prepare_delete_projection_failed"
    recover.assert_not_awaited()
    assert marker("service_account:*") in history.fga.present


@pytest.mark.parametrize(
    "change",
    ["business", "downstream", "fga", "pin", "version", "fence", "ledger", "scope", "tenant", "after_checksum"],
)
async def test_old_failure_still_refuses_changed_business_graph_pin_fence_and_ledger(
    history, strict_fga, monkeypatch, change
):
    history.fga.present.remove(marker("user:*"))
    plan = await module.capture(history.sessions, history.fga)
    operation = await stop_like_old_script(history, plan, monkeypatch)
    if change in {"business", "downstream"}:
        await history.db.insert(
            KnowledgeFile,
            [
                fixtures.resources.file(
                    999 if change == "business" else 1000,
                    knowledge_id=10,
                    file_level_path="" if change == "business" else "/999",
                    level=0,
                )
            ],
        )
    elif change == "fga":
        history.fga.present.add(("user:100", "visible", "knowledge_file:999"))
    elif change == "pin":
        pin = deepcopy(plan["pin"])
        pin["model_id"] = "changed-model"
        monkeypatch.setattr(module, "read_pin", AsyncMock(return_value=pin))
    else:
        async with history.db.engine.begin() as connection:
            if change in {"version", "fence"}:
                await connection.execute(
                    sa.update(ResourcePermissionMode)
                    .where(ResourcePermissionMode.id == 999)
                    .values(**({"version": 99} if change == "version" else {"operation_id": 99999}))
                )
            elif change in {"scope", "tenant", "after_checksum"}:
                await connection.execute(
                    sa.update(PermissionProjectionOperation)
                    .where(PermissionProjectionOperation.id == operation.id)
                    .values(
                        **{
                            "scope": {"scope_key": "knowledge_file:123"},
                            "tenant": {"tenant_id": 202},
                            "after_checksum": {"after_checksum": "0" * 64},
                        }[change]
                    )
                )
            else:
                await connection.execute(
                    sa.update(PermissionProjectionTuple)
                    .where(PermissionProjectionTuple.operation_id == operation.id)
                    .values(action="WRITE")
                )
    recover = AsyncMock(wraps=history.runtime._projection.recover_failed_closed_operation)
    monkeypatch.setattr(history.runtime._projection, "recover_failed_closed_operation", recover)
    attempts = len(strict_fga.attempts)
    with pytest.raises((KnowledgeOperationPlanConflictError, PermissionVersionConflictError)):
        await apply(history, plan)
    recover.assert_not_awaited()
    assert len(strict_fga.attempts) == attempts
    assert marker("service_account:*") in history.fga.present


@pytest.mark.parametrize("change", ["proposal", "fence", "business", "pin", "graph"])
async def test_recovery_rechecks_facts_and_checksum_after_failed_attempt(history, strict_fga, monkeypatch, change):
    history.fga.present.remove(marker("user:*"))
    plan = await module.capture(history.sessions, history.fga)
    original_inspect = history.runtime._projection.inspect_failed_closed_recovery
    original_delete = history.runtime.project_delete
    changed = False

    async def mutate():
        nonlocal changed
        if changed:
            return
        changed = True
        if change == "proposal":
            history.fga.present.remove(marker("service_account:*"))
        elif change == "graph":
            history.fga.present.add(("user:100", "visible", "knowledge_file:999"))
        elif change == "business":
            await history.db.insert(
                KnowledgeFile, [fixtures.resources.file(999, knowledge_id=10, file_level_path="", level=0)]
            )
        elif change == "pin":
            pin = deepcopy(plan["pin"])
            pin["model_id"] = "changed-model"
            monkeypatch.setattr(module, "read_pin", AsyncMock(return_value=pin))
        else:
            async with history.db.engine.begin() as connection:
                await connection.execute(
                    sa.update(ResourcePermissionMode).where(ResourcePermissionMode.id == 999).values(operation_id=99999)
                )

    async def inspect(operation_id):
        result = await original_inspect(operation_id)
        if change in {"proposal", "fence"}:
            await mutate()
        return result

    async def project_delete(**kwargs):
        try:
            return await original_delete(**kwargs)
        except PermissionProjectionFailedError:
            if change in {"business", "pin", "graph"}:
                await mutate()
            raise

    monkeypatch.setattr(history.runtime._projection, "inspect_failed_closed_recovery", inspect)
    monkeypatch.setattr(history.runtime, "project_delete", project_delete)
    with pytest.raises(
        (KnowledgeOperationPlanConflictError, PermissionVersionConflictError, fixtures.PermissionPublishNotReadyError)
    ):
        await apply(history, plan)
    assert changed
    operation = await delete_operation(history, plan)
    assert operation.status == "FAILED_CLOSED"
    # Only parent repair succeeded. The initial strict pair delete was rejected;
    # no correction or derived purge was submitted after the guarded facts drifted.
    assert len(strict_fga.attempts) == 2


async def test_failed_correction_retains_original_fence_and_can_retry_same_plan(history, strict_fga, monkeypatch):
    history.fga.present.remove(marker("user:*"))
    plan = await module.capture(history.sessions, history.fga)
    original_write = history.fga.write_atomic
    failed = False

    async def write_atomic(*, writes, deletes):
        nonlocal failed
        if not failed and tuple(delta.key for delta in deletes) == (marker("service_account:*"),):
            failed = True
            raise RuntimeError("OpenFGA unavailable")
        return await original_write(writes=writes, deletes=deletes)

    monkeypatch.setattr(history.fga, "write_atomic", write_atomic)
    with pytest.raises(PermissionProjectionFailedError) as raised:
        await apply(history, plan)
    assert raised.value.kwargs["reason"] == "history_prepare_delete_recovery_failed"
    operation = await delete_operation(history, plan)
    assert operation.status == "FAILED_CLOSED"
    async with module.global_session(history.sessions) as session:
        mode = await session.get(ResourcePermissionMode, 999)
        assert (mode.version, mode.projection_state, mode.operation_id) == (1, "FAILED_CLOSED", operation.id)
    await apply(history, plan)
    await assert_completed(history, plan, operation.id)


async def test_correction_timeout_after_atomic_commit_is_verified_without_duplicate_delete(
    history, strict_fga, monkeypatch
):
    history.fga.present.remove(marker("user:*"))
    plan = await module.capture(history.sessions, history.fga)
    original_write = history.fga.write_atomic

    async def write_atomic(*, writes, deletes):
        result = await original_write(writes=writes, deletes=deletes)
        if tuple(delta.key for delta in deletes) == (marker("service_account:*"),):
            raise TimeoutError("commit response lost")
        return result

    monkeypatch.setattr(history.fga, "write_atomic", write_atomic)
    await apply(history, plan)
    assert strict_fga.attempts.count((marker("service_account:*"),)) == 1
    await assert_completed(history, plan)


async def test_completed_earlier_resource_is_not_repeated_when_next_recovery_is_interrupted(
    history, strict_fga, monkeypatch
):
    await history.db.insert(
        ResourcePermissionMode,
        [
            {
                "id": 1000,
                "tenant_id": 101,
                "resource_type": "knowledge_file",
                "resource_id": "1000",
                "mode": "INHERIT",
                "parent_type": "knowledge_library",
                "parent_id": "10",
                "version": 1,
                "projection_state": "CURRENT",
            }
        ],
    )
    history.fga.present.update(
        {marker("service_account:*", 1000), ("knowledge_library:10", "parent", "knowledge_file:1000")}
    )
    plan = await module.capture(history.sessions, history.fga)
    assert [item["mode"]["id"] for item in plan["purges"]] == [999, 1000]
    original = history.runtime._projection.recover_failed_closed_operation
    interrupted = False

    async def recover(operation_id, **kwargs):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise asyncio.CancelledError()
        return await original(operation_id, **kwargs)

    monkeypatch.setattr(history.runtime._projection, "recover_failed_closed_operation", recover)
    with pytest.raises(asyncio.CancelledError):
        await apply(history, plan)
    async with module.global_session(history.sessions) as session:
        assert await session.get(ResourcePermissionMode, 999) is None
        assert (await session.get(ResourcePermissionMode, 1000)).projection_state == "FAILED_CLOSED"
        previous_ids = {row.id for row in (await session.exec(select(PermissionProjectionOperation))).all()}
    attempts = len(strict_fga.attempts)
    await apply(history, plan)
    assert all(delta[2] != "knowledge_file:999" for batch in strict_fga.attempts[attempts:] for delta in batch)
    async with module.global_session(history.sessions) as session:
        assert await session.get(ResourcePermissionMode, 1000) is None
        rows = (await session.exec(select(PermissionProjectionOperation))).all()
        assert len(rows) == 5 and previous_ids < {row.id for row in rows}
        assert all(row.status == "FINALIZED" for row in rows)


@contextmanager
def sql_count(engine):
    stats = SimpleNamespace(statements=[], commits=0)

    def record(conn, cursor, statement, params, context, many):
        stats.statements.append(statement)

    def commit(conn):
        stats.commits += 1

    sa.event.listen(engine.sync_engine, "before_cursor_execute", record)
    sa.event.listen(engine.sync_engine, "commit", commit)
    try:
        yield stats
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", record)
        sa.event.remove(engine.sync_engine, "commit", commit)


@pytest.mark.parametrize("count", [8, 16])
async def test_many_partial_markers_use_bounded_exact_reads_and_linear_writes(
    history, strict_fga, count, record_property
):
    history.fga.present.remove(marker("user:*"))
    for ident in range(1000, 1000 + count - 1):
        await history.db.insert(
            ResourcePermissionMode,
            [
                {
                    "id": ident,
                    "tenant_id": 101,
                    "resource_type": "knowledge_file",
                    "resource_id": str(ident),
                    "mode": "INHERIT",
                    "parent_type": "knowledge_library",
                    "parent_id": "10",
                    "version": 1,
                    "projection_state": "CURRENT",
                }
            ],
        )
        history.fga.present.update(
            {marker("service_account:*", ident), ("knowledge_library:10", "parent", f"knowledge_file:{ident}")}
        )
    plan = await module.capture(history.sessions, history.fga)
    assert len(plan["purges"]) == count
    tracemalloc.start()
    started = time.perf_counter()
    try:
        with sql_count(history.db.engine) as stats:
            await apply(history, plan)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    record_property("resources", count)
    record_property("sql", len(stats.statements))
    record_property("sql_commits", stats.commits)
    record_property("exact_reads", strict_fga.reads)
    record_property("exact_keys", strict_fga.keys)
    record_property("peak_python_bytes", peak)
    record_property("apply_seconds", time.perf_counter() - started)
    assert len(strict_fga.attempts) == count * 3 + 1  # rejected pair, correction, purge, plus parent repair
    assert strict_fga.keys <= count * 24 + 4
    assert len(stats.statements) <= count * 125 + 100
    writes = len(strict_fga.attempts)
    await apply(history, plan)
    assert len(strict_fga.attempts) == writes


def test_cli_error_reports_safe_operation_details_without_provider_message(tmp_path, monkeypatch, capsys):
    async def failed(args):
        raise PermissionProjectionFailedError(
            msg="secret provider configuration",
            reason="history_prepare_delete_projection_failed",
            operation_id=123,
            projection_status="FAILED_CLOSED",
        )

    monkeypatch.setattr(module, "arun", failed)
    assert module.main(["--plan", str(tmp_path / "plan.json"), "--apply", "--operator-id", "7"]) == 3
    output = capsys.readouterr().err
    assert '"operation_id": 123' in output
    assert '"reason": "history_prepare_delete_projection_failed"' in output
    assert "secret provider configuration" not in output
