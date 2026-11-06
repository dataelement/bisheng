"""T847: native, bounded Assistant metadata with the original F048 identity."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.api.services.f048_application_permission import F048ApplicationPermissionAdapter
from bisheng.assistant.application.reference_source_owner import AssistantReferenceSourceOwner
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.core.database import tenant_filter
from bisheng.database.models.assistant import Assistant
from bisheng.permission.application import access, control_state
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.models import PermissionProjectionOperation, ResourcePermissionMode
from bisheng.permission.domain.services.permission_action_service import F048PermissionService
from bisheng.resource_reference.application.contracts import SourceKey, SourceType
from bisheng.resource_reference.application.source_disclosure import SourceDisclosure, SourceDisclosureRuntime
from test.knowledge_unification import test_as_source_owner as original

source_tenant = original.source_tenant
source_db = original.source_db


def key(ident="owned", tenant=101, version="current", kind=SourceType.ASSISTANT):
    return SourceKey(tenant, kind, ident, version)


@pytest.fixture
async def disclosure(source_db, monkeypatch):
    engine, owner, user, _ = source_db
    names = {ResourcePermissionMode.__tablename__, PermissionProjectionOperation.__tablename__}
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync: PermissionProjectionOperation.__table__.create(sync, checkfirst=True))
        await conn.run_sync(lambda sync: ResourcePermissionMode.__table__.create(sync, checkfirst=True))
        await conn.execute(
            sa.insert(ResourcePermissionMode),
            [
                {
                    "id": i,
                    "tenant_id": tid,
                    "resource_type": "assistant",
                    "resource_id": ident,
                    "mode": "CUSTOM",
                    "version": 3,
                    "projection_state": "CURRENT",
                }
                for i, (ident, tid) in enumerate((("owned", 101), ("root", 1), ("foreign", 202)), 1)
            ],
        )
    queries, allowed, checks = [], set(), []

    @sa.event.listens_for(engine.sync_engine, "before_cursor_execute")
    def observed(_conn, _cursor, sql, params, _ctx, _many):
        queries.append((sql, params))

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine) as session:
            yield session

    monkeypatch.setattr(control_state, "get_async_db_session", sessions)

    async def batch(values, **_kwargs):
        checks.append(tuple(values))
        return [(row["user"], row["relation"], row["object"]) in allowed for row in values]

    fga = SimpleNamespace(batch_check=AsyncMock(side_effect=batch))
    decision = F048PermissionService(
        catalog=SimpleNamespace(ensure_runtime_ready=AsyncMock(), is_action_effective=AsyncMock(return_value=True)),
        scope_fence=SimpleNamespace(ensure_readable=AsyncMock(return_value=False)),
        marker=SimpleNamespace(consistency_for=AsyncMock(return_value=None)),
        fga=fga,
        list_policy=SimpleNamespace(),
    )
    runtime = F048PermissionRuntime(
        client=None,
        state=control_state.SqlPermissionControlState(),
        marker=None,
        decision=decision,
        projection=None,
        sources=None,
        owner=None,
        grants=None,
        modes=None,
        explain=None,
    )
    adapter = F048ApplicationPermissionAdapter(loader=None, permission=runtime)
    monkeypatch.setattr(access, "_ensure_f048_runtime", AsyncMock())
    monkeypatch.setattr(access, "_runtime", runtime)
    monkeypatch.setattr(access, "_resource_adapters", {"assistant": adapter})
    actor = PermissionActor(user_id=user.user_id, tenant_id=101)
    token = set_current_permission_actor(actor)
    try:
        yield SimpleNamespace(
            engine=engine,
            owner=owner,
            user=user,
            actor=actor,
            queries=queries,
            checks=checks,
            allowed=allowed,
            fga=fga,
            runtime=runtime,
        )
    finally:
        reset_current_permission_actor(token)


async def disclose(case, keys):
    async with AsyncSession(case.engine) as session, session.begin():
        result = await case.owner.adisclose_sources(session, identity=case.user, source_keys=keys)
        assert not session.new and not session.dirty and not session.identity_map
        return result


async def test_empty_and_foreign_batches_do_not_query_business_or_permission(disclosure):
    case = disclosure
    case.queries.clear()
    assert await disclose(case, ()) == ()
    assert await disclose(case, (key("root", 1), key("foreign", 202), key("root", 1))) == (None, None, None)
    assert not case.queries and not case.checks


async def test_current_metadata_and_duplicate_positions_use_original_visible_not_configuration(disclosure):
    case = disclosure
    case.allowed.add((case.actor.fga_subject, "visible", "assistant:owned"))
    async with case.engine.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE assistant SET guide_question='not-json', system_prompt='never disclose prompt' WHERE id='owned'"
            )
        )
    case.queries.clear()
    result = await disclose(case, (key(), key("root", 1), key()))
    assert result == (SourceDisclosure(key(), "owned", None, "/assistant/owned"), None, result[0])
    assert sum(len(batch) for batch in case.checks) == 1
    sql = " ".join(statement for statement, _ in case.queries).lower()
    assert "system_prompt" not in sql and "guide_question" not in sql and "assistantlink" not in sql
    assert "for update" not in sql
    assert "never disclose" not in repr(result)


async def test_visible_denial_is_hidden_but_current_missing_deleted_or_bad_status_is_not(disclosure):
    case = disclosure
    assert await disclose(case, (key(),)) == (None,)
    with pytest.raises(ReferenceCoverageNotReadyError):
        await disclose(case, (key("missing"),))
    for values in ({"is_delete": 1}, {"status": 999}):
        async with case.engine.begin() as conn:
            await conn.execute(sa.update(Assistant).where(Assistant.id == "owned").values(**values))
        with pytest.raises(ReferenceCoverageNotReadyError):
            await disclose(case, (key(),))


@pytest.mark.parametrize(
    "keys",
    [
        [key()],
        (key(version="saved-v1"),),
        (key(kind=SourceType.CHANNEL_SYNC),),
        tuple(key() for _ in range(201)),
        (object(),),
    ],
)
async def test_owner_direct_invalid_batch_or_version_rejects_before_io(disclosure, keys):
    case = disclosure
    case.queries.clear()
    with pytest.raises(ReferenceCoverageNotReadyError):
        await disclose(case, keys)
    assert not case.queries and not case.checks


async def test_missing_permission_metadata_and_fga_io_fail_closed(disclosure):
    case = disclosure
    async with case.engine.begin() as conn:
        await conn.execute(sa.delete(ResourcePermissionMode).where(ResourcePermissionMode.resource_id == "owned"))
    with pytest.raises(ReferenceCoverageNotReadyError):
        await disclose(case, (key(),))
    async with case.engine.begin() as conn:
        await conn.execute(
            sa.insert(ResourcePermissionMode).values(
                id=9,
                tenant_id=101,
                resource_type="assistant",
                resource_id="owned",
                mode="CUSTOM",
                version=1,
                projection_state="CURRENT",
            )
        )
    case.fga.batch_check.side_effect = ConnectionError("transport unavailable")
    with pytest.raises(ReferenceCoverageNotReadyError):
        await disclose(case, (key(),))


async def test_401_unique_sources_and_duplicate_slots_use_only_bounded_light_batches(disclosure):
    case = disclosure
    async with case.engine.begin() as conn:
        await conn.execute(
            sa.insert(Assistant),
            [
                {
                    "id": f"a-{i}",
                    "tenant_id": 101,
                    "user_id": 9,
                    "name": f"Assistant {i}",
                    "model_name": "private-model",
                    "system_prompt": "private-prompt",
                }
                for i in range(401)
            ],
        )
        await conn.execute(
            sa.insert(ResourcePermissionMode),
            [
                {
                    "id": 100 + i,
                    "tenant_id": 101,
                    "resource_type": "assistant",
                    "resource_id": f"a-{i}",
                    "mode": "CUSTOM",
                    "version": 3,
                    "projection_state": "CURRENT",
                }
                for i in range(401)
            ],
        )
    case.allowed.update((case.actor.fga_subject, "visible", f"assistant:a-{i}") for i in range(401))
    case.queries.clear()
    requested = tuple(key(f"a-{i}") for i in range(401))
    runtime = SourceDisclosureRuntime({SourceType.ASSISTANT: case.owner})
    found = []
    async with AsyncSession(case.engine) as session, session.begin():
        for start in range(0, len(requested), 200):
            batch = requested[start : start + 200]
            found.extend(await runtime.adisclose_sources(session, identity=case.user, source_keys=batch))
        assert tuple(item.source for item in found) == requested
        duplicates = await runtime.adisclose_sources(session, identity=case.user, source_keys=(requested[0],) * 200)
        assert len(duplicates) == 200 and all(item == found[0] for item in duplicates)
        assert not session.new and not session.dirty
    assert sum("FROM assistant " in sql for sql, _ in case.queries) <= 4
    assert sum("FROM resource_permission_mode" in sql for sql, _ in case.queries) <= 4
    assert sum(len(batch) for batch in case.checks) == 402
    assert all(len(batch) <= 100 for batch in case.checks)
    assert all("private-prompt" not in sql and "system_prompt" not in sql for sql, _ in case.queries)


async def test_same_owner_source_permission_is_rechecked_and_service_account_stays_original(disclosure):
    case = disclosure
    actor = PermissionActor(subject_type="service_account", subject_id=44, tenant_id=101)
    token = set_current_permission_actor(actor)
    try:
        case.allowed.add((actor.fga_subject, "visible", "assistant:owned"))
        assert (await disclose(case, (key(),)))[0].source == key()
        case.allowed.clear()
        assert await disclose(case, (key(),)) == (None,)
        assert all(row["user"] == actor.fga_subject for batch in case.checks for row in batch)
    finally:
        reset_current_permission_actor(token)


async def test_owner_read_preserves_pending_rows_and_does_not_commit(disclosure):
    case = disclosure
    case.allowed.add((case.actor.fga_subject, "visible", "assistant:owned"))
    async with AsyncSession(case.engine, autoflush=True) as session, session.begin():
        pending = Assistant(id="caller-pending", tenant_id=101, user_id=9)
        session.add(pending)
        result = await case.owner.adisclose_sources(session, identity=case.user, source_keys=(key(),))
        assert result[0].source == key() and pending in session.new
        assert not session.identity_map
        await session.rollback()
    async with case.engine.connect() as conn:
        assert (
            await conn.execute(
                sa.select(sa.func.count()).select_from(Assistant).where(Assistant.id == "caller-pending")
            )
        ).scalar_one() == 0
