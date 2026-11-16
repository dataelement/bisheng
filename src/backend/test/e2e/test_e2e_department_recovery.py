"""F086 HTTP-to-recovery contract; full deployed FGA/DM/Worker E2E is separate.

AC-01/03/19: real HMAC, payload parsing, batch and timestamp service; injected
runtime transport. SQL/FGA crash recovery is tested separately with real SQLite.
No production endpoints or persistent data are touched by this suite.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from bisheng.database.models.department import Department
from bisheng.department.domain.services import department_projection_scope as scopes
from bisheng.department.domain.services import department_service
from bisheng.sso_sync.api.endpoints import departments_sync as endpoint
from bisheng.sso_sync.domain.services import departments_sync_service as sync
from test.e2e.helpers.api import assert_resp_200

pytest_plugins = ["test.fixtures.sso_sync"]

PATH = "/api/v1/departments/sync"
BODY = b'{"source":"wecom","source_ts":100,"upsert":[{"external_id":"e2e-f086-one","name":"e2e-f086-one","ts":100}],"remove":[]}'


def setup(monkeypatch):
    department = Department(
        id=11,
        tenant_id=7,
        dept_id="e2e-f086-one",
        name="e2e-f086-one",
        source="wecom",
        external_id="e2e-f086-one",
        last_sync_ts=100,
        path="/1/11/",
        parent_id=1,
        permission_projection_state="FAILED_CLOSED",
        permission_projection_operation_id=41,
    )
    runtime = SimpleNamespace(
        reconcile_operation=AsyncMock(return_value=SimpleNamespace(target_version=1)),
        needs_recovery=AsyncMock(return_value=False),
    )
    monkeypatch.setattr(scopes, "get_department_projection_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(department_service, "_uses_f048_department_projection", lambda: True)
    monkeypatch.setattr(sync.DepartmentsSyncService, "_preload_parent_cache", AsyncMock(return_value={}))
    monkeypatch.setattr(
        sync.DepartmentTopologyProjectionService, "sync_recovery_hints", AsyncMock(return_value={"e2e-f086-one": True})
    )
    monkeypatch.setattr(sync.DepartmentDao, "aget_tenant_root_via_pointer", AsyncMock(return_value=None))
    monkeypatch.setattr(sync.DepartmentDao, "aget_by_source_external_id", AsyncMock(return_value=department))
    monkeypatch.setattr(endpoint, "flush_log", AsyncMock())
    monkeypatch.setattr(sync.DeptUpsertService, "upsert_from_sync_payload", AsyncMock(return_value=department))
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/api/v1")
    return TestClient(app), runtime, department


@pytest.mark.parametrize("incoming_ts", [99, 100])
def test_ac01_ac03_signed_replay_recovers_before_timestamp_short_circuit(
    monkeypatch, configure_sso_secret, hmac_signer, incoming_ts
):
    """AC-01/03: identical sync replay dispatches recovery once, with unchanged ts."""
    client, runtime, department = setup(monkeypatch)
    body = BODY.replace(b"100", str(incoming_ts).encode())
    with client:
        for _ in range(2):
            response = client.post(
                PATH,
                content=body,
                headers={"X-Signature": hmac_signer("POST", PATH, body), "Content-Type": "application/json"},
            )
            data = assert_resp_200(response)
            assert data["skipped_ts_conflict"] == (incoming_ts < 100) and data["errors"] == []
    runtime.reconcile_operation.assert_awaited_once_with(41)
    assert department.permission_projection_state == "CURRENT"
    assert department.permission_projection_version == 1 and department.last_sync_ts == 100


def test_ac19_unsigned_request_cannot_trigger_recovery(monkeypatch, configure_sso_secret):
    """AC-19: paired deny case; untrusted input never reaches recovery."""
    client, runtime, _ = setup(monkeypatch)
    with client:
        response = client.post(
            PATH, content=BODY, headers={"X-Signature": "invalid", "Content-Type": "application/json"}
        )
    assert response.status_code == 19301
    runtime.reconcile_operation.assert_not_awaited()
