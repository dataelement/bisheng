"""T725: actual space-list service and native SQL keep F064 anomaly semantics."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge_space import KnowledgeSpaceInvalidCursorError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import management_tenant_scope
from bisheng.knowledge.domain.services.knowledge_permission_service import (
    F048KnowledgeContainerPermissionAdapter,
    KnowledgeContainerDaoPermissionLoader,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.application import business_authorization
from bisheng.permission.application.control_state import PermissionResourceSnapshot
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.knowledge_unification import test_space_abnormal_listing_repository as fixtures

file, space, store = fixtures.file, fixtures.space, fixtures.store
concrete_tenant = fixtures.concrete_tenant


@pytest.fixture
def listing(store, monkeypatch):
    allowed, checked = set(), []

    async def snapshots(keys):
        assert store.facts.open_sessions == 0
        return {key: PermissionResourceSnapshot(*key, 3, "ctx3", "CUSTOM", None, None, "READY") for key in keys}

    async def check(actor, targets, action):
        assert store.facts.open_sessions == 0 and action == "visible"
        checked.append(tuple(int(target.resource_id) for target in targets))
        return tuple(int(target.resource_id) in allowed for target in targets)

    runtime = SimpleNamespace(batch_check_actions=AsyncMock(side_effect=check))
    monkeypatch.setattr(business_authorization, "get_f048_runtime", AsyncMock(return_value=runtime))
    adapter = F048KnowledgeContainerPermissionAdapter(
        loader=KnowledgeContainerDaoPermissionLoader(
            SimpleNamespace(get_permission_snapshots=AsyncMock(side_effect=snapshots))
        ),
        permission=SimpleNamespace(),
    )
    service = KnowledgeSpaceService(
        None,
        SimpleNamespace(user_id=7, tenant_id=101),
        f048_permission_adapter=adapter,
        space_listing_repository=store.repository,
    )
    service._permission_actor = AsyncMock(return_value=PermissionActor(user_id=7, current_tenant_id=101))
    return SimpleNamespace(store=store, service=service, runtime=runtime, allowed=allowed, checked=checked)


def marker_reads(store):
    return [query for query in store.facts.selects if query[0].lower().startswith("select knowledge.id ")]


async def test_final_visible_page_marks_only_returned_spaces_in_one_native_batch(listing):
    await listing.store.seed(
        *(space(ident) for ident in range(1, 8)),
        file(11, 1),
        file(12, 3, status=6),
        file(13, 5, tenant=202),
        file(14, 7, status=7),
        file(15, 6),
    )
    listing.allowed.update({1, 3, 5, 7})
    page = await listing.service.list_visible_spaces(page_size=2)
    assert [(item.id, item.has_abnormal_files) for item in page.data] == [(7, True), (5, False)]
    assert page.has_more and page.next_cursor and "total" not in page.model_dump()
    markers = marker_reads(listing.store)
    assert len(markers) == 1
    assert set(markers[0][1]) >= {5, 7} and 6 not in markers[0][1]
    assert all(len(batch) <= 100 for batch in listing.checked)


async def test_filtered_visible_cursor_uses_sql_candidates_then_original_permission_checks(listing):
    await listing.store.seed(
        *(space(ident) for ident in range(1, 10)),
        *(file(100 + ident, ident) for ident in (2, 4, 6, 8)),
        file(199, 9, tenant=202),
    )
    listing.allowed.update({2, 6, 8, 9})
    ids, cursor = [], None
    for _ in range(5):
        page = await listing.service.list_visible_spaces(page_size=1, has_abnormal=True, cursor=cursor)
        ids.extend(item.id for item in page.data)
        assert all(item.has_abnormal_files is True for item in page.data)
        if not page.has_more:
            break
        cursor = page.next_cursor
    else:
        pytest.fail("anomaly cursor did not terminate")
    assert ids == [8, 6, 2]
    assert {value for batch in listing.checked for value in batch} <= {2, 4, 6, 8}


async def test_full_200_visible_page_has_one_marker_read_after_two_permission_batches(listing):
    await listing.store.seed(*(space(ident) for ident in range(1, 202)), file(1001, 200), file(1002, 1))
    listing.allowed.update(range(1, 202))
    page = await listing.service.list_visible_spaces(page_size=200)
    assert [item.id for item in page.data] == list(range(201, 1, -1))
    assert {item.id for item in page.data if item.has_abnormal_files} == {200}
    assert [len(batch) for batch in listing.checked] == [100, 100]
    assert len(marker_reads(listing.store)) == 1
    assert len(listing.store.facts.selects) == 4 and page.has_more


async def test_false_and_none_share_cursor_but_true_is_separate_context(listing):
    await listing.store.seed(*(space(ident) for ident in range(1, 5)), file(10, 1), file(11, 3))
    listing.allowed.update({1, 2, 3, 4})
    ordinary = await listing.service.list_visible_spaces(page_size=1, has_abnormal=False)
    second = await listing.service.list_visible_spaces(page_size=1, cursor=ordinary.next_cursor)
    assert [item.id for item in second.data] == [3]
    before = len(listing.store.facts.selects)
    with pytest.raises(KnowledgeSpaceInvalidCursorError):
        await listing.service.list_visible_spaces(page_size=1, cursor=ordinary.next_cursor, has_abnormal=True)
    assert len(listing.store.facts.selects) == before
    abnormal = await listing.service.list_visible_spaces(page_size=1, has_abnormal=True)
    with pytest.raises(KnowledgeSpaceInvalidCursorError):
        await listing.service.list_visible_spaces(page_size=1, cursor=abnormal.next_cursor, has_abnormal=False)


@pytest.mark.parametrize("flag", [None, False, True])
async def test_admin_count_and_page_use_same_filter_without_ordinary_fga(listing, flag):
    await listing.store.seed(
        *(space(ident) for ident in range(1, 8)), file(11, 1), file(12, 3), file(13, 5), file(14, 7, tenant=202)
    )
    listing.service._permission_actor.return_value = PermissionActor(user_id=7, current_tenant_id=101, super_admin=True)
    with management_tenant_scope(101):
        page = await listing.service.list_admin_spaces(page=2, page_size=2, has_abnormal=flag)
    expected = [(1, True)] if flag else [(5, True), (4, False)]
    assert page.total == (3 if flag else 7)
    assert [(item.id, item.has_abnormal_files) for item in page.data] == expected
    assert not listing.checked and len(marker_reads(listing.store)) == 1
    assert len(listing.store.facts.selects) == 3


async def test_denied_or_empty_visible_page_performs_no_file_status_read(listing):
    await listing.store.seed(space(1), file(11, 1))
    page = await listing.service.list_visible_spaces()
    assert not page.data and marker_reads(listing.store) == []


async def test_permission_transport_failure_propagates_without_file_read(listing):
    await listing.store.seed(space(1), file(11, 1))
    listing.runtime.batch_check_actions.side_effect = RuntimeError("permission unavailable")
    with pytest.raises(RuntimeError, match="permission unavailable"):
        await listing.service.list_visible_spaces()
    assert marker_reads(listing.store) == []


async def test_final_marker_failure_does_not_return_false_success(listing):
    await listing.store.seed(space(1), file(11, 1))
    listing.allowed.add(1)
    listing.store.repository.aexists_abnormal_files = AsyncMock(side_effect=RuntimeError("status read unavailable"))
    with pytest.raises(RuntimeError, match="status read unavailable"):
        await listing.service.list_visible_spaces()


async def test_anomaly_flag_does_not_expand_admin_gate(listing):
    await listing.store.seed(space(1), file(11, 1))
    with management_tenant_scope(101), pytest.raises(PermissionDeniedError):
        await listing.service.list_admin_spaces(has_abnormal=True)
    assert listing.store.facts.selects == []
