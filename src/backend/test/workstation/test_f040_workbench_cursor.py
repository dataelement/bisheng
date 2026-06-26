"""F040 (C) T6b: the workbench "常用" (frequently-used) and "最近" (used) lists
move from fetch-all → enrich → Python-slice to an F027 AD-15 pseudo-cursor
envelope (key=[page_num], no total, INV-6). Both candidate sets are per-user
bounded with a CUSTOM order (favourites order / pinned+recency) that a keyset
cursor over update_time can't express, so the pseudo-cursor re-slices the bounded
set per page and enriches only the page.

Equivalence red line: each page must surface the SAME items, in the SAME order,
as the legacy slice; walking pages via next_cursor must partition the full
visible set with no gaps/dupes; enrichment must be page-bounded (tags fetched
only for the page's ids).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.api.services import workflow as workflow_mod
from bisheng.workstation.api.endpoints import apps as apps_mod

_WF = "bisheng.api.services.workflow"


class _User:
    user_id = 7

    def __init__(self, admin: bool = False):
        self._admin = admin

    def is_admin(self):
        return self._admin


# ---------------------------------------------------------------------------
# 常用 (frequently-used) — service pseudo-cursor
# ---------------------------------------------------------------------------


async def _freq_page(user, fav_ids, *, cursor, page_size, allowed=None):
    """Run aget_frequently_used_flows_cursor with the favourites list `fav_ids`
    (already in link order) and an optional view_app allow-set."""
    links = [SimpleNamespace(type_detail=fid) for fid in fav_ids]
    # get_all_apps returns rows in arbitrary order; the method re-sorts by link order.
    rows = [{"id": fid, "flow_type": 10, "logo": ""} for fid in reversed(fav_ids)]

    async def _filter(u, data, permission_id="use_app"):
        assert permission_id == "view_app"
        if allowed is None:
            return data
        return [r for r in data if r["id"] in allowed]

    with (
        patch.object(
            workflow_mod,
            "UserLinkType",
            SimpleNamespace(app=SimpleNamespace(value=[SimpleNamespace(value="app")])),
        ),
        patch.object(workflow_mod.UserLinkDao, "get_user_link", return_value=links, create=True),
        patch.object(workflow_mod.FlowDao, "get_all_apps", return_value=(rows, len(rows))),
        patch.object(workflow_mod.WorkFlowService, "filter_supported_apps", side_effect=lambda d: d),
        patch.object(workflow_mod.WorkFlowService, "filter_apps_by_permission_id", new=_filter),
        patch.object(workflow_mod.WorkFlowService, "add_extra_field", side_effect=lambda u, d: d),
        patch.object(
            workflow_mod.WorkFlowService,
            "aenrich_apps_can_share",
            new_callable=AsyncMock,
            side_effect=lambda u, d: d,
        ),
    ):
        return await workflow_mod.WorkFlowService.aget_frequently_used_flows_cursor(
            user,
            "app",
            cursor=cursor,
            page_size=page_size,
        )


async def test_frequently_used_preserves_link_order_across_pages():
    fav = [f"app{i}" for i in range(7)]  # link order app0..app6
    user = _User()

    page1 = await _freq_page(user, fav, cursor=None, page_size=3)
    assert [r["id"] for r in page1.data] == ["app0", "app1", "app2"]
    assert page1.has_more is True
    assert page1.next_cursor

    page2 = await _freq_page(user, fav, cursor=page1.next_cursor, page_size=3)
    assert [r["id"] for r in page2.data] == ["app3", "app4", "app5"]
    assert page2.has_more is True

    page3 = await _freq_page(user, fav, cursor=page2.next_cursor, page_size=3)
    assert [r["id"] for r in page3.data] == ["app6"]
    assert page3.has_more is False
    assert page3.next_cursor is None

    # Full walk == original ordered favourites, no dup/gap.
    walked = [*[r["id"] for r in page1.data], *[r["id"] for r in page2.data], *[r["id"] for r in page3.data]]
    assert walked == fav


async def test_frequently_used_permission_filter_preserved():
    fav = [f"app{i}" for i in range(5)]
    user = _User()
    # Only even-indexed favourites pass view_app.
    allowed = {"app0", "app2", "app4"}
    page = await _freq_page(user, fav, cursor=None, page_size=10, allowed=allowed)
    assert [r["id"] for r in page.data] == ["app0", "app2", "app4"]
    assert page.has_more is False


async def test_frequently_used_empty_favourites_short_circuits():
    with (
        patch.object(
            workflow_mod,
            "UserLinkType",
            SimpleNamespace(app=SimpleNamespace(value=[SimpleNamespace(value="app")])),
        ),
        patch.object(workflow_mod.UserLinkDao, "get_user_link", return_value=[], create=True),
    ):
        page = await workflow_mod.WorkFlowService.aget_frequently_used_flows_cursor(
            _User(),
            "app",
            cursor=None,
            page_size=8,
        )
    assert page.data == []
    assert page.has_more is False
    assert page.next_cursor is None


async def test_frequently_used_bad_cursor_raises_app_invalid_cursor():
    from bisheng.common.errcode.flow import AppInvalidCursorError

    raised = False
    try:
        await workflow_mod.WorkFlowService.aget_frequently_used_flows_cursor(
            _User(),
            "app",
            cursor="@@bogus@@",
            page_size=8,
        )
    except AppInvalidCursorError:
        raised = True
    assert raised


# ---------------------------------------------------------------------------
# 最近 (used apps) — endpoint pseudo-cursor + enrich-after-paginate
# ---------------------------------------------------------------------------


async def _used_page(*, cursor, page_size, n=5, tag_spy=None):
    user = MagicMock()
    user.is_admin.return_value = False
    user.user_id = 7

    base = datetime(2026, 1, 1, 12, 0, 0)
    # recency: app0 newest .. app{n-1} oldest; none pinned -> recency order app0..
    used_apps = [(f"app{i}", base - timedelta(minutes=i)) for i in range(n)]
    rows = [{"id": f"app{i}", "flow_type": 10, "logo": ""} for i in range(n)]

    tag_mock = tag_spy or MagicMock(return_value={})

    with (
        patch.object(
            apps_mod.MessageSessionDao,
            "get_user_used_apps",
            new_callable=AsyncMock,
            return_value=used_apps,
            create=True,
        ),
        patch.object(apps_mod.UserLinkDao, "get_user_link", return_value=[], create=True),
        patch.object(apps_mod.FlowDao, "aget_all_apps", new_callable=AsyncMock, return_value=(rows, n), create=True),
        patch.object(
            apps_mod.WorkFlowService,
            "filter_apps_by_permission_id",
            new=AsyncMock(side_effect=lambda u, d, permission_id="use_app": d),
        ),
        patch.object(apps_mod.WorkFlowService, "get_logo_share_link", side_effect=lambda logo: logo, create=True),
        patch.object(apps_mod.TagDao, "get_tags_by_resource", new=tag_mock),
        patch.object(apps_mod, "batch_user_may_share_app", new_callable=AsyncMock, return_value=[False] * n),
    ):
        resp = await apps_mod.get_used_apps(login_user=user, page_size=page_size, cursor=cursor)
    return resp.data, tag_mock


async def test_used_apps_pseudo_cursor_pagination():
    env1, _ = await _used_page(cursor=None, page_size=2, n=5)
    assert [a["id"] for a in env1.data] == ["app0", "app1"]
    assert env1.has_more is True

    env2, _ = await _used_page(cursor=env1.next_cursor, page_size=2, n=5)
    assert [a["id"] for a in env2.data] == ["app2", "app3"]
    assert env2.has_more is True

    env3, _ = await _used_page(cursor=env2.next_cursor, page_size=2, n=5)
    assert [a["id"] for a in env3.data] == ["app4"]
    assert env3.has_more is False
    assert env3.next_cursor is None


async def test_used_apps_enrichment_is_page_bounded():
    """Tags are fetched only for the page's ids, not the whole used history."""
    tag_spy = MagicMock(return_value={})
    env, tag_mock = await _used_page(cursor=None, page_size=2, n=6, tag_spy=tag_spy)
    assert [a["id"] for a in env.data] == ["app0", "app1"]
    # get_tags_by_resource(None, page_flow_ids) — second positional is the id list.
    called_ids = tag_mock.call_args.args[1]
    assert set(called_ids) == {"app0", "app1"}, "enrichment must not scan the whole history"


async def test_used_apps_empty_history_returns_empty_envelope():
    user = MagicMock()
    user.is_admin.return_value = False
    user.user_id = 7
    with patch.object(
        apps_mod.MessageSessionDao, "get_user_used_apps", new_callable=AsyncMock, return_value=[], create=True
    ):
        resp = await apps_mod.get_used_apps(login_user=user, page_size=20, cursor=None)
    env = resp.data
    assert env.data == []
    assert env.has_more is False
    assert env.next_cursor is None


async def test_used_apps_bad_cursor_raises_app_invalid_cursor():
    from bisheng.common.errcode.flow import AppInvalidCursorError

    user = MagicMock()
    user.is_admin.return_value = False
    user.user_id = 7
    raised = False
    try:
        await apps_mod.get_used_apps(login_user=user, page_size=20, cursor="@@bogus@@")
    except AppInvalidCursorError:
        raised = True
    assert raised
