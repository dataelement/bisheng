"""Tests for F012 CustomMiddleware enhancements.

Focuses on the two new responsibilities layered into CustomMiddleware:

1. ``token_version`` validation (AC-09) — JWT payload vs DB; 401 on
   mismatch.
2. ``visible_tenant_ids`` computation — frozenset shaped by tenant_id +
   is_global_super.

The full middleware stack (trace_id, request logging) is out of scope
here; we test the pure functions (`_validate_token_version`,
`_compute_visible_tenant_ids`, `_apply_token_version_and_visible`).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.utils import http_middleware as hm


# -------------------------------------------------------------------------
# _compute_visible_tenant_ids
# -------------------------------------------------------------------------

class TestComputeVisibleTenantIds:

    def test_super_admin_returns_none(self):
        assert hm._compute_visible_tenant_ids(5, is_global_super=True) is None

    def test_root_user_returns_root_only(self):
        assert hm._compute_visible_tenant_ids(1, is_global_super=False) == frozenset({1})

    def test_child_user_returns_leaf_and_root(self):
        assert hm._compute_visible_tenant_ids(7, is_global_super=False) == frozenset({7, 1})

    def test_pending_tenant_returns_empty_set(self):
        assert hm._compute_visible_tenant_ids(0, is_global_super=False) == frozenset()

    def test_negative_tenant_returns_empty_set(self):
        # Defensive — not a normal code path, but verify we never leak.
        assert hm._compute_visible_tenant_ids(-1, is_global_super=False) == frozenset()


# -------------------------------------------------------------------------
# _validate_token_version
# -------------------------------------------------------------------------

def _swap_user_dao(aget_token_version_mock):
    """Install a stub UserDao with an AsyncMock ``aget_token_version``.

    ``bisheng.user.domain.models.user`` is pre-mocked by conftest, so we
    poke into the existing MagicMock via sys.modules instead of importing
    it (which would trigger a real import and fail).
    """
    import sys
    user_mod = sys.modules.get('bisheng.user.domain.models.user')
    if user_mod is None:
        user_mod = MagicMock()
        sys.modules['bisheng.user.domain.models.user'] = user_mod
    stub_dao = MagicMock()
    stub_dao.aget_token_version = aget_token_version_mock
    user_mod.UserDao = stub_dao
    return stub_dao


class TestValidateTokenVersion:

    def test_match_returns_true(self):
        _swap_user_dao(AsyncMock(return_value=5))
        result = asyncio.run(hm._validate_token_version(100, 5))
        assert result is True

    def test_mismatch_returns_false(self):
        _swap_user_dao(AsyncMock(return_value=3))
        result = asyncio.run(hm._validate_token_version(100, 5))
        assert result is False

    def test_dao_error_fails_open(self):
        """Don't lock out users on infra failures — fail open."""
        _swap_user_dao(AsyncMock(side_effect=RuntimeError('db down')))
        result = asyncio.run(hm._validate_token_version(100, 5))
        assert result is True

    def test_no_user_id_returns_true(self):
        """Anonymous / malformed payload — pass through to downstream auth."""
        result = asyncio.run(hm._validate_token_version(0, 0))
        assert result is True


# -------------------------------------------------------------------------
# _apply_token_version_and_visible (integration-style, using a fake token)
# -------------------------------------------------------------------------

class TestApplyTokenVersionAndVisible:

    def _build_request(self):
        """Build a minimal FastAPI-style Request stub."""
        from starlette.requests import Request
        scope = {
            'type': 'http', 'method': 'GET', 'path': '/foo',
            'headers': [], 'query_string': b'',
        }
        return Request(scope)

    def _patch_subject(self, monkeypatch, subject):
        monkeypatch.setattr(hm, '_decode_jwt_subject', lambda token: subject)

    def test_mismatch_returns_401(self, monkeypatch):
        self._patch_subject(monkeypatch, {
            'user_id': 100, 'user_name': 'a', 'tenant_id': 5, 'token_version': 1,
        })
        async def _fake_validate(uid, tv):
            return False
        monkeypatch.setattr(hm, '_validate_token_version', _fake_validate)

        async def _run():
            return await hm._apply_token_version_and_visible(
                self._build_request(), 'fake-token',
            )
        result = asyncio.run(_run())
        assert result is not None
        assert result.status_code == 401

    def test_match_sets_visible_for_child_user(self, monkeypatch):
        """ContextVar mutations inside asyncio.run() don't escape the new
        event loop context, so we read get_visible_tenant_ids() INSIDE the
        coroutine to observe the ContextVar before the loop tears down.
        """
        self._patch_subject(monkeypatch, {
            'user_id': 100, 'user_name': 'a', 'tenant_id': 5, 'token_version': 3,
        })
        async def _fake_validate(uid, tv):
            return True
        async def _fake_is_super(uid):
            return False
        monkeypatch.setattr(hm, '_validate_token_version', _fake_validate)
        monkeypatch.setattr(hm, '_check_is_global_super', _fake_is_super)

        async def _run():
            result = await hm._apply_token_version_and_visible(
                self._build_request(), 'fake-token',
            )
            from bisheng.core.context.tenant import get_visible_tenant_ids
            return result, get_visible_tenant_ids()

        result, visible = asyncio.run(_run())
        assert result is None
        assert visible == frozenset({5, 1})

    def test_match_sets_visible_none_for_super(self, monkeypatch):
        self._patch_subject(monkeypatch, {
            'user_id': 100, 'user_name': 'a', 'tenant_id': 1, 'token_version': 0,
        })
        async def _fake_validate(uid, tv):
            return True
        async def _fake_is_super(uid):
            return True
        monkeypatch.setattr(hm, '_validate_token_version', _fake_validate)
        monkeypatch.setattr(hm, '_check_is_global_super', _fake_is_super)

        async def _run():
            result = await hm._apply_token_version_and_visible(
                self._build_request(), 'fake-token',
            )
            from bisheng.core.context.tenant import get_visible_tenant_ids
            return result, get_visible_tenant_ids()

        result, visible = asyncio.run(_run())
        assert result is None
        assert visible is None

    def test_undecodable_token_noops(self, monkeypatch):
        """Bad JWT — return None (fall through to legacy logic)."""
        monkeypatch.setattr(hm, '_decode_jwt_subject', lambda t: None)
        async def _run():
            return await hm._apply_token_version_and_visible(
                self._build_request(), 'bad-token',
            )
        assert asyncio.run(_run()) is None
