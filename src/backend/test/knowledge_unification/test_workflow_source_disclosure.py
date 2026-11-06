"""T845: actual workflow metadata SQL and loaded F048 adapter, external decisions isolated."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.api.services.f048_application_permission import F048ApplicationPermissionAdapter
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.common.errcode.public_endpoints import PublicGuestAccessDisabledError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.permission.application import control_state
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.domain.models import ResourcePermissionMode
from bisheng.public_endpoints.domain.context import (
    PublicApiPrincipal,
    reset_current_public_api_principal,
    set_current_public_api_principal,
)
from bisheng.resource_reference.application.contracts import SourceKey, SourceType
from bisheng.workflow.application import reference_source_owner as module
from test.knowledge_unification import test_wf_transaction as fixtures

store = fixtures.store
tenant = fixtures.tenant


def source(version="1", ident="wf", tenant=101):
    return SourceKey(tenant, SourceType.WORKFLOW_VERSION, ident, version)


@pytest.fixture
async def auth(store, monkeypatch):
    engine, sync = store
    metadata = sa.MetaData()
    sa.Table(
        ResourcePermissionMode.__tablename__,
        metadata,
        *[
            sa.Column(
                column.name,
                column.type.copy(),
                primary_key=column.primary_key,
                nullable=column.nullable,
                server_default=sa.text("CURRENT_TIMESTAMP")
                if column.name in {"create_time", "update_time"}
                else column.server_default,
            )
            for column in ResourcePermissionMode.__table__.columns
        ],
    )
    metadata.create_all(sync)
    with sync.begin() as connection:
        connection.execute(
            ResourcePermissionMode.__table__.insert().values(
                id=1,
                tenant_id=101,
                resource_type="workflow",
                resource_id="wf",
                mode="CUSTOM",
                version=4,
                projection_state="CURRENT",
            )
        )

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(engine) as session:
            yield session

    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)
    actor = PermissionActor(user_id=11, tenant_id=101)
    actor_token = set_current_permission_actor(actor)
    decisions = SimpleNamespace(visible=True, edit=False, calls=[], error=None)

    async def batch(actor, targets, action):
        if decisions.error:
            raise decisions.error
        assert len(targets) <= 100
        decisions.calls.append((actor, targets, action))
        return tuple(getattr(decisions, action) for _ in targets)

    # Actual business adapter validates loaded rows; no DAO ID reload is allowed.
    loader = SimpleNamespace(load_permission_record=AsyncMock(side_effect=AssertionError("ID reload")))
    adapter = F048ApplicationPermissionAdapter(loader=loader, permission=SimpleNamespace(batch_check_actions=batch))
    runtime = SimpleNamespace(get_permission_snapshots=control_state.SqlPermissionControlState().permission_snapshots)
    monkeypatch.setattr(module, "get_f048_runtime", AsyncMock(return_value=runtime), raising=False)
    monkeypatch.setattr(module, "get_f048_resource_adapter", AsyncMock(return_value=adapter), raising=False)
    queries = []

    @sa.event.listens_for(engine.sync_engine, "before_cursor_execute")
    def seen(_connection, _cursor, statement, parameters, _context, _many):
        queries.append((statement, parameters))

    try:
        yield SimpleNamespace(
            engine=engine,
            sync=sync,
            decisions=decisions,
            queries=queries,
            actor=actor,
            identity=UserPayload(user_id=11, tenant_id=101, user_role=[]),
            loader=loader,
        )
    finally:
        reset_current_permission_actor(actor_token)


async def read(auth, keys, *, owner=None):
    async with AsyncSession(auth.engine) as session, session.begin():
        result = await (owner or module.WorkflowReferenceSourceOwner()).adisclose_sources(
            session, identity=auth.identity, source_keys=keys
        )
        assert not session.identity_map and not session.new and not session.dirty
        return result


async def test_current_visible_and_history_edit_are_distinct_with_duplicates(auth):
    keys = (source(), source("2"), source())
    result = await read(auth, keys)
    assert [item.source if item else None for item in result] == [keys[0], None, keys[2]]
    assert result[0].name == "workflow" and result[0].version_label == "v0"
    assert result[0].entry == "/flow/wf/"
    auth.decisions.edit = True
    assert (await read(auth, (source("2"),)))[0].version_label == "draft"
    assert all(actor is auth.actor for actor, _, _ in auth.decisions.calls)
    assert {action for _, _, action in auth.decisions.calls} == {"visible", "edit"}
    auth.loader.load_permission_record.assert_not_awaited()


async def test_denied_is_none_but_sql_and_fga_failures_are_not_hidden(auth):
    auth.decisions.visible = False
    assert await read(auth, (source(),)) == (None,)
    error = OSError("authorization backend unavailable")
    auth.decisions.error = error
    with pytest.raises(ReferenceCoverageNotReadyError) as failure:
        await read(auth, (source(),))
    assert failure.value.__cause__ is error
    auth.decisions.error = None
    owner = module.WorkflowReferenceSourceOwner()
    owner.repository = SimpleNamespace(aload_disclosure=AsyncMock(side_effect=error))
    with pytest.raises(ReferenceCoverageNotReadyError):
        await read(auth, (source(),), owner=owner)


async def test_foreign_and_empty_batches_have_zero_business_sql_and_permission_calls(auth):
    auth.queries.clear()
    assert await read(auth, ()) == ()
    assert await read(auth, (source("999", "outside", 202),)) == (None,)
    assert not auth.queries and not auth.decisions.calls


@pytest.mark.parametrize(
    "change",
    [
        "missing_version",
        "missing_root",
        "foreign_root",
        "foreign_version",
        "wrong_parent",
        "wrong_type",
        "deleted_root",
        "deleted_version",
        "invalid_status",
    ],
)
async def test_current_tenant_incomplete_metadata_is_fail_closed(auth, change):
    with auth.sync.begin() as connection:
        if change == "missing_version":
            connection.execute(sa.delete(FlowVersion).where(FlowVersion.id == 1))
        elif change == "missing_root":
            connection.execute(sa.delete(Flow).where(Flow.id == "wf"))
        elif change == "foreign_root":
            connection.execute(sa.update(Flow).where(Flow.id == "wf").values(tenant_id=202))
        elif change == "foreign_version":
            connection.execute(sa.update(FlowVersion).where(FlowVersion.id == 1).values(tenant_id=202))
        elif change == "wrong_parent":
            connection.execute(sa.update(FlowVersion).where(FlowVersion.id == 1).values(flow_id="other"))
        elif change == "wrong_type":
            connection.execute(sa.update(Flow).where(Flow.id == "wf").values(flow_type=5))
        elif change == "deleted_root":
            connection.execute(sa.update(Flow).where(Flow.id == "wf").values(is_delete=1))
        elif change == "deleted_version":
            connection.execute(sa.update(FlowVersion).where(FlowVersion.id == 1).values(is_delete=1))
        else:
            connection.execute(sa.update(Flow).where(Flow.id == "wf").values(status=999))
    with pytest.raises(ReferenceCoverageNotReadyError):
        await read(auth, (source(),))
    assert not auth.decisions.calls


async def test_version_flow_type_does_not_add_a_new_gate_and_offline_remains_visible(auth):
    auth.decisions.edit = True
    with auth.sync.begin() as connection:
        connection.execute(sa.update(FlowVersion).where(FlowVersion.id == 2).values(flow_type=5))
        connection.execute(sa.update(Flow).where(Flow.id == "wf").values(status=1))
    assert (await read(auth, (source("2"),)))[0].version_label == "draft"


async def test_public_principal_cannot_disclose_noncurrent_version(auth, monkeypatch):
    from bisheng.public_endpoints.domain.services import guest_policy

    guest = AsyncMock()
    monkeypatch.setattr(guest_policy, "ensure_guest_link_enabled", guest)
    token = set_current_public_api_principal(
        PublicApiPrincipal(
            tenant_id=101, operator_user_id=11, operator_name="guest", resource_type="workflow", resource_id="wf"
        )
    )
    try:
        actual = await read(auth, (source(), source("2")))
        assert actual[0].name == "workflow" and actual[1] is None
        guest.assert_awaited_once_with("workflow", "wf")
    finally:
        reset_current_public_api_principal(token)


@pytest.mark.parametrize("failure", [PublicGuestAccessDisabledError(), OSError("guest policy unavailable")])
async def test_public_guest_denial_is_distinct_from_policy_io_failure(auth, monkeypatch, failure):
    from bisheng.public_endpoints.domain.services import guest_policy

    monkeypatch.setattr(guest_policy, "ensure_guest_link_enabled", AsyncMock(side_effect=failure))
    token = set_current_public_api_principal(
        PublicApiPrincipal(
            tenant_id=101, operator_user_id=11, operator_name="guest", resource_type="workflow", resource_id="wf"
        )
    )
    try:
        if isinstance(failure, PublicGuestAccessDisabledError):
            assert await read(auth, (source(),)) == (None,)
        else:
            with pytest.raises(ReferenceCoverageNotReadyError) as error:
                await read(auth, (source(),))
            assert error.value.__cause__ is failure
    finally:
        reset_current_public_api_principal(token)


async def test_original_full_scope_super_path_does_not_grant_foreign_metadata(auth):
    actor = PermissionActor(user_id=11, tenant_id=1, super_admin=True)
    token = set_current_permission_actor(actor)
    auth.identity = UserPayload(user_id=11, tenant_id=1, user_role=[])
    try:
        result = await read(auth, (source(), source("2"), source("999", "outside", 202)))
        assert [item.version_label if item else None for item in result] == ["v0", "draft", None]
        assert not auth.decisions.calls
    finally:
        reset_current_permission_actor(token)


async def test_missing_permission_snapshot_is_not_a_normal_hidden_source(auth):
    with auth.sync.begin() as connection:
        connection.execute(sa.delete(ResourcePermissionMode))
    with pytest.raises(ReferenceCoverageNotReadyError):
        await read(auth, (source(),))
    assert not auth.decisions.calls


async def test_pending_changes_remain_unflushed_and_no_graph_or_write_is_selected(auth):
    auth.queries.clear()
    async with AsyncSession(auth.engine) as session, session.begin():
        pending = Flow(id="pending", name="pending", user_id=11, tenant_id=101)
        session.add(pending)
        actual = await module.WorkflowReferenceSourceOwner().adisclose_sources(
            session, identity=auth.identity, source_keys=(source(),)
        )
        assert actual[0].name == "workflow" and pending in session.new
        assert not session.identity_map
        await session.rollback()
    assert all(not sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")) for sql, _ in auth.queries)
    assert all("flow.data" not in sql.lower() and "flowversion.data" not in sql.lower() for sql, _ in auth.queries)
    assert all("FOR UPDATE" not in sql.upper() for sql, _ in auth.queries)


@pytest.mark.parametrize("keys", [[], (source("current"),), (source("01"),), tuple(source() for _ in range(201))])
async def test_invalid_batch_or_version_is_rejected_before_business_io(auth, keys):
    auth.queries.clear()
    with pytest.raises(ReferenceCoverageNotReadyError):
        await read(auth, keys)
    assert not auth.queries and not auth.decisions.calls


async def test_401_native_sources_use_three_safe_metadata_and_permission_snapshot_queries(auth):
    auth.decisions.edit = True
    with auth.sync.begin() as connection:
        connection.execute(
            Flow.__table__.insert(),
            [
                {
                    "id": f"wf-{i}",
                    "name": f"name-{i}",
                    "tenant_id": 101,
                    "user_id": 11,
                    "flow_type": 10,
                    "status": 1,
                    "is_delete": 0,
                }
                for i in range(401)
            ],
        )
        connection.execute(
            FlowVersion.__table__.insert(),
            [
                {
                    "id": 1000 + i,
                    "flow_id": f"wf-{i}",
                    "name": f"version-{i}",
                    "tenant_id": 101,
                    "is_current": 0,
                    "is_delete": 0,
                }
                for i in range(401)
            ],
        )
        connection.execute(
            ResourcePermissionMode.__table__.insert(),
            [
                {
                    "id": 1000 + i,
                    "tenant_id": 101,
                    "resource_type": "workflow",
                    "resource_id": f"wf-{i}",
                    "mode": "CUSTOM",
                    "version": 1,
                    "projection_state": "CURRENT",
                }
                for i in range(401)
            ],
        )
    keys = tuple(source(str(1000 + i), f"wf-{i}") for i in range(401))
    auth.queries.clear()
    actual = []
    for offset in range(0, len(keys), 200):
        actual.extend(await read(auth, keys[offset : offset + 200]))
    assert tuple(item.source for item in actual) == keys
    selects = [sql for sql, _ in auth.queries if sql.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 6
    assert len(auth.decisions.calls) == 10
    assert all(len(targets) <= 100 for _, targets, _ in auth.decisions.calls)


async def test_ambient_bypass_is_not_source_disclosure_authority(auth):
    with bypass_tenant_filter(), pytest.raises(ReferenceCoverageNotReadyError):
        await read(auth, (source(),))
