"""F040 (C) T6b: the workbench "最近" (used apps) list stays on the per-user
bounded offset ``{list, total}`` contract (INV-6 exemption — bounded set, no deep
pagination), but keeps the F040 enrich-AFTER-paginate optimization: the page is
sliced first and only then decorated with tags / logo / can_share, so per-request
enrichment is bounded by ``limit`` instead of the whole used-app history.

Equivalence red line: same page items, same pinned+recency order, same total as
the legacy path; enrichment must be page-bounded (tags fetched only for the page's
ids). The "常用" list reverted to the existing offset
``WorkFlowService.get_frequently_used_flows`` (covered by
test_workflow_service_app_permissions.py), so it is not re-tested here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.workstation.api.endpoints import apps as apps_mod


async def _used_page(*, page, limit, n=5, tag_spy=None):
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
        resp = await apps_mod.get_used_apps(login_user=user, page=page, limit=limit)
    return resp.data, tag_mock


async def test_used_apps_offset_pagination_preserves_order_and_total():
    page1, _ = await _used_page(page=1, limit=2, n=5)
    assert [a["id"] for a in page1["list"]] == ["app0", "app1"]
    assert page1["total"] == 5

    page2, _ = await _used_page(page=2, limit=2, n=5)
    assert [a["id"] for a in page2["list"]] == ["app2", "app3"]
    assert page2["total"] == 5

    page3, _ = await _used_page(page=3, limit=2, n=5)
    assert [a["id"] for a in page3["list"]] == ["app4"]
    assert page3["total"] == 5


async def test_used_apps_enrichment_is_page_bounded():
    """Tags are fetched only for the page's ids, not the whole used history."""
    tag_spy = MagicMock(return_value={})
    env, tag_mock = await _used_page(page=1, limit=2, n=6, tag_spy=tag_spy)
    assert [a["id"] for a in env["list"]] == ["app0", "app1"]
    # get_tags_by_resource(None, page_flow_ids) — second positional is the id list.
    called_ids = tag_mock.call_args.args[1]
    assert set(called_ids) == {"app0", "app1"}, "enrichment must not scan the whole history"


async def test_used_apps_empty_history_returns_empty_list():
    user = MagicMock()
    user.is_admin.return_value = False
    user.user_id = 7
    with patch.object(
        apps_mod.MessageSessionDao, "get_user_used_apps", new_callable=AsyncMock, return_value=[], create=True
    ):
        resp = await apps_mod.get_used_apps(login_user=user, page=1, limit=20)
    assert resp.data == {"list": [], "total": 0}
