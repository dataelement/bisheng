"""Real SQL paging and bounded loaded-row F048 checks for unified lists."""

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.cursor import decode_cursor, encode_cursor
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import KnowledgeSpaceInvalidCursorError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import bypass_tenant_filter, management_tenant_scope, tenant_execution_scope
from bisheng.core.database import tenant_filter
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.knowledge_space_listing_repository import KnowledgeSpaceListingRepository
from bisheng.knowledge.domain.services.knowledge_permission_service import (
    F048KnowledgeContainerPermissionAdapter,
    KnowledgeContainerDaoPermissionLoader,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.application import business_authorization
from bisheng.permission.application.control_state import PermissionResourceSnapshot
from bisheng.permission.application.data_scope import DATA_SCOPE_PERSONAL
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.permission.domain.services.permission_action_service import F048PermissionService, PermissionActor


@pytest.fixture
def concrete_tenant(tenant_context):
    tenant_context(101)


@pytest.fixture
async def catalog(concrete_tenant, monkeypatch):
    register_tenant_filter_events()
    # Other native-SQL fixtures narrow discovery during the first global
    # registration; pin this fixture's real model even in a combined selection.
    monkeypatch.setattr(
        tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | {"knowledge", "knowledgefile"}
    )
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    metadata = sa.MetaData()
    table = Knowledge.__table__.to_metadata(metadata)
    KnowledgeFile.__table__.to_metadata(metadata)
    # Old installations may still contain NULL times; do not mutate shared ORM metadata.
    table.c.update_time.nullable = True
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    facts = SimpleNamespace(open_sessions=0, allowed=set(), checked=[], snapshots=[])

    @asynccontextmanager
    async def sessions():
        facts.open_sessions += 1
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                yield session
        finally:
            facts.open_sessions -= 1

    async def seed(rows, null_ids=()):
        async with sessions() as session:
            with bypass_tenant_filter():
                session.add_all(rows)
                await session.flush()
                if null_ids:
                    await session.exec(
                        sa.update(Knowledge)
                        .where(Knowledge.tenant_id == 101, Knowledge.id.in_(null_ids))
                        .values(update_time=None)
                    )
                await session.commit()

    async def snapshots(keys):
        assert facts.open_sessions == 0
        facts.snapshots.append(keys)
        return {key: PermissionResourceSnapshot(*key, 3, "ctx3", "CUSTOM", None, None, "READY") for key in keys}

    async def check(actor, targets, action):
        assert facts.open_sessions == 0 and action == "visible"
        facts.checked.append(tuple(int(target.resource_id) for target in targets))
        return tuple(int(target.resource_id) in facts.allowed for target in targets)

    runtime = SimpleNamespace(
        batch_check_actions=AsyncMock(side_effect=check),
        list_visible_objects=AsyncMock(side_effect=AssertionError("ordinary list must not enumerate all FGA IDs")),
    )
    monkeypatch.setattr(business_authorization, "get_f048_runtime", AsyncMock(return_value=runtime))
    adapter = F048KnowledgeContainerPermissionAdapter(
        loader=KnowledgeContainerDaoPermissionLoader(
            SimpleNamespace(get_permission_snapshots=AsyncMock(side_effect=snapshots))
        ),
        permission=SimpleNamespace(),
    )
    repository = KnowledgeSpaceListingRepository(session_factory=sessions)
    service = KnowledgeSpaceService(
        None,
        SimpleNamespace(user_id=7, tenant_id=101),
        f048_permission_adapter=adapter,
        space_listing_repository=repository,
    )
    service._permission_actor = AsyncMock(return_value=PermissionActor(user_id=7, current_tenant_id=101))
    try:
        yield SimpleNamespace(
            **vars(facts), facts=facts, seed=seed, repository=repository, service=service, runtime=runtime
        )
    finally:
        await engine.dispose()


def row(ident, *, tenant=101, kind=3, timestamp=None, name=None):
    return Knowledge(
        id=ident,
        tenant_id=tenant,
        user_id=99,
        name=name or f"space {ident}",
        type=kind,
        update_time=timestamp or datetime(2026, 11, 6),
        state=3 if ident % 2 else 0,
    )


async def test_candidate_seek_keeps_equal_times_and_legacy_nulls_in_one_stable_tenant_order(catalog):
    await catalog.seed([row(ident) for ident in range(1, 6)] + [row(6, tenant=202), row(7, kind=1)], null_ids=[4, 5])
    found = []
    after = None
    for _ in range(5):
        batch = await catalog.repository.alist_candidates(keyword=None, after=after, limit=2)
        if not batch:
            break
        found.extend(item.id for item in batch)
        after = (batch[-1].update_time, batch[-1].id)
    assert found == [3, 2, 1, 5, 4]


async def test_ordinary_pages_do_not_skip_unconsumed_rows_or_infer_space_visibility_from_other_grants(catalog):
    await catalog.seed([row(ident) for ident in range(1, 9)] + [row(20, tenant=202), row(21, kind=0)], null_ids=[1, 2])
    catalog.facts.allowed.update({1, 3, 5, 7, 20, 21})
    found, cursor = [], None
    for _ in range(10):
        page = await catalog.service.list_visible_spaces(page_size=2, cursor=cursor)
        assert "total" not in page.model_dump()
        found.extend(item.id for item in page.data)
        if not page.has_more:
            assert page.next_cursor is None
            break
        assert page.next_cursor and page.next_cursor != cursor
        cursor = page.next_cursor
    else:
        pytest.fail("ordinary cursor did not terminate")
    assert found == [7, 5, 3, 1]
    assert all(set(batch) <= set(range(1, 9)) for batch in catalog.facts.checked)
    catalog.runtime.list_visible_objects.assert_not_awaited()


async def test_all_denied_budget_page_can_be_empty_and_resume_after_last_consumed_candidate(catalog):
    await catalog.seed([row(ident) for ident in range(1, 1202)])
    catalog.facts.allowed.add(1)
    first = await catalog.service.list_visible_spaces(page_size=20)
    assert first.data == [] and first.has_more and first.next_cursor
    assert len(catalog.facts.checked) == 10
    assert sum(map(len, catalog.facts.checked)) == 1000
    assert all(len(batch) <= 100 for batch in catalog.facts.checked)
    second = await catalog.service.list_visible_spaces(page_size=20, cursor=first.next_cursor)
    assert [item.id for item in second.data] == [1] and not second.has_more
    assert [value for batch in catalog.facts.checked for value in batch] == list(range(1201, 0, -1))


async def test_cursor_is_bound_to_original_identity_tenant_and_filters(catalog):
    await catalog.seed([row(ident, name="matched") for ident in range(1, 4)])
    catalog.facts.allowed.update({1, 2, 3})
    first = await catalog.service.list_visible_spaces(keyword="matched", page_size=1)
    for options in [{"keyword": "other"}, {"keyword": "matched"}]:
        if options["keyword"] == "matched":
            catalog.service._permission_actor.return_value = PermissionActor(user_id=8, current_tenant_id=101)
        with pytest.raises(KnowledgeSpaceInvalidCursorError):
            await catalog.service.list_visible_spaces(page_size=1, cursor=first.next_cursor, **options)
    catalog.service._permission_actor.return_value = PermissionActor(user_id=7, current_tenant_id=202)
    with management_tenant_scope(202), pytest.raises(KnowledgeSpaceInvalidCursorError):
        await catalog.service.list_visible_spaces(keyword="matched", page_size=1, cursor=first.next_cursor)


@pytest.mark.parametrize(
    "cursor",
    ["broken", "W10", encode_cursor([None, 0], context="wrong"), encode_cursor(["broken", 1], context="wrong")],
)
async def test_bad_cursor_never_scans_candidates(catalog, cursor):
    catalog.repository.alist_candidates = AsyncMock(side_effect=AssertionError("invalid cursor must not scan SQL"))
    with pytest.raises(KnowledgeSpaceInvalidCursorError):
        await catalog.service.list_visible_spaces(cursor=cursor)
    catalog.repository.alist_candidates.assert_not_awaited()


async def test_same_context_malformed_cursor_keys_are_rejected(catalog):
    await catalog.seed([row(1), row(2)])
    catalog.facts.allowed.update({1, 2})
    first = await catalog.service.list_visible_spaces(page_size=1)
    import base64
    import json

    payload = json.loads(base64.urlsafe_b64decode(first.next_cursor + "=" * (-len(first.next_cursor) % 4)))
    for key in [[None, True], ["not-a-time", 1], [None, -1], [None, "2"]]:
        bad = encode_cursor(key, context=payload["s"])
        with pytest.raises(KnowledgeSpaceInvalidCursorError):
            await catalog.service.list_visible_spaces(page_size=1, cursor=bad)
    assert decode_cursor(first.next_cursor, expected_key_len=2, expected_context=payload["s"])


async def test_admin_total_is_sql_filtered_and_is_not_a_visible_or_pinned_subset(catalog):
    await catalog.seed(
        [row(ident, name="matched") for ident in range(1, 6)]
        + [row(6, name="other"), row(7, tenant=202, name="matched"), row(8, kind=1, name="matched")]
    )
    catalog.service._permission_actor.return_value = PermissionActor(user_id=7, current_tenant_id=101, super_admin=True)
    with management_tenant_scope(101):
        page = await catalog.service.list_admin_spaces(keyword="matched", page=2, page_size=2)
    assert page.total == 5 and [item.id for item in page.data] == [3, 2]
    assert not catalog.facts.checked


async def test_permission_failure_does_not_turn_partial_scan_into_a_success_page(catalog):
    await catalog.seed([row(1)])
    catalog.runtime.batch_check_actions.side_effect = RuntimeError("permission transport unavailable")
    with pytest.raises(RuntimeError, match="permission transport unavailable"):
        await catalog.service.list_visible_spaces()


async def test_real_root_super_uses_existing_business_shortcut_after_selected_tenant_target_validation(
    catalog, monkeypatch
):
    invalid = row(5)
    invalid.state = -1
    await catalog.seed([row(1), row(2), row(3, tenant=1), row(4, tenant=202), invalid, row(6)])
    snapshots = catalog.service.f048_permission_adapter._loader._versions.get_permission_snapshots
    original_snapshots = snapshots.side_effect

    async def missing_snapshot(keys):
        return {key: value for key, value in (await original_snapshots(keys)).items() if key[2] != "6"}

    snapshots.side_effect = missing_snapshot
    original = UserPayload(user_id=7, tenant_id=1, user_role=[], is_global_super=True)
    service = KnowledgeSpaceService(
        None,
        original,
        f048_permission_adapter=catalog.service.f048_permission_adapter,
        space_listing_repository=catalog.repository,
    )
    business_actions = AsyncMock(wraps=service._batch_actions)
    monkeypatch.setattr(service, "_batch_actions", business_actions)
    fga = SimpleNamespace(batch_check=AsyncMock(return_value=[]))
    decision = F048PermissionService(
        catalog=SimpleNamespace(ensure_runtime_ready=AsyncMock()),
        scope_fence=SimpleNamespace(ensure_readable=AsyncMock()),
        marker=SimpleNamespace(consistency_for=AsyncMock()),
        fga=fga,
        list_policy=SimpleNamespace(),
    )
    runtime = AsyncMock(return_value=decision)
    monkeypatch.setattr(business_authorization, "get_f048_runtime", runtime)
    token = set_current_permission_actor(None)
    try:
        with management_tenant_scope(101):
            actor = await service._permission_actor()
            assert actor.current_tenant_id == 1 and actor.super_admin
            loaded = await catalog.repository.alist_candidates(limit=100)
            targets = await service.f048_permission_adapter.resolve_permission_targets_from_rows(
                rows=loaded,
                resource_type="knowledge_space",
                actor=actor,
            )
            assert {target.tenant_id for target in targets} == {101}
            assert [target.resource_id for target in targets] == ["2", "1"]
            # The joined/square visible protocol must keep its original tenant
            # fence; the business full-scope-super shortcut is a separate path.
            assert await decision.batch_check_actions(actor, targets, "visible") == (False, False)
            page = await service.list_visible_spaces()
        assert [item.id for item in page.data] == [2, 1]
        assert original.tenant_id == actor.current_tenant_id == 1
        assert await service._permission_actor() is actor
        business_actions.assert_awaited_once_with("knowledge_space", ["2", "1"], ("visible",))
        runtime.assert_not_awaited()
        fga.batch_check.assert_not_awaited()
        assert all(key[0] == 101 for batch in catalog.facts.snapshots for key in batch)
    finally:
        reset_current_permission_actor(token)


@pytest.mark.parametrize("context", ["no_pin", "wrong_pin", "different_subject"])
async def test_real_super_home_actor_cannot_adopt_untrusted_management_scope(catalog, monkeypatch, context):
    original = UserPayload(user_id=7, tenant_id=1, user_role=[], is_global_super=True)
    service = KnowledgeSpaceService(
        None,
        original,
        f048_permission_adapter=catalog.service.f048_permission_adapter,
        space_listing_repository=catalog.repository,
    )
    scan = AsyncMock(side_effect=AssertionError("untrusted tenant must not scan SQL"))
    monkeypatch.setattr(catalog.repository, "alist_candidates", scan)
    contextual = (
        PermissionActor(user_id=8, current_tenant_id=1, super_admin=True) if context == "different_subject" else None
    )
    token = set_current_permission_actor(contextual)
    try:
        scope = tenant_execution_scope(101) if context == "no_pin" else management_tenant_scope(101)
        if context == "wrong_pin":
            monkeypatch.setattr(
                "bisheng.knowledge.domain.services.knowledge_space_service.get_admin_scope_tenant_id", lambda: 202
            )
        with scope, pytest.raises(PermissionDeniedError):
            await service.list_visible_spaces()
        scan.assert_not_awaited()
        assert original.tenant_id == (await service._permission_actor()).current_tenant_id == 1
    finally:
        reset_current_permission_actor(token)


@pytest.mark.parametrize("home,super_admin,narrowed", [(1, False, False), (202, False, False), (1, True, True)])
async def test_management_pin_does_not_expand_ordinary_tenant_admin_or_narrowed_actor(
    catalog, monkeypatch, home, super_admin, narrowed
):
    from bisheng.permission.application import relation_api

    original = UserPayload(user_id=7, tenant_id=home, user_role=[], is_global_super=super_admin)
    monkeypatch.setattr(relation_api, "is_tenant_admin", AsyncMock(return_value=home == 202))
    service = KnowledgeSpaceService(
        None,
        original,
        f048_permission_adapter=catalog.service.f048_permission_adapter,
        space_listing_repository=catalog.repository,
    )
    scan = AsyncMock(side_effect=AssertionError("cross-tenant denied identity must not scan SQL"))
    monkeypatch.setattr(catalog.repository, "alist_candidates", scan)
    contextual = (
        PermissionActor(user_id=7, current_tenant_id=home, super_admin=True, data_scope=DATA_SCOPE_PERSONAL)
        if narrowed
        else None
    )
    token = set_current_permission_actor(contextual)
    try:
        with management_tenant_scope(101), pytest.raises(PermissionDeniedError):
            await service.list_visible_spaces()
        scan.assert_not_awaited()
        actor = await service._permission_actor()
        assert actor.current_tenant_id == original.tenant_id == home
        if narrowed:
            assert actor is contextual
    finally:
        reset_current_permission_actor(token)
