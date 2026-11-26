"""Tenant user lists must return displayable avatar links, not storage keys."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from bisheng.tenant.domain.repositories.management_search_repository import ManagementSearchRepository
from bisheng.tenant.domain.services.tenant_service import TenantService


@pytest.fixture
def avatar_links(monkeypatch):
    links = {
        "avatar/1/admin.jpg": "/object/bisheng/avatar/1/admin.jpg?signature=fresh",
        "http://minio:9000/bisheng/avatar/2/old.jpg?signature=expired": "/object/bisheng/avatar/2/old.jpg?signature=fresh",
        "https://example.com/photo.jpg": "https://example.com/photo.jpg",
        None: None,
        "": "",
    }
    resolve = AsyncMock(side_effect=lambda user_id, avatar: links[avatar])
    records = {index: (SimpleNamespace(avatar=avatar), "active", 5) for index, avatar in enumerate(links, start=1)}
    monkeypatch.setattr(
        "bisheng.user.application.avatar.read_current_person_records",
        AsyncMock(return_value=records),
    )
    monkeypatch.setitem(
        sys.modules,
        "bisheng.user.domain.services.user",
        SimpleNamespace(UserService=SimpleNamespace(get_display_avatar_url=resolve)),
    )
    return resolve, links


async def test_tenant_user_avatars_are_resolved_without_changing_page(monkeypatch, avatar_links):
    resolve, links = avatar_links
    rows = [
        {"user_id": index, "user_name": f"user-{index}", "external_id": f"E{index}", "avatar": avatar}
        for index, avatar in enumerate(links, start=1)
    ]
    expected = [dict(row, avatar=links[row["avatar"]] or None) for row in rows]
    query = AsyncMock(return_value=(rows, 27))
    monkeypatch.setattr(ManagementSearchRepository, "tenant_users", query)

    result = await TenantService.aget_tenant_users(5, 2, 5, " alice ", login_user=None)

    assert result == {"data": expected, "total": 27}
    query.assert_awaited_once_with(tenant_id=5, page=2, page_size=5, keyword="alice")
    assert resolve.await_count == sum(bool(row["avatar"]) for row in rows)


async def test_empty_tenant_user_page_does_not_resolve_avatars(monkeypatch, avatar_links):
    resolve, _ = avatar_links
    monkeypatch.setattr(ManagementSearchRepository, "tenant_users", AsyncMock(return_value=([], 27)))

    assert await TenantService.aget_tenant_users(5, 99, 5, None, None) == {"data": [], "total": 27}
    resolve.assert_not_awaited()


async def test_invalid_keyword_is_rejected_before_query_or_avatar_lookup(monkeypatch, avatar_links):
    resolve, _ = avatar_links
    query = AsyncMock()
    monkeypatch.setattr(ManagementSearchRepository, "tenant_users", query)

    with pytest.raises(HTTPException) as exc:
        await TenantService.aget_tenant_users(5, 1, 5, "a" * 256, None)

    assert exc.value.status_code == 422
    query.assert_not_awaited()
    resolve.assert_not_awaited()
