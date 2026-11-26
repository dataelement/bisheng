from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.api.services import tag
from bisheng.common.schemas.api import PageInfiniteCursorData
from bisheng.core.context.tenant import is_strict_tenant_filter, tenant_execution_scope
from bisheng.workstation.api.endpoints import apps


async def test_app_categories_exclude_root_tags(monkeypatch):
    local_tag = SimpleNamespace(id=7)
    root_tag = SimpleNamespace(id=1)
    monkeypatch.setattr(tag.ConfigDao, "aget_config", AsyncMock(return_value=SimpleNamespace(value="[1, 7]")))
    monkeypatch.setattr(tag.TenantWorkstationConfigDao, "aget", AsyncMock(return_value=None))

    def fetch_tags(*args, **kwargs):
        return [local_tag] if is_strict_tenant_filter() else [root_tag, local_tag]

    def count_tags(*args, **kwargs):
        return len(fetch_tags())

    monkeypatch.setattr(tag.TagDao, "aget_tags_by_ids", AsyncMock(side_effect=fetch_tags))
    monkeypatch.setattr(tag.TagDao, "search_tags", fetch_tags)
    monkeypatch.setattr(tag.TagDao, "count_tags", count_tags)
    user = SimpleNamespace(user_id=841, tenant_id=69)
    with tenant_execution_scope(69):
        assert await tag.TagService.get_home_tag(None, user) == [local_tag]
        assert tag.TagService.get_all_tag(None, user) == ([local_tag], 1)


async def test_uncategorized_scans_only_current_tenant(monkeypatch):
    async def scan(*args, **kwargs):
        assert is_strict_tenant_filter()
        return PageInfiniteCursorData(data=[], page_size=8, has_more=False, next_cursor=None)

    monkeypatch.setattr(apps.WorkFlowService, "get_uncategorized_flows_envelope", AsyncMock(side_effect=scan))
    await apps.get_uncategorized_chat(login_user=SimpleNamespace(user_id=841, tenant_id=69))
    assert not is_strict_tenant_filter()
