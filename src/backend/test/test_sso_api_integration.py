"""Integration tests for the F014 API routes.

Mounts the ``sso_sync_router`` directly on a minimal FastAPI app so each
test verifies:
- Route registration (POST /api/v1/internal/sso/login-sync + /departments/sync)
- HMAC dependency wiring (401 + 19301 without a valid signature)
- Service-layer call-through (LoginSyncService / DepartmentsSyncService
  receive the parsed payload).

Both services are patched with ``AsyncMock`` so the integration test
stays in-process with no DB / Redis / FGA dependencies. The other
suites (``test_sso_login_sync_service.py`` etc.) exercise the internal
logic of those services.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter, FastAPI
from starlette.testclient import TestClient

pytest_plugins = ['test.fixtures.sso_sync']


LOGIN_SYNC_PATH = '/api/v1/internal/sso/login-sync'
DEPTS_SYNC_PATH = '/api/v1/departments/sync'


def _mount_app() -> FastAPI:
    from bisheng.sso_sync.api.router import router as sso_sync_router

    app = FastAPI()
    api = APIRouter(prefix='/api/v1')
    api.include_router(sso_sync_router)
    app.include_router(api)
    return app


# =========================================================================
# Service-layer mocks (shared across tests)
# =========================================================================

@pytest.fixture()
def mocked_services(monkeypatch):
    """Patch service + writer calls at the endpoints import site so we
    only test the HTTP / dependency plumbing."""
    import bisheng.sso_sync.api.endpoints.login_sync as login_ep
    import bisheng.sso_sync.api.endpoints.departments_sync as depts_ep

    login_result = SimpleNamespace(
        user_id=7, leaf_tenant_id=15, token='jwt-token',
    )
    # LoginSyncResponse is a Pydantic model — build a real one so resp_200
    # serialisation works cleanly.
    from bisheng.sso_sync.domain.schemas.payloads import (
        BatchResult, LoginSyncResponse,
    )

    login_service = AsyncMock(
        return_value=LoginSyncResponse(
            user_id=7, leaf_tenant_id=15, token='jwt-token',
        ),
    )
    depts_service = AsyncMock(
        return_value=BatchResult(applied_upsert=2, applied_remove=1),
    )
    flush = AsyncMock(return_value=None)

    monkeypatch.setattr(login_ep.LoginSyncService, 'execute', login_service)
    monkeypatch.setattr(login_ep, 'flush_log', flush)
    monkeypatch.setattr(
        depts_ep.DepartmentsSyncService, 'execute', depts_service,
    )
    monkeypatch.setattr(depts_ep, 'flush_log', flush)

    return SimpleNamespace(
        login=login_service, depts=depts_service, flush=flush,
        login_result=login_result,
    )


# =========================================================================
# Happy-path route tests (HMAC valid → service receives payload)
# =========================================================================

class TestLoginSyncRoute:

    def test_valid_signature_invokes_service(
        self, configure_sso_secret, hmac_signer, mocked_services,
    ):
        app = _mount_app()
        body = (
            b'{"external_user_id":"u1",'
            b'"primary_dept_external_id":"D1",'
            b'"user_attrs":{"name":"Alice"},'
            b'"ts":1000}'
        )
        sig = hmac_signer('POST', LOGIN_SYNC_PATH, body)
        with TestClient(app) as client:
            resp = client.post(
                LOGIN_SYNC_PATH,
                content=body,
                headers={
                    'X-Signature': sig,
                    'Content-Type': 'application/json',
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data['data'] == {
            'user_id': 7, 'leaf_tenant_id': 15, 'token': 'jwt-token',
        }
        mocked_services.login.assert_awaited_once()
        payload = mocked_services.login.await_args.args[0]
        assert payload.external_user_id == 'u1'
        assert payload.ts == 1000

    def test_invalid_signature_rejected(
        self, configure_sso_secret, mocked_services,
    ):
        app = _mount_app()
        with TestClient(app) as client:
            resp = client.post(
                LOGIN_SYNC_PATH,
                json={'external_user_id': 'u1', 'ts': 1000},
                headers={'X-Signature': 'deadbeef'},
            )
        assert resp.status_code == 19301
        mocked_services.login.assert_not_awaited()


class TestDepartmentsSyncRoute:

    def test_valid_signature_invokes_service(
        self, configure_sso_secret, hmac_signer, mocked_services,
    ):
        app = _mount_app()
        body = (
            b'{"upsert":[{"external_id":"D1","name":"Eng","ts":10}],'
            b'"remove":["D99"],"source_ts":100}'
        )
        sig = hmac_signer('POST', DEPTS_SYNC_PATH, body)
        with TestClient(app) as client:
            resp = client.post(
                DEPTS_SYNC_PATH,
                content=body,
                headers={
                    'X-Signature': sig,
                    'Content-Type': 'application/json',
                },
            )
        assert resp.status_code == 200
        data = resp.json()['data']
        assert data['applied_upsert'] == 2
        assert data['applied_remove'] == 1
        mocked_services.depts.assert_awaited_once()
        payload = mocked_services.depts.await_args.args[0]
        assert len(payload.upsert) == 1
        assert payload.remove == ['D99']

    def test_missing_signature_rejected(
        self, configure_sso_secret, mocked_services,
    ):
        app = _mount_app()
        with TestClient(app) as client:
            resp = client.post(
                DEPTS_SYNC_PATH,
                json={'upsert': [], 'remove': []},
            )
        assert resp.status_code == 19301
        mocked_services.depts.assert_not_awaited()


class TestExemptPathWhitelist:

    def test_paths_are_in_tenant_check_exempt_list(self):
        """Regression guard: both routes MUST be whitelisted or the main
        tenant-context middleware will try to parse JWT and 401 before
        our HMAC dependency even runs."""
        from bisheng.utils.http_middleware import TENANT_CHECK_EXEMPT_PATHS
        assert LOGIN_SYNC_PATH in TENANT_CHECK_EXEMPT_PATHS
        assert DEPTS_SYNC_PATH in TENANT_CHECK_EXEMPT_PATHS
