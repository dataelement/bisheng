"""T851: native channel metadata, SQL permission fence and original F048 decisions."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.application import reference_source_owner as module
from bisheng.channel.domain.models.channel import Channel, ChannelVisibilityEnum
from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.channel.domain.services.f048_channel_permission import (
    ChannelPermissionRecord,
    F048ChannelPermissionAdapter,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id
from bisheng.core.database import tenant_filter
from bisheng.permission.application import business_authorization, control_state, sql_runtime
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.domain.models import ResourcePermissionMode
from bisheng.permission.domain.services.permission_action_service import F048PermissionService
from bisheng.resource_reference.application.contracts import SourceKey, SourceType


def source(ident="channel", tenant=101, version="current"):
    return SourceKey(tenant, SourceType.CHANNEL_SYNC, ident, version)


def channel(ident="channel", *, tenant=101, shared=False):
    return {
        "id": ident,
        "tenant_id": tenant,
        "name": "actual-channel",
        "user_id": 11,
        "visibility": ChannelVisibilityEnum.PRIVATE,
        "is_shared": shared,
        "is_pinned": False,
        "is_released": False,
        "source_list": ["private-provider"],
        "filter_rules": [{"private-rule": "never read"}],
    }


def mode(ident="channel", pk=1):
    return {
        "id": pk,
        "tenant_id": 101,
        "resource_type": "channel",
        "resource_id": ident,
        "mode": "CUSTOM",
        "version": 4,
        "projection_state": "CURRENT",
    }


class Marker:
    async def consistency_for(self, **kwargs):
        return None

    async def consistency_for_batch(self, targets):
        return None


@pytest.fixture
async def native(tmp_path, monkeypatch):
    names = tenant_filter._tenant_aware_tables | {Channel.__tablename__, ResourcePermissionMode.__tablename__}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    tenant_filter.register_tenant_filter_events()
    tenant_token = set_current_tenant_id(101)
    actor = PermissionActor(user_id=11, tenant_id=101)
    actor_token = set_current_permission_actor(actor)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'channel.db'}")
    metadata = sa.MetaData()
    for model in (Channel, ChannelKnowledgeSync, ResourcePermissionMode):
        sa.Table(
            model.__tablename__,
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
                for column in model.__table__.columns
            ],
        )
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(Channel.__table__.insert(), [channel(), channel("foreign", tenant=202)])
        await connection.execute(ResourcePermissionMode.__table__.insert(), [mode()])

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine) as session:
            yield session

    monkeypatch.setattr(control_state, "get_async_db_session", sessions)
    monkeypatch.setattr(sql_runtime, "get_async_db_session", sessions)
    decisions = SimpleNamespace(allowed=True, error=None, calls=[])

    async def batch(checks, *, consistency=None):
        if decisions.error:
            raise decisions.error
        decisions.calls.append((checks, consistency))
        assert len(checks) <= 100 and all(row["relation"] == "visible" for row in checks)
        return [decisions.allowed for _ in checks]

    decision = F048PermissionService(
        catalog=SimpleNamespace(ensure_runtime_ready=AsyncMock()),
        scope_fence=sql_runtime.SqlPermissionScopeFence(),
        marker=Marker(),
        fga=SimpleNamespace(batch_check=batch),
        list_policy=SimpleNamespace(),
    )
    runtime = SimpleNamespace(
        get_permission_snapshots=control_state.SqlPermissionControlState().permission_snapshots,
        batch_check_actions=decision.batch_check_actions,
    )
    monkeypatch.setattr(module, "get_f048_runtime", AsyncMock(return_value=runtime), raising=False)
    monkeypatch.setattr(business_authorization, "get_f048_runtime", AsyncMock(return_value=runtime))
    queries = []

    @sa.event.listens_for(engine.sync_engine, "before_cursor_execute")
    def seen(_connection, _cursor, statement, parameters, _context, _many):
        queries.append((statement, parameters))

    try:
        yield SimpleNamespace(
            engine=engine,
            sessions=sessions,
            queries=queries,
            decisions=decisions,
            actor=actor,
            identity=UserPayload(user_id=11, tenant_id=101, user_role=[]),
            decision=decision,
        )
    finally:
        reset_current_permission_actor(actor_token)
        current_tenant_id.reset(tenant_token)
        await engine.dispose()


async def read(native, keys, *, owner=None):
    async with native.sessions() as session, session.begin():
        result = await (owner or module.ChannelReferenceSourceOwner()).adisclose_sources(
            session, identity=native.identity, source_keys=keys
        )
        assert not session.identity_map and not session.new and not session.dirty
        return result


async def test_real_name_and_current_source_preserve_duplicates_without_membership_gate(native):
    keys = (source(), source(), source("foreign", 202))
    result = await read(native, keys)
    assert tuple(item.source if item else None for item in result) == (keys[0], keys[1], None)
    assert result[0].name == "actual-channel" and result[0].version_label is None
    assert result[0].entry == "/workspace/channel/channel"
    assert result[0] == result[1]
    assert len(native.decisions.calls) == 1
    assert native.decisions.calls[0][0][0] == {
        "user": native.actor.fga_subject,
        "relation": "visible",
        "object": "channel:channel",
    }
    assert all("space_channel_member" not in sql.lower() for sql, _ in native.queries)


async def test_denied_visibility_is_none_and_fga_or_sql_failure_is_not(native):
    native.decisions.allowed = False
    assert await read(native, (source(),)) == (None,)
    error = OSError("external authorization unavailable")
    native.decisions.error = error
    with pytest.raises(ReferenceCoverageNotReadyError) as failure:
        await read(native, (source(),))
    assert failure.value.__cause__.__cause__ is error
    owner = module.ChannelReferenceSourceOwner()
    owner.repository = SimpleNamespace(aload_disclosure=AsyncMock(side_effect=error))
    with pytest.raises(ReferenceCoverageNotReadyError) as failure:
        await read(native, (source(),), owner=owner)
    assert failure.value.__cause__ is error


async def test_empty_and_foreign_source_have_zero_business_queries_or_fga(native):
    native.queries.clear()
    assert await read(native, ()) == ()
    assert await read(native, (source("foreign", 202),)) == (None,)
    assert not native.queries and not native.decisions.calls


@pytest.mark.parametrize("change", ["missing", "wrong_tenant", "bad_creator"])
async def test_current_tenant_broken_metadata_is_not_hidden(native, change):
    async with native.engine.begin() as connection:
        if change == "missing":
            await connection.execute(sa.delete(Channel).where(Channel.id == "channel"))
        else:
            await connection.execute(
                sa.update(Channel)
                .where(Channel.id == "channel")
                .values({"tenant_id": 202} if change == "wrong_tenant" else {"user_id": 0})
            )
    with pytest.raises(ReferenceCoverageNotReadyError):
        await read(native, (source(),))
    assert not native.decisions.calls


@pytest.mark.parametrize("change", ["missing", "parent", "mode", "version"])
async def test_bad_permission_metadata_fails_before_batch_fence_can_hide_it(native, change):
    async with native.engine.begin() as connection:
        if change == "missing":
            await connection.execute(sa.delete(ResourcePermissionMode))
        else:
            changes = {
                "parent": {"parent_type": "channel", "parent_id": "missing"},
                "mode": {"mode": "INHERIT"},
                "version": {"version": 0},
            }[change]
            await connection.execute(sa.update(ResourcePermissionMode).values(**changes))
    with pytest.raises(ReferenceCoverageNotReadyError):
        await read(native, (source(),))
    assert not native.decisions.calls


async def test_real_sql_fence_distinguishes_parent_corruption_from_ordinary_denial(native):
    async with native.engine.begin() as connection:
        await connection.execute(sa.update(ResourcePermissionMode).values(parent_type="channel", parent_id="missing"))
    record = ChannelPermissionRecord(101, "channel", "ACTIVE", 11, 4, "same-source")
    target = F048ChannelPermissionAdapter._target(record, "channel", native.actor, action="visible")
    with pytest.raises(PermissionPublishNotReadyError):
        await sql_runtime.SqlPermissionScopeFence().ensure_readable(target)
    assert await native.decision.batch_check_visible(native.actor, (target,)) == (False,)
    with pytest.raises(ReferenceCoverageNotReadyError):
        await read(native, (source(),))


@pytest.mark.parametrize("shared,sub_name", [(False, None), (True, "saved-sub")])
async def test_stopped_sync_and_shared_readonly_do_not_hide_source(native, shared, sub_name):
    async with native.engine.begin() as connection:
        await connection.execute(sa.update(Channel).where(Channel.id == "channel").values(is_shared=shared))
        await connection.execute(
            ChannelKnowledgeSync.__table__.insert().values(
                id="sync",
                channel_id="channel",
                knowledge_space_id="10",
                folder_id=None,
                sub_channel_name=sub_name,
                is_enabled=False,
                user_id=11,
            )
        )
    native.queries.clear()
    assert (await read(native, (source(),)))[0].name == "actual-channel"
    assert all(
        "channel_knowledge_sync" not in sql.lower()
        and "filter_rules" not in sql.lower()
        and "source_list" not in sql.lower()
        for sql, _ in native.queries
    )


async def test_original_super_shortcut_is_current_tenant_only_and_narrowed_actor_is_not_promoted(native):
    actor_token = set_current_permission_actor(PermissionActor(user_id=11, tenant_id=1, super_admin=True))
    native.identity = UserPayload(user_id=11, tenant_id=1, user_role=[])
    try:
        result = await read(native, (source(), source("foreign", 202)))
        assert result[0].name == "actual-channel" and result[1] is None
        assert not native.decisions.calls
    finally:
        reset_current_permission_actor(actor_token)
    actor_token = set_current_permission_actor(
        PermissionActor(user_id=11, tenant_id=101, super_admin=True, data_scope="personal_only")
    )
    native.identity = UserPayload(user_id=11, tenant_id=101, user_role=[])
    try:
        assert await read(native, (source(),)) == (None,)
        assert not native.decisions.calls
    finally:
        reset_current_permission_actor(actor_token)


async def test_native_401_rows_use_bounded_light_queries_and_actual_sql_fence(native):
    async with native.engine.begin() as connection:
        await connection.execute(Channel.__table__.insert(), [channel(f"c-{i}") for i in range(401)])
        await connection.execute(
            ResourcePermissionMode.__table__.insert(), [mode(f"c-{i}", 1000 + i) for i in range(401)]
        )
    keys = tuple(source(f"c-{i}") for i in range(401))
    native.queries.clear()
    actual = []
    for offset in range(0, len(keys), 200):
        actual.extend(await read(native, keys[offset : offset + 200]))
    assert tuple(item.source for item in actual) == keys
    selects = [sql for sql, _ in native.queries if sql.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 11  # 3 metadata + 3 permission snapshots + 5 actual SQL fences.
    assert len(native.decisions.calls) == 5
    assert all(len(checks) <= 100 for checks, _ in native.decisions.calls)
    assert all("channel.filter_rules" not in sql and "channel.source_list" not in sql for sql in selects)


async def test_external_pending_orm_stays_pending_and_no_write_lock_or_commit(native):
    async with native.sessions() as session, session.begin():
        pending = Channel(**channel("pending"))
        session.add(pending)
        native.queries.clear()
        actual = await module.ChannelReferenceSourceOwner().adisclose_sources(
            session, identity=native.identity, source_keys=(source(),)
        )
        assert actual[0].name == "actual-channel" and pending in session.new and not session.identity_map
        assert all(
            not sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")) and "FOR UPDATE" not in sql.upper()
            for sql, _ in native.queries
        )
        await session.rollback()


@pytest.mark.parametrize("keys", [[], (source(version="v2"),), tuple(source() for _ in range(201))])
async def test_invalid_input_never_reaches_business_sql(native, keys):
    native.queries.clear()
    with pytest.raises(ReferenceCoverageNotReadyError):
        await read(native, keys)
    assert not native.queries and not native.decisions.calls


async def test_ambient_bypass_is_not_disclosure_authority(native):
    with bypass_tenant_filter(), pytest.raises(ReferenceCoverageNotReadyError):
        await read(native, (source(),))
