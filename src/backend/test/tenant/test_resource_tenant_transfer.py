"""Native transaction + real projection journal; only physical FGA transport is isolated."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.permission import PermissionProjectionFailedError, PermissionPublishNotReadyError
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.tenant import Tenant
from bisheng.permission.application.sql_runtime import SqlProjectionFinalizer, SqlProjectionScopeGuard
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionProjectionOperation,
    PermissionProjectionTuple,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.services.projection_service import ProjectionService
from bisheng.permission.domain.services.tenant_transfer_policy import checksum, compile_transfer
from bisheng.tenant.application.resource_tenant_transfer import ResourceTenantTransferApplication
from test.knowledge_unification.test_model_share_projection_deferred import Marker, Transport


@pytest.fixture
async def transfer():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    models = (
        Tenant,
        Assistant,
        AuthorizationModelRelease,
        PermissionCatalogRelease,
        PermissionProjectionOperation,
        PermissionProjectionTuple,
        PermissionGrant,
        PermissionGrantAssignee,
        PermissionVisibleSourceProjection,
        ResourcePermissionMode,
    )
    metadata = sa.MetaData()
    pending = [model.__table__ for model in models]
    while pending:
        original = pending.pop()
        if original.name in metadata.tables:
            continue
        table = original.to_metadata(metadata)
        if "id" in table.c and isinstance(table.c.id.type, sa.BigInteger):
            table.c.id.type = sa.Integer()
        pending.extend(foreign.column.table for foreign in original.foreign_keys)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    class TransferTransport(Transport):
        async def read_object(self, key):
            return frozenset(row for row in self.present if row[2] == key)

    transport = TransferTransport()
    projection = ProjectionService(
        repository=ProjectionRepository(sessions),
        marker=Marker(),
        fga=transport,
        scope_guard=SqlProjectionScopeGuard(session_factory=sessions),
        finalizer=SqlProjectionFinalizer(session_factory=sessions),
    )
    app = ResourceTenantTransferApplication(projection=projection, session_factory=sessions)
    async with sessions() as session, session.begin():
        session.add(Tenant(id=1, tenant_code="root", tenant_name="Root", status="active"))
        session.add(Tenant(id=18, tenant_code="child", tenant_name="Child", status="active"))
        session.add(Assistant(id="assistant-a", name="a", tenant_id=18, user_id=7, status=2))
        session.add(Assistant(id="unrelated", name="untouched", tenant_id=1, user_id=8, status=2))
        session.add(
            AuthorizationModelRelease(
                id=1,
                environment="test",
                store_id="store",
                model_id="model",
                model_version="v1",
                model_checksum="a" * 64,
                required_relations_checksum="b" * 64,
                openfga_version="1",
                status="ACTIVE",
            )
        )
        session.add(
            PermissionCatalogRelease(
                id=1,
                release_key="catalog",
                version=1,
                status="CURRENT",
                required_authorization_model_release_id=1,
                draft_owner_id=7,
                idempotency_key="catalog",
                checksum="c" * 64,
            )
        )
        session.add(
            ResourcePermissionMode(
                id=1,
                tenant_id=18,
                resource_type="assistant",
                resource_id="assistant-a",
                mode="CUSTOM",
                version=1,
                projection_state="CURRENT",
            )
        )
        session.add(
            PermissionGrant(
                id=1,
                tenant_id=18,
                resource_type="assistant",
                resource_id="assistant-a",
                model_key="owner",
                state="ACTIVE",
                version=1,
                projection_state="CURRENT",
            )
        )
        session.add(
            PermissionGrantAssignee(
                id=1,
                tenant_id=18,
                grant_id=1,
                subject_type="user",
                subject_id="7",
                source_type="CREATOR",
                source_ref="assistant:assistant-a",
                source_locator="creator:assistant:assistant-a",
                source_fingerprint="a" * 64,
                projected_subject="user:7",
                protected=True,
                state="ACTIVE",
                version=1,
            )
        )
        session.add(
            PermissionVisibleSourceProjection(
                id=1,
                tenant_id=18,
                resource_type="assistant",
                resource_id="assistant-a",
                visibility_class="protected",
                projected_subject="user:7",
                source_kind="GRANT_ASSIGNEE",
                source_owner_key="grant_assignee:1",
                source_locator="creator:assistant:assistant-a",
                source_fingerprint="a" * 64,
                contribution_fingerprint="b" * 64,
                model_key="owner",
                source_version=1,
                tuple_fingerprint="c" * 64,
                state="ACTIVE",
            )
        )
    preview = await app.preview(source=18, tables=("assistant",))
    plan = compile_transfer(preview["permissions"][0], source=18, destination=1, pin=preview["pin"], operator_id=7)
    transport.present.update(row.key for row in plan.deltas if row.action == "DELETE")
    transport.present.add(("user:7", "visible", "assistant:assistant-a"))
    transport.present.add(("user:*", "custom_mode", "assistant:assistant-a"))
    transport.present.add(("service_account:*", "custom_mode", "assistant:assistant-a"))
    try:
        yield SimpleNamespace(
            app=app, sessions=sessions, engine=engine, transport=transport, preview=preview, plan=plan
        )
    finally:
        await engine.dispose()


async def test_business_permission_and_journal_move_together_then_actual_graph_changes(transfer):
    t = transfer
    before = set(t.transport.present)
    counts = await t.app.unmount(source=18, tables=("assistant",), filters={}, operator_id=7)
    assert counts == {"assistant": 1}
    async with t.sessions() as session:
        assert (await session.get(Assistant, "assistant-a")).tenant_id == 1
        assert (await session.get(Assistant, "unrelated")).tenant_id == 1
        assert (await session.get(Tenant, 18)).status == "disabled"  # Service archives only after this success.
        mode = await session.get(ResourcePermissionMode, 1)
        assert (mode.tenant_id, mode.version, mode.projection_state) == (1, 2, "CURRENT")
        grant = await session.get(PermissionGrant, 1)
        assert (grant.tenant_id, grant.model_key, grant.state, grant.projection_state) == (
            1,
            "owner",
            "ACTIVE",
            "CURRENT",
        )
        source = await session.get(PermissionGrantAssignee, 1)
        assert (source.tenant_id, source.subject_id, source.source_fingerprint, source.protected) == (
            1,
            "7",
            "a" * 64,
            True,
        )
        visible = await session.get(PermissionVisibleSourceProjection, 1)
        assert (visible.tenant_id, visible.contribution_fingerprint, visible.state) == (1, "b" * 64, "ACTIVE")
        journals = (await session.execute(sa.select(PermissionProjectionOperation))).scalars().all()
        assert len(journals) == 1 and journals[0].status == "FINALIZED"
    expected = (before - {row.key for row in t.plan.deltas if row.action == "DELETE"}) | {
        row.key for row in t.plan.deltas if row.action == "WRITE"
    }
    assert t.transport.present == expected
    assert ("user:7", "visible", "assistant:assistant-a") in t.transport.present
    writes = t.transport.writes
    assert await t.app.unmount(source=18, tables=("assistant",), filters={}, operator_id=7) == {"assistant": 0}
    assert t.transport.writes == writes


async def test_any_business_sql_failure_rolls_back_all_mirrors_and_original_journal(transfer, monkeypatch):
    t = transfer
    monkeypatch.setattr(t.app.business, "move", AsyncMock(side_effect=RuntimeError("injected SQL failure")))
    with pytest.raises(RuntimeError, match="injected SQL failure"):
        await t.app.apply(t.preview, operator_id=7, expected_checksum=checksum(t.preview))
    assert t.transport.writes == 0
    async with t.sessions() as session:
        assert (await session.get(Assistant, "assistant-a")).tenant_id == 18
        assert (await session.get(ResourcePermissionMode, 1)).tenant_id == 18
        assert (await session.get(PermissionGrant, 1)).tenant_id == 18
        assert (await session.get(PermissionGrantAssignee, 1)).tenant_id == 18
        assert not (await session.execute(sa.select(PermissionProjectionOperation))).scalars().all()


async def test_crash_after_sql_commit_resumes_original_operation_without_rewriting_authorizations(
    transfer, monkeypatch
):
    t = transfer
    from bisheng.tenant.application import resource_tenant_transfer as module

    original = module.resume_transfer
    monkeypatch.setattr(module, "resume_transfer", AsyncMock(side_effect=RuntimeError("process exited")))
    with pytest.raises(RuntimeError, match="process exited"):
        await t.app.apply(t.preview, operator_id=7, expected_checksum=checksum(t.preview))
    async with t.sessions() as session:
        assert (await session.get(Assistant, "assistant-a")).tenant_id == 1
        mode = await session.get(ResourcePermissionMode, 1)
        assert mode.projection_state == "PROJECTING"
        ident = mode.operation_id
    monkeypatch.setattr(module, "resume_transfer", original)
    assert await t.app.resume(source=18) == 1
    async with t.sessions() as session:
        assert (await session.get(ResourcePermissionMode, 1)).projection_state == "CURRENT"
        assert (await session.get(ResourcePermissionMode, 1)).operation_id == ident
        assert len((await session.execute(sa.select(PermissionProjectionOperation))).scalars().all()) == 1


@pytest.mark.parametrize("damage", ["destination", "source_changed", "physical", "pending", "pin"])
async def test_conflicting_scope_refuses_before_any_transfer(transfer, damage):
    t = transfer
    async with t.sessions() as session, session.begin():
        if damage == "destination":
            session.add(
                ResourcePermissionMode(
                    id=2,
                    tenant_id=1,
                    resource_type="assistant",
                    resource_id="assistant-a",
                    mode="CUSTOM",
                    version=1,
                    projection_state="CURRENT",
                )
            )
        elif damage == "source_changed":
            (await session.get(PermissionGrantAssignee, 1)).subject_id = "8"
        elif damage == "pending":
            (await session.get(ResourcePermissionMode, 1)).projection_state = "PROJECTING"
        elif damage == "pin":
            (await session.get(PermissionCatalogRelease, 1)).checksum = "d" * 64
    if damage == "physical":
        t.transport.present.discard(
            (
                "user:7",
                "protected_assignee",
                next(
                    row.object
                    for row in t.plan.deltas
                    if row.relation == "protected_assignee" and row.action == "DELETE"
                ),
            )
        )
    with pytest.raises(PermissionPublishNotReadyError):
        await t.app.apply(t.preview, operator_id=7, expected_checksum=checksum(t.preview))
    assert t.transport.writes == 0
    async with t.sessions() as session:
        assert (await session.get(Assistant, "assistant-a")).tenant_id == 18


async def test_failed_physical_write_recovers_same_frozen_journal(transfer, monkeypatch):
    t = transfer
    original = t.transport.write_atomic
    failures = 1

    async def fail_once(**kwargs):
        nonlocal failures
        if failures:
            failures -= 1
            raise RuntimeError("transient FGA error")
        return await original(**kwargs)

    monkeypatch.setattr(t.transport, "write_atomic", fail_once)
    with pytest.raises(PermissionProjectionFailedError):
        await t.app.apply(t.preview, operator_id=7, expected_checksum=checksum(t.preview))
    async with t.sessions() as session:
        mode = await session.get(ResourcePermissionMode, 1)
        ident = mode.operation_id
        assert mode.tenant_id == 1 and mode.projection_state != "CURRENT"
    assert await t.app.resume(source=18) == 1
    async with t.sessions() as session:
        mode = await session.get(ResourcePermissionMode, 1)
        assert (mode.operation_id, mode.projection_state) == (ident, "CURRENT")
        assert (await session.get(PermissionGrantAssignee, 1)).subject_id == "7"


@pytest.mark.parametrize("damage", ["unknown_binding", "unknown_old_source", "orphan_new_node"])
async def test_untracked_physical_sources_are_not_silently_carried_or_overwritten(transfer, damage):
    t = transfer
    old = next(row.object for row in t.plan.deltas if row.relation == "model" and row.action == "DELETE")
    new = next(row.object for row in t.plan.deltas if row.relation == "model" and row.action == "WRITE")
    key = {
        "unknown_binding": ("permission_grant:unexpected", "grant", "assistant:assistant-a"),
        "unknown_old_source": ("user:99", "ordinary_assignee", old),
        "orphan_new_node": ("user:99", "ordinary_assignee", new),
    }[damage]
    t.transport.present.add(key)
    with pytest.raises(PermissionPublishNotReadyError):
        await t.app.apply(t.preview, operator_id=7, expected_checksum=checksum(t.preview))
    assert t.transport.writes == 0


async def test_tenant_audience_is_preserved_without_widening_it_to_root(transfer):
    t = transfer
    async with t.sessions() as session, session.begin():
        row = await session.get(PermissionGrantAssignee, 1)
        row.subject_type, row.subject_id, row.projected_subject, row.protected = (
            "tenant",
            "18",
            "tenant:18#member",
            False,
        )
        visible = await session.get(PermissionVisibleSourceProjection, 1)
        visible.projected_subject, visible.visibility_class = "tenant:18#member", "ordinary"
    preview = await t.app.preview(source=18, tables=("assistant",))
    compiled = compile_transfer(preview["permissions"][0], source=18, destination=1, pin=preview["pin"], operator_id=7)
    t.transport.present = {row.key for row in compiled.deltas if row.action == "DELETE"}
    t.transport.present.update(
        {("user:*", "custom_mode", compiled.scope_key), ("service_account:*", "custom_mode", compiled.scope_key)}
    )
    t.transport.present.add(("tenant:18#member", "visible", compiled.scope_key))
    await t.app.apply(preview, operator_id=7, expected_checksum=checksum(preview))
    assert any(row[0] == "tenant:18#member" for row in t.transport.present)
    assert not any(row[0] == "tenant:1#member" for row in t.transport.present)


@pytest.mark.parametrize(
    "table,row,expected",
    [
        ("assistant", {"id": "a"}, "assistant"),
        ("flow", {"id": "f"}, "workflow"),
        ("channel", {"id": "c"}, "channel"),
        ("t_gpts_tools_type", {"id": 2}, "tool"),
        ("knowledge", {"id": 3, "type": 3}, "knowledge_space"),
        ("knowledge", {"id": 4, "type": 1}, "knowledge_library"),
        ("knowledgefile", {"id": 5, "file_type": 0}, "folder"),
        ("knowledgefile", {"id": 6, "file_type": 1}, "knowledge_file"),
    ],
)
def test_every_unmount_permission_resource_kind_is_classified(table, row, expected):
    from bisheng.tenant.domain.repositories.resource_tenant_transfer_repository import resource_kind

    assert resource_kind(table, row) == expected


async def test_historical_preview_roundtrips_json_and_full_cli_verification(transfer):
    import json

    from bisheng.database.models.audit_log import AuditLog
    from bisheng.permission.application.tenant_resource_transfer import verify_transfer_input
    from scripts.repair_unmounted_tenant_permissions import verify

    t = transfer
    async with t.engine.begin() as conn:
        await conn.run_sync(lambda active: AuditLog.__table__.create(active, checkfirst=True))
    async with t.sessions() as session, session.begin():
        (await session.get(Tenant, 18)).status = "archived"
        (await session.get(Assistant, "assistant-a")).tenant_id = 1
        session.add(
            AuditLog(
                id="unmount-audit",
                operator_id=7,
                tenant_id=18,
                action="tenant.unmount",
                target_type="tenant",
                target_id="18",
            )
        )
    preview = await t.app.preview(source=18, historical=True)
    assert preview["resources"] == (("assistant", "assistant-a"),)
    graph = await verify_transfer_input(
        t.app.projection, preview["permissions"], source=18, destination=1, pin=preview["pin"], operator_id=7
    )
    saved = json.loads(json.dumps(preview, default=str))
    assert checksum(saved) == checksum(preview)
    await t.app.apply(saved, operator_id=7, expected_checksum=checksum(saved))
    await verify(t.app, saved, {key: sorted(rows) for key, rows in graph.items()}, operator_id=7)
    assert not (await t.app.preview(source=18, historical=True))["resources"]


async def test_inherit_mode_does_not_rewrite_parent_or_mode_predicates(transfer):
    from copy import deepcopy

    snapshot = deepcopy(transfer.preview["permissions"][0])
    snapshot["mode"].update(
        resource_type="knowledge_file", resource_id="81", mode="INHERIT", parent_type="knowledge_space", parent_id="99"
    )
    for grant in snapshot["grants"]:
        grant.update(resource_type="knowledge_file", resource_id="81")
    plan = compile_transfer(snapshot, source=18, destination=1, pin=transfer.preview["pin"], operator_id=7)
    assert all(row.relation not in {"parent", "custom_mode", "inherit_mode", "visible"} for row in plan.deltas)
    assert snapshot["mode"]["parent_id"] == "99"


@pytest.mark.parametrize(
    "table,row", [("flow", {"id": "internal", "flow_type": 15}), ("knowledge", {"id": 19, "type": 2})]
)
def test_retired_or_internal_rows_do_not_invent_permission_namespaces(table, row):
    from bisheng.tenant.domain.repositories.resource_tenant_transfer_repository import resource_kind

    assert resource_kind(table, row) is None


_SCALE = {}


@pytest.mark.parametrize("size", [4, 8])
async def test_preview_apply_verify_resume_cost_is_linear_in_actual_resources(transfer, size):
    import json
    import time
    import tracemalloc
    from copy import deepcopy

    from bisheng.permission.application.tenant_resource_transfer import verify_transfer_input
    from scripts.repair_unmounted_tenant_permissions import verify

    t = transfer
    models = (ResourcePermissionMode, PermissionGrant, PermissionGrantAssignee, PermissionVisibleSourceProjection)
    async with t.sessions() as session, session.begin():
        originals = [await session.get(model, 1) for model in models]
        for index in range(2, size + 1):
            ident = f"assistant-{index}"
            session.add(Assistant(id=ident, name=ident, tenant_id=18, user_id=7, status=2))
            for model, original in zip(models, originals, strict=True):
                data = {column.name: deepcopy(getattr(original, column.name)) for column in model.__table__.c}
                data["id"] = index
                if "resource_id" in data:
                    data["resource_id"] = ident
                if model is PermissionGrantAssignee:
                    data["grant_id"] = index
                if model is PermissionVisibleSourceProjection:
                    data["source_owner_key"] = f"grant_assignee:{index}"
                session.add(model(**data))
    preview = await t.app.preview(source=18, tables=("assistant",))
    for snapshot in preview["permissions"]:
        plan = compile_transfer(snapshot, source=18, destination=1, pin=preview["pin"], operator_id=7)
        t.transport.present.update(row.key for row in plan.deltas if row.action == "DELETE")
        t.transport.present.update(
            {
                ("user:*", "custom_mode", plan.scope_key),
                ("service_account:*", "custom_mode", plan.scope_key),
                ("user:7", "visible", plan.scope_key),
            }
        )
    sql, transactions, reads = [], [], []
    sa.event.listen(t.engine.sync_engine, "before_cursor_execute", lambda *args: sql.append(args[2]))
    sa.event.listen(t.engine.sync_engine, "begin", lambda *args: transactions.append(1))
    original_read = t.transport.read_object

    async def read(key):
        reads.append(key)
        return await original_read(key)

    t.transport.read_object = read
    started = time.perf_counter()
    tracemalloc.start()
    try:
        preview = await t.app.preview(source=18, tables=("assistant",))
        graph = await verify_transfer_input(
            t.app.projection, preview["permissions"], source=18, destination=1, pin=preview["pin"], operator_id=7
        )
        await t.app.apply(preview, operator_id=7, expected_checksum=checksum(preview))
        await verify(t.app, preview, graph, operator_id=7)
        assert await t.app.resume(source=18) == 0
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    result = {
        "resources": size,
        "sql": len(sql),
        "transactions": len(transactions),
        "graph_reads": len(reads),
        "physical_writes": t.transport.writes,
        "peak_bytes": peak,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    _SCALE[size] = result
    print("TRANSFER_SCALE=" + json.dumps(result))
    if size == 8 and 4 in _SCALE:
        for key in ("sql", "transactions", "graph_reads", "physical_writes"):
            assert _SCALE[8][key] <= _SCALE[4][key] * 2 + 5


async def test_frozen_full_graph_change_is_refused_before_sql_commit(transfer):
    t = transfer
    from bisheng.permission.application.tenant_resource_transfer import verify_transfer_input

    graph = await verify_transfer_input(
        t.app.projection, t.preview["permissions"], source=18, destination=1, pin=t.preview["pin"], operator_id=7
    )
    graph = {key: sorted(rows) for key, rows in graph.items()}
    t.transport.present.add(("tenant:99", "shared_with", "assistant:assistant-a"))
    with pytest.raises(PermissionPublishNotReadyError):
        await t.app.apply(t.preview, operator_id=7, expected_checksum=checksum(t.preview), expected_graph=graph)
    async with t.sessions() as session:
        assert (await session.get(ResourcePermissionMode, 1)).tenant_id == 18
    assert t.transport.writes == 0


async def test_maintenance_resume_is_restricted_to_confirmed_resources(transfer, monkeypatch):
    t = transfer
    from bisheng.tenant.application import resource_tenant_transfer as module

    original = module.resume_transfer
    monkeypatch.setattr(module, "resume_transfer", AsyncMock(side_effect=RuntimeError("stopped")))
    with pytest.raises(RuntimeError, match="stopped"):
        await t.app.apply(t.preview, operator_id=7, expected_checksum=checksum(t.preview))
    monkeypatch.setattr(module, "resume_transfer", original)
    assert await t.app.resume(source=18, resources=(("assistant", "a-different-resource"),)) == 0
    assert t.transport.writes == 0
    assert await t.app.resume(source=18, resources=(("assistant", "assistant-a"),)) == 1
