"""Native incomplete intent recovery preserves payloads and refuses drift."""

import pytest
from sqlmodel import select

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill
from bisheng.permission.domain.models import PermissionGrant, PermissionGrantAssignee
from bisheng.permission.domain.models import PermissionProjectionOperation as Operation
from bisheng.permission.domain.models import PermissionVisibleSourceProjection as Source
from bisheng.permission.domain.models import ResourcePermissionMode as Mode
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.projection_plan import (
    build_projection_operation,
    normalize_projection_plan,
    projection_request_checksum,
)
from bisheng.permission.domain.services.resource_lifecycle_policy import build_create_plan
from scripts import f118_delete_closure as closure
from scripts import f118_history_permissions as permissions
from scripts import prepare_f118_history as script
from test.knowledge_unification import test_history_delete_closure as original

resource_native, native, history = original.resource_native, original.native, original.history


@pytest.mark.parametrize("markers", [(), ("user:*",), ("user:*", "service_account:*")])
async def test_old_failed_delete_uses_current_pin_new_receipt_and_retains_payload(history, markers):
    pin = await original.seed(history, marker=False)
    async with script.global_session(history.sessions) as session:
        old, rows = original.receipt(7002, "knowledge_file", "30", 1, store_id=pin["store_id"], model_id="old-model")
        old.status = "FAILED_CLOSED"
        session.add_all([old, *rows])
        mode = await session.get(Mode, 30)
        mode.version, mode.operation_id = 1, old.id
        session.add(mode)
    history.fga.present.update((subject, "permission_enabled", "knowledge_file:30") for subject in markers)
    items, retained = await closure.capture(history.sessions, history.fga, pin=pin)
    assert len(items) == 1 and not retained and items[0]["source_status"] == "FAILED_CLOSED"
    plan = {"pin": pin, "delete_closures": items}
    await closure.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    writes = history.fga.writes
    await closure.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    assert history.fga.writes == writes
    async with script.global_session(history.sessions) as session:
        assert (await session.get(Operation, 7002)).status == "FAILED_CLOSED"
        assert await session.get(original.original.KnowledgeFile, 30) is not None
        mode = await session.get(Mode, 30)
        assert mode.version == 2 and mode.projection_state == "CURRENT" and mode.operation_id != 7002
    assert not any(rel == "permission_enabled" and obj == "knowledge_file:30" for _, rel, obj in history.fga.present)


async def seed_builtin(history, status="FAILED_CLOSED", ident=8000):
    original_read = history.fga.read_tuples

    async def read(*, user=None, **kwargs):
        return [row for row in await original_read(**kwargs) if user is None or row["user"] == user]

    history.fga.read_tuples = read
    async with history.db.engine.begin() as connection:
        await connection.run_sync(lambda c: LinsightSkill.__table__.create(c, checkfirst=True))
    async with script.global_session(history.sessions) as session:
        pin = await script.read_pin(session)
        mode = Mode(
            id=ident,
            tenant_id=101,
            resource_type="linsight_skill",
            resource_id=str(ident),
            mode="CUSTOM",
            version=0,
            projection_state="FAILED_CLOSED",
            operation_id=ident,
        )
        target = VerifiedPermissionTarget.from_business_service(
            tenant_id=101,
            resource_type="linsight_skill",
            resource_id=str(ident),
            resource_version=0,
            context_version="test",
        )
        plan = normalize_projection_plan(
            build_create_plan(
                target,
                store_id=pin["store_id"],
                model_id=pin["model_id"],
                operator_id=7,
                idempotency_key=f"builtin:{ident}",
                protected_deltas=(),
            )
        )
        operation, rows = build_projection_operation(plan, request_checksum=projection_request_checksum(plan))
        operation.id, operation.status = ident, status
        for seq, row in enumerate(rows):
            row.id, row.operation_id = ident * 10 + seq, ident
        source = Source(
            id=ident,
            tenant_id=101,
            resource_type="linsight_skill",
            resource_id=str(ident),
            visibility_class="ordinary",
            projected_subject="user:7",
            source_kind="GRANT_ASSIGNEE",
            source_owner_key=f"grant_assignee:{ident}",
            source_locator="owner:7",
            source_fingerprint="a" * 64,
            contribution_fingerprint="b" * 64,
            source_version=1,
            model_key="owner",
            tuple_fingerprint="c" * 64,
            state="PENDING",
            operation_id=ident,
        )
        session.add_all(
            [
                PermissionGrant(
                    id=ident,
                    tenant_id=101,
                    resource_type="linsight_skill",
                    resource_id=str(ident),
                    model_key="owner",
                    state="ACTIVE",
                    projection_state="CURRENT",
                ),
                PermissionGrantAssignee(
                    id=ident,
                    tenant_id=101,
                    grant_id=ident,
                    subject_type="user",
                    subject_id="7",
                    source_type="DIRECT",
                    source_ref="user:7",
                    source_locator="owner:7",
                    source_fingerprint="a" * 64,
                    projected_subject="user:7",
                    protected=False,
                    state="ACTIVE",
                    version=1,
                ),
            ]
        )
        session.add_all(
            [
                mode,
                operation,
                *rows,
                source,
                LinsightSkill(
                    id=ident,
                    tenant_id=101,
                    name=f"builtin-test-{ident}",
                    description="native",
                    source="builtin",
                    owner_user_id=0,
                    created_by=None,
                    object_path="skills/8000",
                    content_hash="a" * 64,
                ),
            ]
        )
        history.fga.present.update(delta.key for delta in plan.deltas)
    return pin


@pytest.mark.parametrize("status", ["FAILED_CLOSED", "COMMITTED"])
async def test_after_only_native_finalize_and_resume_has_no_fga_writes(history, status, tmp_path):
    pin = await seed_builtin(history, status)
    items = await permissions.capture_builtin_finalizations(history.sessions, history.fga, pin)
    assert len(items) == 1 and items[0]["preview"]["observed_state"] == "AFTER"
    writes = history.fga.writes
    path = tmp_path / "plan.json"
    plan = {"schema": 3, "pin": pin, "builtin_finalizations": items}
    script.save_plan(path, plan)
    assert script.load_plan(path) == plan and path.stat().st_mode & 0o777 == 0o600
    for _ in range(2):
        assert await permissions.apply_builtin_finalizations(
            script.load_plan(path), sessions=history.sessions, runtime=history.runtime
        ) == [8000]
    assert history.fga.writes == writes
    assert not await permissions.capture_builtin_finalizations(history.sessions, history.fga, pin)
    async with script.global_session(history.sessions) as session:
        assert (await session.get(Operation, 8000)).status == "FINALIZED"
        mode = await session.get(Mode, 8000)
        assert (mode.projection_state, mode.version) == ("CURRENT", 1)
        assert (await session.exec(select(Source).where(Source.operation_id == 8000))).one().state == "ACTIVE"


@pytest.mark.parametrize("drift", ["graph", "skill", "pin", "fence", "ledger"])
async def test_changed_facts_never_finalize(history, drift):
    pin = await seed_builtin(history)
    items = await permissions.capture_builtin_finalizations(history.sessions, history.fga, pin)
    if drift == "graph":
        history.fga.present.remove(("user:*", "permission_enabled", "linsight_skill:8000"))
    elif drift == "pin":
        pin = pin | {"model_id": "different"}
    else:
        async with script.global_session(history.sessions) as session:
            if drift == "skill":
                row = await session.get(LinsightSkill, 8000)
                row.source = "manual"
            elif drift == "fence":
                row = await session.get(Mode, 8000)
                row.version = 9
            else:
                row = await session.get(Operation, 8000)
                row.request_checksum = "f" * 64
            session.add(row)
    with pytest.raises(BaseErrorCode):
        await permissions.apply_builtin_finalizations(
            {"pin": pin, "builtin_finalizations": items}, sessions=history.sessions, runtime=history.runtime
        )
    assert not history.fga.writes


@pytest.mark.parametrize("count", [2, 4])
async def test_builtin_preview_apply_verify_resume_scale(history, count, record_property):
    import time

    from sqlalchemy import event

    for index in range(count):
        pin = await seed_builtin(history, ident=8000 + index)
    counts = {"sql": 0, "commits": 0, "reads": 0}

    def query(*args):
        counts["sql"] += 1

    def commit(*args):
        counts["commits"] += 1

    event.listen(history.db.engine.sync_engine, "before_cursor_execute", query)
    event.listen(history.db.engine.sync_engine, "commit", commit)
    before = history.fga.read_tuples

    async def read(**kwargs):
        counts["reads"] += 1
        return await before(**kwargs)

    history.fga.read_tuples = read
    started = time.monotonic()
    items = await permissions.capture_builtin_finalizations(history.sessions, history.fga, pin)
    plan = {"schema": 3, "pin": pin, "builtin_finalizations": items}
    for _ in range(2):
        await permissions.apply_builtin_finalizations(plan, sessions=history.sessions, runtime=history.runtime)
    assert not await permissions.capture_builtin_finalizations(history.sessions, history.fga, pin)
    counts["seconds"] = round(time.monotonic() - started, 3)
    record_property("scale", str({"count": count, **counts, "fga_writes": history.fga.writes}))
    assert counts["sql"] <= 110 * count + 3 and counts["reads"] <= 100 * count
    assert not history.fga.writes
