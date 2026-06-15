"""Integration tests for the F015 relink HTTP endpoints.

Mounts ``relink_router`` on a minimal FastAPI app; service calls are
monkeypatched so we only verify:

- Route registration (POST /api/v1/internal/departments/relink and
  /relink/resolve-conflict).
- HMAC dependency wiring (rejected without a valid signature).
- Payload → service arg plumbing.

The service logic itself is covered by ``test_department_relink_service.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, FastAPI
from starlette.testclient import TestClient

pytest_plugins = ['test.fixtures.sso_sync']


RELINK_PATH = '/api/v1/internal/departments/relink'
RESOLVE_PATH = '/api/v1/internal/departments/relink/resolve-conflict'


def _mount_app() -> FastAPI:
    from bisheng.org_sync.api.endpoints.relink import router as relink_router

    app = FastAPI()
    api = APIRouter(prefix='/api/v1')
    api.include_router(relink_router)
    app.include_router(api)
    return app


@pytest.fixture()
def mocked_service(monkeypatch):
    """Patch DepartmentRelinkService at the endpoints import site."""
    import bisheng.org_sync.api.endpoints.relink as ep
    from bisheng.org_sync.domain.schemas.relink import (
        RelinkAppliedItem, RelinkResponse,
    )

    relink = AsyncMock(return_value=RelinkResponse(
        applied=[RelinkAppliedItem(
            dept_id=42, old_external_id='OLD', new_external_id='NEW',
        )],
    ))
    resolve = AsyncMock(return_value=RelinkAppliedItem(
        dept_id=42, old_external_id='OLD', new_external_id='NEW-CHOSEN',
    ))
    monkeypatch.setattr(ep.DepartmentRelinkService, 'relink', relink)
    monkeypatch.setattr(
        ep.DepartmentRelinkService, 'resolve_conflict', resolve)
    return SimpleNamespace(relink=relink, resolve=resolve)


# ---------------------------------------------------------------------------
# /relink
# ---------------------------------------------------------------------------


class TestRelinkRoute:

    def test_relink_route_responds_200_with_valid_hmac(
        self, configure_sso_secret, hmac_signer, mocked_service,
    ):
        app = _mount_app()
        body = (
            b'{"old_external_ids":["OLD"],'
            b'"matching_strategy":"external_id_map",'
            b'"external_id_map":{"OLD":"NEW"}}'
        )
        sig = hmac_signer('POST', RELINK_PATH, body)
        with TestClient(app) as client:
            resp = client.post(
                RELINK_PATH, content=body,
                headers={
                    'X-Signature': sig,
                    'Content-Type': 'application/json',
                },
            )
        assert resp.status_code == 200
        data = resp.json()['data']
        assert len(data['applied']) == 1
        assert data['applied'][0]['dept_id'] == 42
        mocked_service.relink.assert_awaited_once()
        payload = mocked_service.relink.await_args.args[0]
        assert payload.old_external_ids == ['OLD']
        assert payload.matching_strategy == 'external_id_map'

    def test_relink_dry_run_via_http_returns_would_apply(
        self, configure_sso_secret, hmac_signer, mocked_service,
    ):
        """AC-07 — HTTP entry point still honours dry_run."""
        from bisheng.org_sync.domain.schemas.relink import (
            RelinkAppliedItem, RelinkResponse,
        )
        mocked_service.relink.return_value = RelinkResponse(
            would_apply=[RelinkAppliedItem(
                dept_id=42, old_external_id='OLD', new_external_id='NEW',
            )],
        )
        app = _mount_app()
        body = (
            b'{"old_external_ids":["OLD"],'
            b'"matching_strategy":"external_id_map",'
            b'"external_id_map":{"OLD":"NEW"},'
            b'"dry_run":true}'
        )
        sig = hmac_signer('POST', RELINK_PATH, body)
        with TestClient(app) as client:
            resp = client.post(
                RELINK_PATH, content=body,
                headers={
                    'X-Signature': sig,
                    'Content-Type': 'application/json',
                },
            )
        assert resp.status_code == 200
        data = resp.json()['data']
        assert data['applied'] == []
        assert len(data['would_apply']) == 1
        payload = mocked_service.relink.await_args.args[0]
        assert payload.dry_run is True

    def test_relink_route_returns_401_without_hmac(
        self, configure_sso_secret, mocked_service,
    ):
        app = _mount_app()
        with TestClient(app) as client:
            resp = client.post(
                RELINK_PATH,
                json={
                    'old_external_ids': ['OLD'],
                    'matching_strategy': 'external_id_map',
                },
            )
        # Missing signature → HMAC dep raises 19301 via the shared
        # SsoHmacInvalidError path (same status-code convention as
        # F014's TestLoginSyncRoute::test_invalid_signature_rejected).
        assert resp.status_code == 19301
        mocked_service.relink.assert_not_awaited()


# ---------------------------------------------------------------------------
# /relink/resolve-conflict
# ---------------------------------------------------------------------------


class TestResolveConflictRoute:

    def test_resolve_conflict_route_happy_path(
        self, configure_sso_secret, hmac_signer, mocked_service,
    ):
        app = _mount_app()
        body = b'{"dept_id":42,"chosen_new_external_id":"NEW-CHOSEN"}'
        sig = hmac_signer('POST', RESOLVE_PATH, body)
        with TestClient(app) as client:
            resp = client.post(
                RESOLVE_PATH, content=body,
                headers={
                    'X-Signature': sig,
                    'Content-Type': 'application/json',
                },
            )
        assert resp.status_code == 200
        data = resp.json()['data']
        assert data['dept_id'] == 42
        assert data['new_external_id'] == 'NEW-CHOSEN'
        mocked_service.resolve.assert_awaited_once_with(
            dept_id=42, chosen_new_external_id='NEW-CHOSEN',
        )


# ---------------------------------------------------------------------------
# Tenant-check exempt registration
# ---------------------------------------------------------------------------


class TestExemptPathWhitelist:

    def test_paths_are_in_tenant_check_exempt_list(self):
        """Both relink endpoints must be exempt from the tenant-context
        middleware — they are HMAC-signed internal entrypoints with no
        JWT."""
        from bisheng.utils.http_middleware import TENANT_CHECK_EXEMPT_PATHS

        assert RELINK_PATH in TENANT_CHECK_EXEMPT_PATHS
        assert RESOLVE_PATH in TENANT_CHECK_EXEMPT_PATHS
