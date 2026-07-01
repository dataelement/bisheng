"""Integration tests for SG sync API routes.

Mounts ``sso_sync_router`` on a minimal FastAPI app and verifies:
- Fixed-header auth wiring on three SG endpoints
- Request alias parsing (``mdmId``, ``Field``, ``ROW``, etc.)
- Service call-through with ESB / TIEM response shapes
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, FastAPI
from starlette.testclient import TestClient

from bisheng.sso_sync.domain.schemas.sg_payloads import (
    SgDataInfoItem,
    SgDataInfos,
    SgDataPayload,
    SgDepartmentSyncResponse,
    SgEsbPayload,
    SgSsoAccountSyncResponse,
    SgSsoAccountSyncResultItem,
)

pytest_plugins = ["test.fixtures.sso_sync"]

DEPTS_PATH = "/api/v1/departments/sg-sync"
USERS_PATH = "/api/v1/users/sg-sync"
SSO_PATH = "/api/v1/users/sg-sso-sync"
SG_HEADER = "X-Signature"


def _mount_app() -> FastAPI:
    from bisheng.sso_sync.api.router import router as sso_sync_router

    app = FastAPI()
    api = APIRouter(prefix="/api/v1")
    api.include_router(sso_sync_router)
    app.include_router(api)
    return app


def _esb_response(*, code: str = "0") -> SgDepartmentSyncResponse:
    return SgDepartmentSyncResponse(
        ESB=SgEsbPayload(
            CODE=code,
            DESC="success" if code == "0" else "partial_failure",
            DATA=SgDataPayload(
                UUID="resp-uuid",
                DATAINFOS=SgDataInfos(
                    DATAINFO=[
                        SgDataInfoItem(
                            uuid="u1",
                            code="D1",
                            status="0",
                            version="1",
                            errorText="",
                        ),
                    ],
                ),
            ),
        ),
    )


def _sso_response() -> SgSsoAccountSyncResponse:
    return SgSsoAccountSyncResponse(
        TIEM=[
            SgSsoAccountSyncResultItem(
                Result="0",
                UserName="Alice",
                Description="success",
                Guid="guid-1",
            ),
        ],
    )


@pytest.fixture()
def mocked_sg_services(monkeypatch):
    import bisheng.sso_sync.api.endpoints.sg_departments_sync as depts_ep
    import bisheng.sso_sync.api.endpoints.sg_sso_account_sync as sso_ep
    import bisheng.sso_sync.api.endpoints.sg_users_sync as users_ep

    depts_service = AsyncMock(return_value=_esb_response())
    users_service = AsyncMock(return_value=_esb_response())
    sso_service = AsyncMock(return_value=_sso_response())

    monkeypatch.setattr(
        depts_ep.SgDepartmentsSyncService,
        "execute",
        depts_service,
    )
    monkeypatch.setattr(
        users_ep.SgUsersSyncService,
        "execute",
        users_service,
    )
    monkeypatch.setattr(
        sso_ep.SgSsoAccountSyncService,
        "execute",
        sso_service,
    )

    return SimpleNamespace(
        depts=depts_service,
        users=users_service,
        sso=sso_service,
    )


class TestSgDepartmentsSyncRoute:
    def test_valid_header_invokes_service(
        self,
        configure_sg_fixed_header,
        hmac_secret,
        mocked_sg_services,
    ):
        app = _mount_app()
        body = {
            "mdmId": 7,
            "BusinessSystem": 1,
            "uuid": "batch-1",
            "Field": [
                {
                    "uuid": "u1",
                    "code": "D1",
                    "pid": "",
                    "remark": "Dept",
                    "state": "01",
                },
            ],
        }
        with TestClient(app) as client:
            resp = client.post(
                DEPTS_PATH,
                json=body,
                headers={SG_HEADER: hmac_secret},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ESB"]["CODE"] == "0"
        assert data["ESB"]["DATA"]["UUID"] == "resp-uuid"
        mocked_sg_services.depts.assert_awaited_once()
        payload = mocked_sg_services.depts.await_args.args[0]
        assert payload.mdm_id == 7
        assert payload.fields[0].code == "D1"

    def test_invalid_header_rejected(
        self,
        configure_sg_fixed_header,
        mocked_sg_services,
    ):
        app = _mount_app()
        with TestClient(app) as client:
            resp = client.post(
                DEPTS_PATH,
                json={"mdmId": 1, "BusinessSystem": 1, "Field": []},
                headers={SG_HEADER: "wrong-secret"},
            )

        assert resp.status_code == 19301
        mocked_sg_services.depts.assert_not_awaited()


class TestSgUsersSyncRoute:
    def test_valid_header_invokes_service(
        self,
        configure_sg_fixed_header,
        hmac_secret,
        mocked_sg_services,
    ):
        app = _mount_app()
        body = {
            "mdmId": 8,
            "BusinessSystem": 1,
            "Field": [
                {
                    "uuid": "u1",
                    "code": "U1",
                    "desc34": "DEPT1",
                    "desc1": "Alice",
                    "desc93": "01",
                },
            ],
        }
        with TestClient(app) as client:
            resp = client.post(
                USERS_PATH,
                json=body,
                headers={SG_HEADER: hmac_secret},
            )

        assert resp.status_code == 200
        assert resp.json()["ESB"]["CODE"] == "0"
        mocked_sg_services.users.assert_awaited_once()
        payload = mocked_sg_services.users.await_args.args[0]
        assert payload.fields[0].desc34 == "DEPT1"


class TestSgSsoAccountSyncRoute:
    def test_valid_header_invokes_service(
        self,
        configure_sg_fixed_header,
        hmac_secret,
        mocked_sg_services,
    ):
        app = _mount_app()
        body = {
            "HEADER": {
                "INT_KEY": "k",
                "SED_NAME": "sender",
                "REC_NAME": "receiver",
                "SENDDATE": "20260422",
                "SENDTIME": "120000",
            },
            "ROW": [
                {
                    "PersonNO": "P001",
                    "UserName": "Alice",
                    "Guid": "guid-1",
                },
            ],
        }
        with TestClient(app) as client:
            resp = client.post(
                SSO_PATH,
                json=body,
                headers={SG_HEADER: hmac_secret},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["TIEM"][0]["Result"] == "0"
        assert data["TIEM"][0]["Guid"] == "guid-1"
        mocked_sg_services.sso.assert_awaited_once()
        payload = mocked_sg_services.sso.await_args.args[0]
        assert payload.rows[0].person_no == "P001"

    def test_missing_header_rejected(
        self,
        configure_sg_fixed_header,
        mocked_sg_services,
    ):
        app = _mount_app()
        with TestClient(app) as client:
            resp = client.post(
                SSO_PATH,
                json={"ROW": []},
            )

        assert resp.status_code == 19301
        mocked_sg_services.sso.assert_not_awaited()

    def test_empty_secret_fail_closed(
        self,
        disable_sg_fixed_header,
        hmac_secret,
        mocked_sg_services,
    ):
        app = _mount_app()
        with TestClient(app) as client:
            resp = client.post(
                SSO_PATH,
                json={"ROW": []},
                headers={SG_HEADER: hmac_secret},
            )

        assert resp.status_code == 19301
        mocked_sg_services.sso.assert_not_awaited()
