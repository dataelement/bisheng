"""F019-admin-tenant-scope — TenantScopeService unit tests.

Covers AC-01/02/03 (set/get/clear), AC-14 (audit payload), AC-15 (invalid
tenant), plus the three hook methods (AC-10/11/12 method bodies; endpoint
wiring for those ACs is verified by later tasks).

Mocks the shape of ``RedisClient``'s async surface and the two DAO
classes touched by the service. Nothing in this test suite needs a real
Redis or DB.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock

import pytest


MODULE = 'bisheng.admin.domain.services.tenant_scope'


class _FakeRedis:
    """Async stand-in for the subset of ``RedisClient`` we use.

    - ``aget(k)`` returns the stored *string* (not pickled bytes) because
      the service only stores ``str(tenant_id)``, matching what the
      unpickling inside ``RedisClient.aget`` would return at runtime.
    - ``aset`` records the last ``expiration`` for TTL assertions.
    - ``attl`` reads from a parallel dict so tests can simulate remaining
      TTL without sleeping.
    """

    def __init__(self):
        self.store: Dict[str, str] = {}
        self.ttls: Dict[str, int] = {}
        self.last_ex: Optional[int] = None
        self.expire_calls: list[tuple[str, int]] = []

    async def aget(self, key: str):
        return self.store.get(key)

    async def aset(self, key: str, value: str, expiration: int = 3600):
        self.store[key] = value
        self.ttls[key] = expiration
        self.last_ex = expiration

    async def adelete(self, key: str):
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return 1

    async def attl(self, key: str) -> int:
        if key not in self.store:
            return -2
        return self.ttls.get(key, -1)

    async def aexpire_key(self, key: str, expiration: int):
        self.ttls[key] = expiration
        self.expire_calls.append((key, expiration))


@pytest.fixture()
def fake_redis(monkeypatch):
    r = _FakeRedis()

    async def _get_client():
        return r

    monkeypatch.setattr(f'{MODULE}.get_redis_client', _get_client)
    return r


@pytest.fixture()
def fake_settings(monkeypatch):
    s = SimpleNamespace(multi_tenant=SimpleNamespace(admin_scope_ttl_seconds=14400))
    monkeypatch.setattr(f'{MODULE}.settings', s)
    return s


@pytest.fixture()
def mock_tenant_dao(monkeypatch):
    dao = SimpleNamespace(aexists=AsyncMock(return_value=True))
    monkeypatch.setattr(f'{MODULE}.TenantDao', dao)
    return dao


@pytest.fixture()
def mock_audit_dao(monkeypatch):
    dao = SimpleNamespace(ainsert_v2=AsyncMock())
    monkeypatch.setattr(f'{MODULE}.AuditLogDao', dao)
    return dao


@pytest.fixture()
def all_mocks(fake_redis, fake_settings, mock_tenant_dao, mock_audit_dao):
    return SimpleNamespace(
        redis=fake_redis,
        settings=fake_settings,
        tenant=mock_tenant_dao,
        audit=mock_audit_dao,
    )


# ---------------------------------------------------------------------------
# set_scope
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_scope_first_time(all_mocks):
    """AC-01: fresh scope set — Redis key written with TTL, audit records
    from_scope=None / to_scope=5, response carries expires_at."""
    from bisheng.admin.domain.services.tenant_scope import TenantScopeService

    result = await TenantScopeService.set_scope(
        user_id=42,
        tenant_id=5,
        request_context={'ip': '10.0.0.1', 'ua': 'curl'},
    )

    assert result['scope_tenant_id'] == 5
    assert result['expires_at'] is not None
    assert all_mocks.redis.store['admin_scope:42'] == '5'
    assert all_mocks.redis.last_ex == 14400

    all_mocks.audit.ainsert_v2.assert_awaited_once()
    kwargs = all_mocks.audit.ainsert_v2.await_args.kwargs
    assert kwargs['metadata']['from_scope'] is None
    assert kwargs['metadata']['to_scope'] == 5


@pytest.mark.asyncio
async def test_set_scope_override_existing(all_mocks):
    """AC-01 continuation: replacing scope 3 with 5 — audit records the
    prior value so operators can reconstruct the session."""
    from bisheng.admin.domain.services.tenant_scope import TenantScopeService
    all_mocks.redis.store['admin_scope:42'] = '3'

    await TenantScopeService.set_scope(user_id=42, tenant_id=5, request_context={})

    kwargs = all_mocks.audit.ainsert_v2.await_args.kwargs
    assert kwargs['metadata']['from_scope'] == 3
    assert kwargs['metadata']['to_scope'] == 5
    assert all_mocks.redis.store['admin_scope:42'] == '5'


@pytest.mark.asyncio
async def test_set_scope_clear_with_none(all_mocks):
    """AC-03: body tenant_id=null → Redis DEL; audit records the clear."""
    from bisheng.admin.domain.services.tenant_scope import TenantScopeService
    all_mocks.redis.store['admin_scope:42'] = '5'

    result = await TenantScopeService.set_scope(user_id=42, tenant_id=None, request_context={})

    assert result == {'scope_tenant_id': None, 'expires_at': None}
    assert 'admin_scope:42' not in all_mocks.redis.store
    kwargs = all_mocks.audit.ainsert_v2.await_args.kwargs
    assert kwargs['metadata']['from_scope'] == 5
    assert kwargs['metadata']['to_scope'] is None
    # When clearing, audit row still has a tenant_id — defaults to Root.
    assert kwargs['tenant_id'] == 1


@pytest.mark.asyncio
async def test_set_scope_tenant_not_found_raises_19702(all_mocks):
    """AC-15: unknown tenant id → 19702 before Redis is touched."""
    from bisheng.admin.domain.services.tenant_scope import TenantScopeService
    from bisheng.common.errcode.admin_scope import AdminScopeTenantNotFoundError
    all_mocks.tenant.aexists.return_value = False

    with pytest.raises(AdminScopeTenantNotFoundError):
        await TenantScopeService.set_scope(
            user_id=42, tenant_id=999, request_context={},
        )

    assert 'admin_scope:42' not in all_mocks.redis.store
    all_mocks.audit.ainsert_v2.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_scope_ttl_applied(all_mocks):
    """AC-08: TTL on the Redis key matches settings.admin_scope_ttl_seconds."""
    from bisheng.admin.domain.services.tenant_scope import TenantScopeService
    all_mocks.settings.multi_tenant.admin_scope_ttl_seconds = 7200  # override

    await TenantScopeService.set_scope(user_id=42, tenant_id=5, request_context={})

    assert all_mocks.redis.ttls['admin_scope:42'] == 7200


@pytest.mark.asyncio
async def test_set_scope_audit_uses_root_operator_tenant_id(all_mocks):
    """AC-14: operator_tenant_id is always Root (INV-T11 — super admin
    leaf is always Root, Root is unique and indestructible)."""
    from bisheng.admin.domain.services.tenant_scope import TenantScopeService

    await TenantScopeService.set_scope(
        user_id=42, tenant_id=5,
        request_context={'ip': '10.0.0.1', 'ua': 'Mozilla/x'},
    )

    kwargs = all_mocks.audit.ainsert_v2.await_args.kwargs
    assert kwargs['operator_tenant_id'] == 1
    assert kwargs['operator_id'] == 42
    assert kwargs['tenant_id'] == 5
    assert kwargs['action'] == 'admin.scope_switch'
    assert kwargs['metadata']['ip'] == '10.0.0.1'
    assert kwargs['metadata']['user_agent'] == 'Mozilla/x'
    # ip_address is also forwarded to the dedicated column.
    assert kwargs['ip_address'] == '10.0.0.1'


# ---------------------------------------------------------------------------
# get_scope
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_scope_empty(all_mocks):
    """AC-02 edge: unset scope returns both fields as None."""
    from bisheng.admin.domain.services.tenant_scope import TenantScopeService

    result = await TenantScopeService.get_scope(user_id=42)

    assert result == {'scope_tenant_id': None, 'expires_at': None}


@pytest.mark.asyncio
async def test_get_scope_with_value(all_mocks):
    """AC-02: existing scope returns tenant id + ISO expiry derived from
    remaining TTL (not a heuristic)."""
    from bisheng.admin.domain.services.tenant_scope import TenantScopeService
    all_mocks.redis.store['admin_scope:42'] = '5'
    all_mocks.redis.ttls['admin_scope:42'] = 3600

    result = await TenantScopeService.get_scope(user_id=42)

    assert result['scope_tenant_id'] == 5
    assert result['expires_at'] is not None
    # ISO format sanity check — contains date separator and timezone.
    assert 'T' in result['expires_at']
    assert result['expires_at'].endswith('+00:00')


# ---------------------------------------------------------------------------
# hooks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clear_on_logout_deletes_key(all_mocks):
    """AC-10 method body: logout hook removes the scope key."""
    from bisheng.admin.domain.services.tenant_scope import TenantScopeService
    all_mocks.redis.store['admin_scope:42'] = '5'

    await TenantScopeService.clear_on_logout(user_id=42)

    assert 'admin_scope:42' not in all_mocks.redis.store
    # clear_on_logout must NOT write an audit row (logout itself is audited
    # elsewhere; a scope DEL on logout is bookkeeping, not an operator action).
    all_mocks.audit.ainsert_v2.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_hooks_all_delegate_to_same_del(all_mocks):
    """AC-11/12 method bodies: token_version_bump and role_revoke hooks
    share the same DEL path as logout — single source of truth."""
    from bisheng.admin.domain.services.tenant_scope import TenantScopeService
    all_mocks.redis.store['admin_scope:42'] = '5'
    await TenantScopeService.clear_on_token_version_bump(user_id=42)
    assert 'admin_scope:42' not in all_mocks.redis.store

    all_mocks.redis.store['admin_scope:42'] = '7'
    await TenantScopeService.clear_on_role_revoke(user_id=42)
    assert 'admin_scope:42' not in all_mocks.redis.store
