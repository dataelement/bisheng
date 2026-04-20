"""F019 T08 — logout wiring: verify ``/user/logout`` clears admin-scope.

Two cases:
  - AC-10 happy path: authenticated logout → ``clear_on_logout`` is
    awaited exactly once with the user's id before the JWT cookie is
    unset.
  - Degraded path: no JWT cookie / decode failure → the handler must
    still unset the cookie and return 200 (no 500), and the scope
    clear must be a no-op rather than raising.

We drive the handler directly (not via TestClient) to keep the blast
radius small: the full auth machinery (AuthJwt cookie handling) would
drag in more than we want for a wiring test.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


ENDPOINT_MOD = 'bisheng.user.api.user'


def _make_auth_jwt(subject):
    """Build a MagicMock AuthJwt whose ``get_subject`` returns ``subject``
    (or raises RuntimeError if ``subject`` is the string ``'raise'``)."""
    auth = MagicMock()
    if subject == 'raise':
        auth.get_subject = MagicMock(side_effect=RuntimeError('bad token'))
    else:
        auth.get_subject = MagicMock(return_value=subject)
    auth.unset_access_token = MagicMock()
    return auth


def test_logout_clears_scope_for_authenticated_user(monkeypatch):
    """AC-10: logout with a valid JWT → scope cleared, cookie unset."""
    import importlib
    mod = importlib.import_module(ENDPOINT_MOD)

    clear_mock = AsyncMock()
    # Patch the service via sys.modules so the late import inside logout()
    # resolves to our mock.
    import sys
    fake_ts_mod = MagicMock()
    fake_ts_mod.TenantScopeService = MagicMock()
    fake_ts_mod.TenantScopeService.clear_on_logout = clear_mock
    sys.modules['bisheng.admin.domain.services.tenant_scope'] = fake_ts_mod

    auth_jwt = _make_auth_jwt({'user_id': 42, 'user_name': 'super'})

    result = asyncio.run(mod.logout(auth_jwt=auth_jwt))

    clear_mock.assert_awaited_once_with(42)
    auth_jwt.unset_access_token.assert_called_once()
    # resp_200 returns a UnifiedResponseModel with status_code=200.
    assert getattr(result, 'status_code', None) == 200


def test_logout_handles_bad_token_gracefully(monkeypatch):
    """Decode failure must NOT 500 — cookie still unset, scope call skipped."""
    import importlib
    mod = importlib.import_module(ENDPOINT_MOD)

    clear_mock = AsyncMock()
    import sys
    fake_ts_mod = MagicMock()
    fake_ts_mod.TenantScopeService = MagicMock()
    fake_ts_mod.TenantScopeService.clear_on_logout = clear_mock
    sys.modules['bisheng.admin.domain.services.tenant_scope'] = fake_ts_mod

    auth_jwt = _make_auth_jwt('raise')

    result = asyncio.run(mod.logout(auth_jwt=auth_jwt))

    clear_mock.assert_not_awaited()
    auth_jwt.unset_access_token.assert_called_once()
    assert getattr(result, 'status_code', None) == 200
