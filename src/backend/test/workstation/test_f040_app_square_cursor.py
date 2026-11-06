"""F040: /app/uncategorized and /chat/online default path are cursor waterfalls.

These pin the *behaviour* of the cursor migration (the static guards in
test_f040_app_square_bounded_scan.py only pin the source shape):

- the keyset scan resumes strictly after the cursor (no re-scan of prior pages,
  no overlap, no gaps) while filtering out non-visible rows across batches;
- the uncategorized envelope round-trips its own ``next_cursor`` without
  eagerly resolving edit/share actions;
- the ranked online envelope strips the internal ``_used_rank``/``_sort_time``
  helper columns without eagerly resolving edit/share actions.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from bisheng.api.services import workflow as wf
from bisheng.api.services.workflow import WorkFlowService

# Rows 1..10, id "1" newest (update_time descending with the id number).
_VISIBLE_IDS = {"1", "2", "4", "5", "7", "8", "10"}  # 3, 6, 9 are filtered out


def _rows(n: int) -> list[dict]:
    base = datetime(2026, 1, 1, 12, 0, 0)
    return [
        {
            "id": str(i),
            "flow_type": 10,
            "logo": "",
            "user_id": 1,
            "name": f"app{i}",
            "description": "",
            "status": 2,
            "create_time": base,
            "update_time": base - timedelta(minutes=i),
        }
        for i in range(1, n + 1)
    ]


class _FakeFlowDao:
    """Honours (update_time, id) keyset cursor + limit over a fixed dataset."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.cursors: list = []
        self.id_lists: list[list[str] | None] = []

    async def aget_all_apps(
        self,
        *,
        name=None,
        status=None,
        id_list=None,
        flow_type=None,
        id_list_not_in=None,
        page=0,
        limit=0,
        search_description=False,
        cursor=None,
        ranking_user_id=None,
        # F056 pins these on both square entries (status_exempt_flow_types /
        # app_state_in). The real DAO takes them; swallow them here so this
        # fixture keeps testing the cursor walk and nothing else.
        **_f056_square_filters,
    ):
        self.cursors.append(cursor)
        self.id_lists.append(id_list)
        rows = [
            row
            for row in self.rows
            if (not id_list or str(row["id"]) in {str(value) for value in id_list})
            and (not id_list_not_in or str(row["id"]) not in {str(value) for value in id_list_not_in})
        ]
        start = 0
        if cursor is not None:
            cut, cid = cursor[0], cursor[-1]
            for i, row in enumerate(rows):
                ut = row["update_time"]
                ut_match = ut == cut or (hasattr(ut, "isoformat") and ut.isoformat() == cut)
                if ut_match and str(row["id"]) == str(cid):
                    start = i + 1
                    break
        window = rows[start : start + limit]
        has_more = (start + limit) < len(rows)
        return [copy.deepcopy(row) for row in window], has_more


async def _fake_action_map(user, data, actions, actions_by_type=None):
    # F056 asks the square for per-resource-type actions (``actions_by_type``);
    # these rows are all plain workflows, so the default set is what applies.
    del actions_by_type
    return {
        str(item["id"]): (frozenset(actions) if str(item["id"]) in _VISIBLE_IDS else frozenset())
        for item in data
    }


@pytest.mark.asyncio
async def test_cursor_scan_resumes_after_cursor_without_overlap_or_gaps():
    fake = _FakeFlowDao(_rows(10))
    user = MagicMock()

    with (
        patch.object(wf.FlowDao, "aget_all_apps", new=fake.aget_all_apps),
        patch.object(wf, "_APP_COMPAT_PAGE_SCAN_BATCH_SIZE", 3),
        patch.object(WorkFlowService, "_application_action_map", new=AsyncMock(side_effect=_fake_action_map)),
    ):
        page1, more1, _ = await WorkFlowService._scan_visible_apps_cursor(
            user=user, page_size=3, status=2, action="visible"
        )
        assert [p["id"] for p in page1] == ["1", "2", "4"]
        assert more1 is True

        cur2 = [page1[-1]["update_time"], page1[-1]["id"]]
        page2, more2, _ = await WorkFlowService._scan_visible_apps_cursor(
            user=user, page_size=3, status=2, action="visible", cursor=cur2
        )
        assert [p["id"] for p in page2] == ["5", "7", "8"]
        assert more2 is True

        cur3 = [page2[-1]["update_time"], page2[-1]["id"]]
        page3, more3, _ = await WorkFlowService._scan_visible_apps_cursor(
            user=user, page_size=3, status=2, action="visible", cursor=cur3
        )
        assert [p["id"] for p in page3] == ["10"]
        assert more3 is False

    # No id appears twice across the three pages (no overlap, no gaps).
    seen = [p["id"] for p in (*page1, *page2, *page3)]
    assert seen == ["1", "2", "4", "5", "7", "8", "10"]
    assert len(seen) == len(set(seen))


@pytest.mark.asyncio
async def test_uncategorized_envelope_roundtrips_its_own_next_cursor():
    fake = _FakeFlowDao(_rows(10))
    user = MagicMock()
    actor = SimpleNamespace(
        super_admin=False,
        current_tenant_id=25,
        tenant_admin_tenant_ids=frozenset(),
    )
    collect_visible = AsyncMock(return_value=sorted(_VISIBLE_IDS))
    action_map = AsyncMock(side_effect=_fake_action_map)

    with (
        patch.object(wf.FlowDao, "aget_all_apps", new=fake.aget_all_apps),
        patch.object(wf, "_APP_COMPAT_PAGE_SCAN_BATCH_SIZE", 3),
        patch.object(wf, "resolve_permission_actor", new=AsyncMock(return_value=actor)),
        patch.object(WorkFlowService, "_collect_visible_app_ids", new=collect_visible),
        patch.object(WorkFlowService, "_application_action_map", new=action_map),
        patch.object(wf.TagDao, "asearch_tags", new=AsyncMock(return_value=[])),
        patch.object(WorkFlowService, "get_logo_share_link", side_effect=lambda logo: logo),
    ):
        env1 = await WorkFlowService.get_uncategorized_flows_envelope(user, cursor=None, page_size=3)
        assert [d["id"] for d in env1.data] == ["1", "2", "4"]
        assert env1.has_more is True
        assert env1.next_cursor
        assert all("can_share" not in item for item in env1.data)

        env2 = await WorkFlowService.get_uncategorized_flows_envelope(user, cursor=env1.next_cursor, page_size=3)
        assert [d["id"] for d in env2.data] == ["5", "7", "8"]

    collect_visible.assert_has_awaits([call(actor, flow_type=None), call(actor, flow_type=None)])
    assert action_map.await_count
    assert all(args.args[2] == ("visible",) for args in action_map.await_args_list)
    assert fake.id_lists
    assert all(id_list == sorted(_VISIBLE_IDS) for id_list in fake.id_lists)


@pytest.mark.asyncio
async def test_uncategorized_empty_visible_ids_short_circuits_before_business_queries():
    user = MagicMock()
    actor = SimpleNamespace(
        super_admin=False,
        current_tenant_id=25,
        tenant_admin_tenant_ids=frozenset(),
    )
    search_tags = AsyncMock()
    scan = AsyncMock()

    with (
        patch.object(wf, "resolve_permission_actor", new=AsyncMock(return_value=actor)),
        patch.object(WorkFlowService, "_collect_visible_app_ids", new=AsyncMock(return_value=[])),
        patch.object(wf.TagDao, "asearch_tags", new=search_tags),
        patch.object(WorkFlowService, "_scan_visible_apps_cursor", new=scan),
    ):
        result = await WorkFlowService.get_uncategorized_flows_envelope(user, page_size=20)

    assert result.data == []
    assert result.has_more is False
    assert result.next_cursor is None
    search_tags.assert_not_awaited()
    scan.assert_not_awaited()


@pytest.mark.asyncio
async def test_uncategorized_admin_skips_visible_id_enumeration():
    user = MagicMock()
    actor = SimpleNamespace(
        super_admin=True,
        current_tenant_id=1,
        tenant_admin_tenant_ids=frozenset(),
    )
    collect_visible = AsyncMock()
    scan = AsyncMock(return_value=([], False, {}))

    with (
        patch.object(wf, "resolve_permission_actor", new=AsyncMock(return_value=actor)),
        patch.object(WorkFlowService, "_collect_visible_app_ids", new=collect_visible),
        patch.object(wf.TagDao, "asearch_tags", new=AsyncMock(return_value=[])),
        patch.object(WorkFlowService, "_scan_visible_apps_cursor", new=scan),
    ):
        await WorkFlowService.get_uncategorized_flows_envelope(user, page_size=20)

    collect_visible.assert_not_awaited()
    assert scan.await_args.kwargs["id_list"] is None
    assert scan.await_args.kwargs["additional_actions"] == ()


@pytest.mark.asyncio
async def test_online_cursor_strips_ranking_columns_without_eager_edit_or_share():
    page_items = [
        {"id": "1", "flow_type": 10, "logo": "", "user_id": 1, "_used_rank": 0, "_sort_time": datetime(2026, 1, 1)},
        {"id": "2", "flow_type": 10, "logo": "", "user_id": 1, "_used_rank": 1, "_sort_time": datetime(2026, 1, 1)},
    ]
    action_map = {"1": frozenset({"use"}), "2": frozenset({"use"})}

    async def _fake_scan(**kwargs):
        return page_items, True, action_map

    user = MagicMock()
    user.user_id = 7
    scan = AsyncMock(side_effect=_fake_scan)
    enrich = MagicMock(side_effect=lambda _u, data, **kw: data)

    with (
        patch.object(WorkFlowService, "_scan_visible_apps_cursor", new=scan),
        patch.object(WorkFlowService, "add_extra_field", new=enrich),
        patch.object(WorkFlowService, "get_logo_share_link", side_effect=lambda logo: logo),
    ):
        env = await WorkFlowService.get_online_flows_cursor(
            user, None, 2, None, None, cursor=None, page_size=2, action="use"
        )

    assert env.has_more is True
    assert env.next_cursor  # derived from the last item's ranked key before stripping
    for item in env.data:
        assert "_used_rank" not in item
        assert "_sort_time" not in item
        assert "can_share" not in item
    assert scan.await_args.kwargs["additional_actions"] == ()
    assert enrich.call_args.kwargs["writeable_ids"] == set()
