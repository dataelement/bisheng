"""AC-46: sensitive management checks cannot trust an old positive cache."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.admin_scope import AdminScopeUnavailableError
from bisheng.database.constants import AdminRole
from bisheng.utils.http_middleware import _check_is_global_super


@pytest.mark.parametrize("cached", [0, 1])
async def test_current_check_uses_authority_instead_of_cache(monkeypatch, cached):
    from bisheng.core.cache import redis_manager
    from bisheng.permission import application

    redis = SimpleNamespace(aget=AsyncMock(return_value=cached), aset=AsyncMock())
    relation = SimpleNamespace(check=AsyncMock(return_value=False))
    monkeypatch.setattr(redis_manager, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(application, "get_permission_relation_api", AsyncMock(return_value=relation))
    assert await _check_is_global_super(191, role_ids=[], force_refresh=True) is False
    relation.check.assert_awaited_once()
    redis.aget.assert_not_awaited()
    redis.aset.assert_awaited_once_with("user:191:is_super", 0, expiration=300)


async def test_current_check_preserves_independent_legacy_admin_source(monkeypatch):
    from bisheng.core.cache import redis_manager
    from bisheng.permission import application

    redis = SimpleNamespace(aget=AsyncMock(return_value=0), aset=AsyncMock())
    monkeypatch.setattr(redis_manager, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(application, "get_permission_relation_api", AsyncMock(side_effect=RuntimeError("unavailable")))
    assert await _check_is_global_super(191, role_ids=[AdminRole], force_refresh=True) is True


async def test_unknown_qualification_rejects_without_replacing_positive_cache(monkeypatch):
    from bisheng.core.cache import redis_manager
    from bisheng.permission import application

    redis = SimpleNamespace(aget=AsyncMock(return_value=1), aset=AsyncMock())
    monkeypatch.setattr(redis_manager, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(application, "get_permission_relation_api", AsyncMock(side_effect=RuntimeError("unavailable")))
    with pytest.raises(AdminScopeUnavailableError):
        await _check_is_global_super(191, role_ids=[], force_refresh=True)
    redis.aset.assert_not_awaited()


async def test_downstream_check_keeps_the_current_admitted_decision(monkeypatch):
    from bisheng.common.request_scope import admitted_request_scope
    from bisheng.core.cache import redis_manager

    cache = AsyncMock()
    monkeypatch.setattr(redis_manager, "get_redis_client", cache)
    token = admitted_request_scope.set(SimpleNamespace(user_id=191, is_super=False))
    try:
        assert await _check_is_global_super(191) is False
        cache.assert_not_awaited()
    finally:
        admitted_request_scope.reset(token)
