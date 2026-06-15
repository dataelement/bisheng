"""F019-admin-tenant-scope middleware tests.

Verifies:
  - Non-management paths take the fast path (AC-07) — no JWT decode, no
    Redis read, no FGA check.
  - Management paths with a super-admin JWT read Redis, set the
    ``_admin_scope_tenant_id`` ContextVar, and refresh TTL.
  - Non-super callers never have scope injected, even if a stale Redis
    key exists (AC-12 eventual-consistency safety net).
  - Corrupt Redis values and Redis outages fail open — no 500 to the user.

Strategy: mount the middleware on a tiny FastAPI app that echoes the
resulting ContextVars back to the response body. Patch
``_check_is_global_super``, ``_decode_jwt_subject`` and
``get_redis_client`` inside the middleware module.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from bisheng.core.context.tenant import (
    get_admin_scope_tenant_id,
    get_is_management_api,
)


MIDDLEWARE_MOD = 'bisheng.common.middleware.admin_scope'


# ---------------------------------------------------------------------------
# Fake Redis (mirrors RedisClient async surface used by the middleware)
# ---------------------------------------------------------------------------

class _FakeRedis:
    def __init__(self):
        self.store: Dict[str, str] = {}
        self.ttls: Dict[str, int] = {}
        self.expire_calls: list[tuple[str, int]] = []
        self.raise_on_aget: bool = False

    async def aget(self, key: str):
        if self.raise_on_aget:
            raise RuntimeError('redis down')
        return self.store.get(key)

    async def aexpire_key(self, key: str, expiration: int):
        self.ttls[key] = expiration
        self.expire_calls.append((key, expiration))


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _build_app():
    """Minimal app with AdminScopeMiddleware + a diagnostic echo route."""
    from bisheng.common.middleware.admin_scope import AdminScopeMiddleware

    app = FastAPI()
    app.add_middleware(AdminScopeMiddleware)

    @app.get('/api/v1/llm')
    def _llm_echo():
        return {
            'scope': get_admin_scope_tenant_id(),
            'is_mgmt': get_is_management_api(),
        }

    @app.get('/api/v1/chat/x')
    def _chat_echo():
        return {
            'scope': get_admin_scope_tenant_id(),
            'is_mgmt': get_is_management_api(),
        }

    @app.get('/api/v1/admin/tenant-scope')
    def _admin_echo():
        return {
            'scope': get_admin_scope_tenant_id(),
            'is_mgmt': get_is_management_api(),
        }

    return app


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_redis(monkeypatch):
    r = _FakeRedis()

    async def _get_client():
        return r

    monkeypatch.setattr(f'{MIDDLEWARE_MOD}.get_redis_client', _get_client)
    return r


@pytest.fixture()
def fake_settings(monkeypatch):
    s = SimpleNamespace(multi_tenant=SimpleNamespace(admin_scope_ttl_seconds=14400))
    monkeypatch.setattr(f'{MIDDLEWARE_MOD}.settings', s)
    return s


def _patch_jwt(monkeypatch, subject: Optional[Dict[str, Any]]):
    """Stub ``_decode_jwt_subject`` with a canned payload."""
    monkeypatch.setattr(f'{MIDDLEWARE_MOD}._decode_jwt_subject', lambda token: subject)


def _patch_super(monkeypatch, is_super: bool, raise_exc: bool = False):
    async def _check(user_id):
        if raise_exc:
            raise RuntimeError('fga down')
        return is_super

    monkeypatch.setattr(f'{MIDDLEWARE_MOD}._check_is_global_super', _check)


def _client_with_cookie(app):
    client = TestClient(app)
    # Any non-empty cookie string works — the middleware patches decoding.
    client.cookies.set('access_token_cookie', 'fake-jwt')
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestManagementApiDetection:

    def test_non_mgmt_path_marks_is_management_false(self, monkeypatch, fake_redis, fake_settings):
        """AC-07 + fast path: ``/api/v1/chat`` is NOT management — no scope,
        no Redis read, is_management_api=False."""
        _patch_jwt(monkeypatch, {'user_id': 1})
        _patch_super(monkeypatch, True)
        fake_redis.store['admin_scope:1'] = '5'  # Would be read on mgmt path.

        app = _build_app()
        client = _client_with_cookie(app)
        resp = client.get('/api/v1/chat/x')
        assert resp.status_code == 200
        body = resp.json()
        assert body['scope'] is None       # Business API ignores scope.
        assert body['is_mgmt'] is False
        assert fake_redis.expire_calls == []

    def test_mgmt_path_marks_is_management_true(self, monkeypatch, fake_redis, fake_settings):
        _patch_jwt(monkeypatch, {'user_id': 1})
        _patch_super(monkeypatch, True)
        app = _build_app()
        client = _client_with_cookie(app)
        resp = client.get('/api/v1/llm')
        assert resp.status_code == 200
        assert resp.json()['is_mgmt'] is True


class TestScopeInjection:

    def test_super_admin_with_scope_key_injects_and_refreshes_ttl(
        self, monkeypatch, fake_redis, fake_settings,
    ):
        """AC-06 + AC-08: mgmt path + super admin + Redis has value → scope
        ContextVar set; TTL refreshed to settings-configured value."""
        _patch_jwt(monkeypatch, {'user_id': 1})
        _patch_super(monkeypatch, True)
        fake_redis.store['admin_scope:1'] = '5'

        app = _build_app()
        client = _client_with_cookie(app)
        resp = client.get('/api/v1/llm')
        assert resp.status_code == 200
        assert resp.json()['scope'] == 5
        assert fake_redis.expire_calls == [('admin_scope:1', 14400)]

    def test_super_admin_without_scope_key_leaves_context_none(
        self, monkeypatch, fake_redis, fake_settings,
    ):
        """AC-09: Redis key missing (either never set OR TTL-expired — both
        look the same to GET) → ContextVar stays None, no TTL refresh."""
        _patch_jwt(monkeypatch, {'user_id': 1})
        _patch_super(monkeypatch, True)

        app = _build_app()
        client = _client_with_cookie(app)
        resp = client.get('/api/v1/llm')
        assert resp.status_code == 200
        assert resp.json()['scope'] is None
        assert fake_redis.expire_calls == []

    def test_non_super_never_injects_even_with_stale_key(
        self, monkeypatch, fake_redis, fake_settings,
    ):
        """AC-12 safety net: a stale Redis key for a user who lost super
        must NOT inject a scope. Fail-closed."""
        _patch_jwt(monkeypatch, {'user_id': 10})
        _patch_super(monkeypatch, False)
        fake_redis.store['admin_scope:10'] = '5'

        app = _build_app()
        client = _client_with_cookie(app)
        resp = client.get('/api/v1/llm')
        assert resp.status_code == 200
        assert resp.json()['scope'] is None
        # TTL is NOT refreshed for non-supers — Celery sweep will clean up.
        assert fake_redis.expire_calls == []


class TestRobustness:

    def test_no_jwt_cookie_passes_through(self, monkeypatch, fake_redis, fake_settings):
        """Unauthenticated mgmt call — middleware doesn't 500, just noops."""
        _patch_jwt(monkeypatch, None)
        _patch_super(monkeypatch, False)
        app = _build_app()
        client = TestClient(app)  # no cookie
        resp = client.get('/api/v1/llm')
        assert resp.status_code == 200
        assert resp.json()['scope'] is None

    def test_corrupt_redis_value_does_not_500(
        self, monkeypatch, fake_redis, fake_settings,
    ):
        """Non-numeric value in Redis → skip injection, don't blow up."""
        _patch_jwt(monkeypatch, {'user_id': 1})
        _patch_super(monkeypatch, True)
        fake_redis.store['admin_scope:1'] = 'oops-not-an-int'

        app = _build_app()
        client = _client_with_cookie(app)
        resp = client.get('/api/v1/llm')
        assert resp.status_code == 200
        assert resp.json()['scope'] is None

    def test_redis_outage_fails_open(
        self, monkeypatch, fake_redis, fake_settings,
    ):
        """Redis GET raises → request proceeds without scope, no 5xx."""
        _patch_jwt(monkeypatch, {'user_id': 1})
        _patch_super(monkeypatch, True)
        fake_redis.raise_on_aget = True

        app = _build_app()
        client = _client_with_cookie(app)
        resp = client.get('/api/v1/llm')
        assert resp.status_code == 200
        assert resp.json()['scope'] is None
