"""Scoped maintenance must not turn departed-member repair into broad tuple deletion."""

import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel import SQLModel, select

from bisheng.common.models.space_channel_member import SpaceChannelMember
from bisheng.permission.application import control_state
from bisheng.permission.application.sql_runtime import SqlProjectionFinalizer, SqlProjectionScopeGuard
from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionProjectionOperation,
    PermissionProjectionTuple,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.services.grant_source_service import GrantSourceService
from scripts import repair_f048_membership_orphan as cli
from test.permission.test_f048_projection_service import FakeFGAProjection, FakeRecentMarker
from test.permission.test_f048_projection_sql_runtime import session_factory as session_factory
from test.permission.test_f048_projection_sql_runtime import tenant_context as tenant_context


def args(*extra):
    return cli.parse_args(["--tenant-id", "7", "--resource-key", "knowledge_space:42", "--user-id", "11", *extra])


@pytest.mark.parametrize("extra", [[], ["--resource-key", "channel:uuid-42"]])
def test_default_is_dry_run(extra):
    assert not args(*extra).apply


@pytest.mark.parametrize(
    "extra",
    [
        ["--apply"],
        ["--tenant-id", "0"],
        ["--user-id", "-1"],
        ["--resource-key", "knowledge_space:*"],
        ["--resource-key", "knowledge_file:42"],
        ["--resource-key", "channel:a#member"],
        ["--resource-key", "knowledge_space:042"],
    ],
)
def test_arguments_reject_unbounded_or_unconfirmed_cleanup(extra):
    with pytest.raises(SystemExit):
        args(*extra)


def test_selection_excludes_other_users_and_resources():
    audit = SimpleNamespace(
        orphan_tuples=(
            ("user:1", "visible", "knowledge_space:42"),
            ("user:11", "visible", "knowledge_space:42"),
            ("user:11", "visible", "channel:42"),
        )
    )
    selected = cli.select_exact_orphan(args(), audit)
    assert selected.tuples == (("user:11", "visible", "knowledge_space:42"),)


async def seed_history(
    factory,
    *,
    tenant=7,
    source_state="INACTIVE",
    protected=False,
    projection_version=1,
    projection_state="RETIRED",
    membership=False,
):
    metadata = sa.MetaData()
    SQLModel.metadata.tables["space_channel_member"].to_metadata(metadata)
    async with factory() as session:
        connection = await session.connection()
        await connection.run_sync(metadata.create_all)
        await session.commit()
        source = GrantSourceService().canonicalize_source(
            source_id=101,
            subject_type="user",
            subject_id="11",
            source_type="SPACE_MEMBERSHIP",
            source_ref="42:user:11",
            protected=protected,
        )
        grant = PermissionGrant(
            tenant_id=tenant,
            resource_type="knowledge_space",
            resource_id="42",
            model_key="viewer",
            state="INACTIVE",
            projection_state="CURRENT",
        )
        session.add(grant)
        await session.flush()
        session.add(
            PermissionGrantAssignee(
                id=101,
                tenant_id=tenant,
                grant_id=grant.id,
                state=source_state,
                version=3,
                **{k: v for k, v in asdict(source).items() if k not in ("source_id", "active", "version")},
            )
        )
        if membership:
            session.add(SpaceChannelMember(business_id="42", business_type="space", user_id=11, user_role="member"))
        await session.commit()
    return PermissionVisibleSourceProjection(
        id=202,
        tenant_id=tenant,
        resource_type="knowledge_space",
        resource_id="42",
        visibility_class="ordinary",
        projected_subject="user:11",
        source_kind="GRANT_ASSIGNEE",
        source_owner_key="grant_assignee:101",
        source_locator=source.source_locator,
        source_fingerprint=source.source_fingerprint,
        contribution_fingerprint="c" * 64,
        model_key="viewer",
        source_version=projection_version,
        tuple_fingerprint="t" * 64,
        state=projection_state,
    )


async def test_sql_evidence_matches_bug_without_changing_history(session_factory, monkeypatch):
    monkeypatch.setattr(cli, "get_async_db_session", session_factory)
    row = await seed_history(session_factory)
    evidence = await cli.load_evidence(args(), (row,))
    assert evidence == ({"assignee_id": 101, "assignee_version": 3, "projection_id": 202, "projection_version": 1},)
    async with session_factory() as session:
        source = await session.get(PermissionGrantAssignee, 101)
        assert source.state == "INACTIVE" and source.version == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"membership": True},
        {"source_state": "ACTIVE"},
        {"source_state": "PENDING"},
        {"protected": True},
        {"tenant": 8},
        {"projection_version": 3},
        {"projection_state": "ACTIVE"},
    ],
)
async def test_sql_evidence_refuses_unrelated_or_current_authorization(session_factory, monkeypatch, changes):
    monkeypatch.setattr(cli, "get_async_db_session", session_factory)
    row = await seed_history(session_factory, **changes)
    with pytest.raises(cli.reconcile.VisibleReconcileBlockedError):
        await cli.load_evidence(args(), (row,))


class Client:
    def __init__(self, **kwargs):
        self.present = {("user:11", "visible", "knowledge_space:42"), ("user:9", "visible", "knowledge_space:42")}

    async def read_tuples(self, **kwargs):
        assert kwargs["consistency"] == "HIGHER_CONSISTENCY"
        return [dict(zip(("user", "relation", "object"), row, strict=True)) for row in self.present]

    async def close(self):
        pass


@pytest.fixture
def environment(monkeypatch):
    r = cli.reconcile
    for name in ("initialize_app_context", "close_app_context", "_assert_maintenance_window"):
        monkeypatch.setattr(r, name, AsyncMock())
    current = r.CurrentRelease(
        catalog_id=1,
        catalog_key="v1",
        store_id="store",
        model_id="model",
        model_release_id=1,
        model_checksum="c" * 64,
        write_fenced=False,
    )
    monkeypatch.setattr(r, "_load_current_release", AsyncMock(return_value=current))
    monkeypatch.setattr(r, "discover_openfga_runtime", AsyncMock(return_value=SimpleNamespace(model_checksum="c" * 64)))
    monkeypatch.setattr(r, "_load_cleanup_scope", AsyncMock(return_value=SimpleNamespace(tenant_id=7, version=5)))
    monkeypatch.setattr(r, "_load_canonical_grants", AsyncMock(return_value=((), 0)))
    monkeypatch.setattr(r, "_load_persisted_sources", AsyncMock(return_value=()))
    monkeypatch.setattr(
        cli, "load_evidence", AsyncMock(return_value=({"assignee_version": 3, "projection_version": 1},))
    )
    client = Client()
    monkeypatch.setattr(r, "FGAClient", lambda **kwargs: client)
    cleanup = AsyncMock()

    async def delete(client, **kwargs):
        client.present.difference_update(kwargs["selection"].tuples)
        return (123,)

    cleanup.side_effect = delete
    monkeypatch.setattr(r, "_cleanup_orphan_tuples", cleanup)
    return SimpleNamespace(
        settings=SimpleNamespace(openfga=SimpleNamespace(api_url="http://fga", timeout=5)),
        cleanup=cleanup,
        client=client,
    )


def plan_from(capsys):
    return next(
        row
        for row in (json.loads(line) for line in capsys.readouterr().out.splitlines())
        if row["event"] == "membership_orphan_plan"
    )


async def test_preview_writes_nothing_and_apply_deletes_only_reviewed_tuple(environment, capsys):
    assert await cli.execute(args(), live_settings=environment.settings) == 0
    plan = plan_from(capsys)
    environment.cleanup.assert_not_awaited()
    apply = args(
        "--apply", "--confirm-store-id", "store", "--confirm-plan-checksum", plan["plan_checksum"], "--operator-id", "9"
    )
    assert await cli.execute(apply, live_settings=environment.settings) == 0
    assert environment.client.present == {("user:9", "visible", "knowledge_space:42")}
    assert environment.cleanup.await_count == 1
    # The old confirmation is harmless after a successful run; no second mutation.
    assert await cli.execute(apply, live_settings=environment.settings) == 0
    assert environment.cleanup.await_count == 1


@pytest.mark.parametrize("reason", ["store", "checksum", "tenant", "heartbeat", "supported", "version"])
async def test_apply_blockers_never_delete(environment, capsys, monkeypatch, reason):
    await cli.execute(args(), live_settings=environment.settings)
    plan = plan_from(capsys)
    apply = args(
        "--apply", "--confirm-store-id", "store", "--confirm-plan-checksum", plan["plan_checksum"], "--operator-id", "9"
    )
    if reason == "store":
        apply.confirm_store_id = "wrong-store"
    elif reason == "checksum":
        apply.confirm_plan_checksum = "wrong-checksum"
    elif reason == "tenant":
        monkeypatch.setattr(cli.reconcile, "_load_cleanup_scope", AsyncMock(return_value=SimpleNamespace(tenant_id=8)))
    elif reason == "version":
        monkeypatch.setattr(
            cli.reconcile, "_load_cleanup_scope", AsyncMock(return_value=SimpleNamespace(tenant_id=7, version=6))
        )
    elif reason == "heartbeat":
        monkeypatch.setattr(
            cli.reconcile,
            "_assert_maintenance_window",
            AsyncMock(side_effect=cli.reconcile.VisibleReconcileBlockedError("active heartbeat")),
        )
    else:
        active = SimpleNamespace(
            state="ACTIVE", projected_subject="user:11", resource_type="knowledge_space", resource_id="42"
        )
        monkeypatch.setattr(cli.reconcile, "_load_persisted_sources", AsyncMock(return_value=(active,)))
    with pytest.raises(cli.reconcile.VisibleReconcileBlockedError):
        await cli.execute(apply, live_settings=environment.settings)
    environment.cleanup.assert_not_awaited()


async def test_failed_postcheck_is_not_reported_as_success(environment, capsys):
    await cli.execute(args(), live_settings=environment.settings)
    plan = plan_from(capsys)
    environment.cleanup.side_effect = None
    with pytest.raises(cli.reconcile.VisibleReconcileBlockedError, match="Post-cleanup"):
        await cli.execute(
            args(
                "--apply",
                "--confirm-store-id",
                "store",
                "--confirm-plan-checksum",
                plan["plan_checksum"],
                "--operator-id",
                "9",
            ),
            live_settings=environment.settings,
        )


async def test_exact_cleanup_records_durable_sql_ledger_and_preserves_other_subjects(session_factory, monkeypatch):
    r = cli.reconcile
    monkeypatch.setattr(r, "get_async_db_session", session_factory)
    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)
    monkeypatch.setattr(control_state.SqlPermissionControlState, "_assert_catalog_writable", AsyncMock())
    orphan = ("user:11", "visible", "knowledge_space:42")
    protected = ("user:9", "visible", "knowledge_space:42")
    other = ("user:12", "visible", "knowledge_space:42")
    fga = FakeFGAProjection({orphan, protected, other})
    runtime = SimpleNamespace(
        repository=ProjectionRepository(session_factory),
        marker=FakeRecentMarker(),
        scope_guard=SqlProjectionScopeGuard(),
        fga=fga,
        finalizer=SqlProjectionFinalizer(),
    )
    monkeypatch.setattr(r, "build_sql_projection_runtime", AsyncMock(return_value=runtime))
    async with session_factory() as session:
        session.add(
            ResourcePermissionMode(
                tenant_id=7,
                resource_type="knowledge_space",
                resource_id="42",
                mode="CUSTOM",
                version=5,
                projection_state="CURRENT",
            )
        )
        await session.commit()
    current = r.CurrentRelease(
        catalog_id=1,
        catalog_key="v1",
        store_id="store",
        model_id="model",
        model_release_id=1,
        model_checksum="c" * 64,
        write_fenced=False,
    )
    selection = r.OrphanCleanupSelection(
        object_filters=("knowledge_space:42",), tuple_count=1, tuple_checksum=r._checksum((orphan,)), tuples=(orphan,)
    )
    ids = await r._cleanup_orphan_tuples(fga, current=current, selection=selection, operator_id=9)
    assert len(ids) == 1 and fga.present == {protected, other}
    async with session_factory() as session:
        operation = await session.get(PermissionProjectionOperation, ids[0])
        assert operation.status == "FINALIZED" and operation.operation_type == "VISIBLE_ORPHAN_CLEANUP"
        rows = (await session.exec(select(PermissionProjectionTuple))).all()
        assert len(rows) == 1
        assert (rows[0].fga_user, rows[0].relation, rows[0].fga_object, rows[0].action) == (*orphan, "DELETE")
        scope = (await session.exec(select(ResourcePermissionMode))).one()
        assert scope.version == 6 and scope.projection_state == "CURRENT"


async def test_partial_initialization_failure_still_closes_context(environment, monkeypatch):
    monkeypatch.setattr(cli.reconcile, "initialize_app_context", AsyncMock(side_effect=RuntimeError("init failed")))
    with pytest.raises(RuntimeError, match="init failed"):
        await cli.execute(args(), live_settings=environment.settings)
    cli.reconcile.close_app_context.assert_awaited_once()
    environment.cleanup.assert_not_awaited()
