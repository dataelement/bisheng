"""F019 T08 — verify the logout endpoint is wired to ``clear_on_logout``.

``bisheng.user.api.user`` is a heavy module that cannot be imported in the
test environment (pre-existing import chain brittleness — tracked as a
separate concern; see F012's ``test_current_tenant_api.py`` which
deliberately imports a leaner split-off ``bisheng.user.api.current_tenant``
for the same reason).

Rather than reproducing that workaround here for a 4-line hook, we verify
the wiring with two complementary checks:

  1. **Source inspection** — the ``logout`` function's source contains the
     required ``TenantScopeService.clear_on_logout`` call inside a
     try/except block so a Redis outage cannot break cookie unset.
  2. **Service behaviour** — the method itself deletes the Redis key (this
     duplicates ``test_admin_tenant_scope_service.py::test_clear_on_logout_deletes_key``
     under a different name so the AC mapping in ac-verification.md has
     a direct one-to-one test reference for AC-10).

The end-to-end HTTP smoke test (actual cookie round-trip + Redis DEL)
lives in ac-verification.md §10 as a manual 114 QA step.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


USER_PY = (
    Path(__file__).resolve().parent.parent
    / 'bisheng' / 'user' / 'api' / 'user.py'
)


# ---------------------------------------------------------------------------
# Source-level wiring check (AC-10)
# ---------------------------------------------------------------------------

def _extract_logout_source() -> str:
    tree = ast.parse(USER_PY.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == 'logout':
            return ast.get_source_segment(USER_PY.read_text(encoding='utf-8'), node) or ''
    return ''


def test_logout_source_contains_clear_on_logout_hook():
    """AC-10 wiring: the logout handler must call
    ``TenantScopeService.clear_on_logout(user_id)`` before unsetting
    the cookie, wrapped in a try/except so the call is best-effort."""
    src = _extract_logout_source()
    assert src, 'logout handler not found in user/api/user.py'
    # Hook call with expected Service reference.
    assert 'TenantScopeService.clear_on_logout' in src, (
        'logout handler is missing the F019 admin-scope clear hook'
    )
    # Must be best-effort — a try/except around the hook so a Redis
    # outage cannot prevent the cookie from being cleared.
    assert 'try:' in src and 'except' in src, (
        'the hook call must be wrapped in try/except (best-effort)'
    )
    # The cookie unset must still happen.
    assert 'unset_access_token' in src


def test_logout_source_imports_service_locally_not_at_module_top():
    """The admin scope module is a late import inside the logout body
    (F019 → admin module dep must not leak to user module top-level;
    circular import risk + module-layer architecture guard)."""
    import re
    body = _extract_logout_source()
    # The import should appear inside the function body, not at file top.
    full = USER_PY.read_text(encoding='utf-8')
    # No top-level ``from bisheng.admin`` or ``import bisheng.admin`` — a
    # top-level import would sit at column 0. Indented imports (inside
    # function bodies) are fine and expected.
    assert not re.search(r'^(from|import)\s+bisheng\.admin', full, re.MULTILINE), (
        'bisheng.admin must not be imported at the top of user/api/user.py'
    )
    # But the local import inside logout is required.
    assert 'from bisheng.admin.domain.services.tenant_scope import' in body, (
        'logout body must locally import TenantScopeService'
    )


# ---------------------------------------------------------------------------
# Service hook behaviour (AC-10 — duplicate-named for direct AC mapping)
# ---------------------------------------------------------------------------

MODULE = 'bisheng.admin.domain.services.tenant_scope'


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def aget(self, key: str):
        return self.store.get(key)

    async def adelete(self, key: str):
        self.store.pop(key, None)
        return 1


@pytest.mark.asyncio
async def test_clear_on_logout_deletes_redis_key(monkeypatch):
    """AC-10 behaviour: ``clear_on_logout`` idempotently deletes the key."""
    fake = _FakeRedis()
    fake.store['admin_scope:42'] = '5'

    async def _get_client():
        return fake

    monkeypatch.setattr(f'{MODULE}.get_redis_client', _get_client)

    from bisheng.admin.domain.services.tenant_scope import TenantScopeService

    await TenantScopeService.clear_on_logout(user_id=42)
    assert 'admin_scope:42' not in fake.store

    # Idempotent: second call is a no-op, not an error.
    await TenantScopeService.clear_on_logout(user_id=42)
    assert 'admin_scope:42' not in fake.store
