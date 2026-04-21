"""Tests for F012 GET /api/v1/user/current-tenant endpoint (AC-10, AC-11).

Rather than spinning up the full FastAPI app (heavy startup chain), we
invoke the endpoint function directly with mocked collaborators. AC-11
(POST /user/switch-tenant → 410) was delivered by F011 T07; we re-assert
its handler still returns 410 here for regression coverage.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# -------------------------------------------------------------------------
# Direct endpoint invocation
# -------------------------------------------------------------------------

def _login_user(user_id=100):
    return SimpleNamespace(
        user_id=user_id, user_name='u', user_role=[],
        tenant_id=1, token_version=0, is_admin=lambda: False,
    )


def _tenant(tid, parent_tenant_id=None):
    return SimpleNamespace(
        id=tid, tenant_code=f't{tid}', tenant_name=f'T{tid}',
        parent_tenant_id=parent_tenant_id,
        status='active', share_default_to_children=True,
    )


class TestCurrentTenantHandler:

    def test_root_user_is_child_false(self):
        """When leaf tenant_id == Root, is_child=False and mounted dept None."""
        with patch(
            'bisheng.tenant.domain.services.tenant_resolver.TenantResolver.resolve_user_leaf_tenant',
            new=AsyncMock(return_value=_tenant(1, parent_tenant_id=None)),
        ):
            from bisheng.user.api.current_tenant import get_current_tenant_handler

            result = asyncio.run(get_current_tenant_handler(_login_user(100)))

        payload = result.data
        assert payload['leaf_tenant_id'] == 1
        assert payload['is_child'] is False
        assert payload['mounted_department_id'] is None
        assert payload['root_tenant_id'] == 1

    def test_child_user_reports_mounted_dept(self, monkeypatch):
        """Child leaf → is_child=True; mounted_department_id from DB."""
        from contextlib import asynccontextmanager

        class _FakeResult:
            def first(self):
                return 42  # department.id

        class _FakeSession:
            async def exec(self, stmt):
                return _FakeResult()

        @asynccontextmanager
        async def _fake_session():
            yield _FakeSession()

        with patch(
            'bisheng.tenant.domain.services.tenant_resolver.TenantResolver.resolve_user_leaf_tenant',
            new=AsyncMock(return_value=_tenant(5, parent_tenant_id=1)),
        ), patch(
            'bisheng.user.api.current_tenant.get_async_db_session', _fake_session,
        ):
            from bisheng.user.api.current_tenant import get_current_tenant_handler
            result = asyncio.run(get_current_tenant_handler(_login_user(200)))

        payload = result.data
        assert payload['leaf_tenant_id'] == 5
        assert payload['is_child'] is True
        assert payload['mounted_department_id'] == 42
        assert payload['root_tenant_id'] == 1


# -------------------------------------------------------------------------
# AC-11 regression: POST /user/switch-tenant still returns 410.
# -------------------------------------------------------------------------

class TestSwitchTenantDeprecated:

    def test_switch_tenant_returns_410(self):
        """The F011 T07 410 Gone handler is still in place."""
        from bisheng.tenant.api.endpoints.user_tenant import (
            switch_tenant_deprecated,
        )
        response = asyncio.run(switch_tenant_deprecated())
        assert response.status_code == 410
        # Body should contain the deprecation explanation.
        body_bytes = response.body
        assert b'410 Gone' in body_bytes or b'primary department' in body_bytes.lower()
