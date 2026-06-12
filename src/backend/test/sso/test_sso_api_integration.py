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
GATEWAY_WECOM_ORG_SYNC_PATH = '/api/v1/internal/sso/gateway-wecom-org-sync'


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
    import bisheng.sso_sync.api.endpoints.gateway_wecom_org_sync as wecom_ep

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
    monkeypatch.setattr(
        wecom_ep.DepartmentsSyncService, 'execute', depts_service,
    )
    monkeypatch.setattr(
        wecom_ep.LoginSyncService, 'execute', login_service,
    )
    monkeypatch.setattr(
        wecom_ep, 'disable_wecom_users_absent_from_import',
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(wecom_ep, 'flush_log', flush)
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
        assert mocked_services.login.await_args.kwargs['row_source'] == 'wecom'

    def test_explicit_source_is_forwarded_to_service(
        self, configure_sso_secret, hmac_signer, mocked_services,
    ):
        app = _mount_app()
        body = (
            b'{"source":"wecom","external_user_id":"u1",'
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
        assert mocked_services.login.await_args.kwargs['row_source'] == 'wecom'

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
        assert mocked_services.depts.await_args.kwargs['row_source'] == 'wecom'
        assert len(payload.upsert) == 1
        assert payload.remove == ['D99']

    def test_explicit_source_is_forwarded_to_service(
        self, configure_sso_secret, hmac_signer, mocked_services,
    ):
        app = _mount_app()
        body = (
            b'{"source":"sso","upsert":[{"external_id":"D1","name":"Eng","ts":10}],'
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
        assert mocked_services.depts.await_args.kwargs['row_source'] == 'sso'

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


class TestGatewayWecomOrgSyncRoute:

    def test_missing_secondary_depts_normalized_to_empty_list(
        self, configure_sso_secret, hmac_signer, mocked_services,
    ):
        """Gateway WeCom full sync is authoritative.

        Older gateway builds omitted ``secondary_dept_external_ids`` for users
        with only one department. The endpoint must normalize that omission to
        [] so LoginSyncService reconciles and removes stale secondary rows.
        """
        app = _mount_app()
        body = (
            b'{"departments":{"upsert":[{"external_id":"D1","name":"Main"}],'
            b'"remove":[]},"members":[{"external_user_id":"yangxin",'
            b'"primary_dept_external_id":"D1","user_attrs":{"name":"Yang"},'
            b'"ts":1000}]}'
        )
        sig = hmac_signer('POST', GATEWAY_WECOM_ORG_SYNC_PATH, body)
        with TestClient(app) as client:
            resp = client.post(
                GATEWAY_WECOM_ORG_SYNC_PATH,
                content=body,
                headers={
                    'X-Signature': sig,
                    'Content-Type': 'application/json',
                },
            )

        assert resp.status_code == 200
        mocked_services.login.assert_awaited_once()
        member_payload = mocked_services.login.await_args.args[0]
        assert member_payload.secondary_dept_external_ids == []
        assert 'secondary_dept_external_ids' in member_payload.model_fields_set

    def test_incremental_batch_skips_user_absent_reconcile(
        self, configure_sso_secret, hmac_signer, mocked_services,
    ):
        """Batched Gateway push: an incremental envelope (``full_snapshot``
        omitted / false) must NOT trigger user absent reconcile. Otherwise
        each chunk would disable every wecom user outside the chunk."""
        import bisheng.sso_sync.api.endpoints.gateway_wecom_org_sync as wecom_ep

        app = _mount_app()
        body = (
            b'{"departments":{"upsert":[{"external_id":"D1","name":"Main"}],'
            b'"remove":[]},"members":[{"external_user_id":"u1",'
            b'"primary_dept_external_id":"D1","user_attrs":{"name":"X"},'
            b'"ts":1000}]}'
        )
        sig = hmac_signer('POST', GATEWAY_WECOM_ORG_SYNC_PATH, body)
        with TestClient(app) as client:
            resp = client.post(
                GATEWAY_WECOM_ORG_SYNC_PATH,
                content=body,
                headers={
                    'X-Signature': sig,
                    'Content-Type': 'application/json',
                },
            )

        assert resp.status_code == 200
        wecom_ep.disable_wecom_users_absent_from_import.assert_not_awaited()
        # Department absent reconcile is gated inside DepartmentsSyncService
        # by the same flag; verify the service received the caller's value
        # (false) rather than a forced True.
        dept_payload = mocked_services.depts.await_args.args[0]
        assert dept_payload.full_snapshot is False

    def test_full_snapshot_batch_triggers_user_absent_reconcile(
        self, configure_sso_secret, hmac_signer, mocked_services,
    ):
        """The authoritative final envelope (``full_snapshot=true``) must
        invoke ``disable_wecom_users_absent_from_import`` with the union of
        external ids present in the batch, and forward full_snapshot to the
        departments service for archival of absent dept rows."""
        import bisheng.sso_sync.api.endpoints.gateway_wecom_org_sync as wecom_ep

        app = _mount_app()
        body = (
            b'{"departments":{"upsert":[{"external_id":"D1","name":"Main"}],'
            b'"remove":[],"full_snapshot":true,'
            b'"snapshot_external_ids":["D1"]},'
            b'"members":[{"external_user_id":"u1",'
            b'"primary_dept_external_id":"D1","user_attrs":{"name":"X"},'
            b'"ts":1000}]}'
        )
        sig = hmac_signer('POST', GATEWAY_WECOM_ORG_SYNC_PATH, body)
        with TestClient(app) as client:
            resp = client.post(
                GATEWAY_WECOM_ORG_SYNC_PATH,
                content=body,
                headers={
                    'X-Signature': sig,
                    'Content-Type': 'application/json',
                },
            )

        assert resp.status_code == 200
        wecom_ep.disable_wecom_users_absent_from_import.assert_awaited_once()
        seen = wecom_ep.disable_wecom_users_absent_from_import.await_args.args[0]
        assert seen == {'u1'}
        dept_payload = mocked_services.depts.await_args.args[0]
        assert dept_payload.full_snapshot is True


class TestExemptPathWhitelist:

    def test_paths_are_in_tenant_check_exempt_list(self):
        """Regression guard: both routes MUST be whitelisted or the main
        tenant-context middleware will try to parse JWT and 401 before
        our HMAC dependency even runs."""
        from bisheng.utils.http_middleware import TENANT_CHECK_EXEMPT_PATHS
        assert LOGIN_SYNC_PATH in TENANT_CHECK_EXEMPT_PATHS
        assert DEPTS_SYNC_PATH in TENANT_CHECK_EXEMPT_PATHS
        assert GATEWAY_WECOM_ORG_SYNC_PATH in TENANT_CHECK_EXEMPT_PATHS
