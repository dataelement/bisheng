"""Lease protocol for the isolation-environment runner (F068 T007)."""

from __future__ import annotations

import time

import pytest
from app import create_app
from starlette.testclient import TestClient


@pytest.fixture
def runner_client(tmp_path):
    app = create_app(
        token="test-token",
        sessions_root=str(tmp_path / "sessions"),
        max_sessions=1,
        lease_ttl_s=900,
    )
    with TestClient(app) as client:
        yield client


def _auth(token: str = "test-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_routes_do_not_contain_config():
    from app import ROUTES

    for path in ROUTES:
        assert "config" not in path.lower()


def test_health(runner_client: TestClient):
    resp = runner_client.get("/health")
    assert resp.status_code == 200


def test_create_session_requires_global_token(runner_client: TestClient):
    assert runner_client.post("/v1/sessions").status_code == 401
    assert runner_client.post("/v1/sessions", headers=_auth("wrong")).status_code == 401
    resp = runner_client.post("/v1/sessions", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"]
    assert body["lease_token"]
    assert body["lease_expires_at"]


def test_capacity_full_returns_503(runner_client: TestClient):
    first = runner_client.post("/v1/sessions", headers=_auth())
    assert first.status_code == 200
    second = runner_client.post("/v1/sessions", headers=_auth())
    assert second.status_code == 503


def test_foreign_lease_token_cannot_delete_other_session(tmp_path):
    app = create_app(
        token="test-token",
        sessions_root=str(tmp_path / "sessions"),
        max_sessions=2,
        lease_ttl_s=900,
        enable_uid_isolation=True,
    )
    with TestClient(app) as client:
        a = client.post("/v1/sessions", headers=_auth()).json()
        b = client.post("/v1/sessions", headers=_auth()).json()
        resp = client.delete(
            f"/v1/sessions/{b['session_id']}",
            headers={"X-Lease-Token": a["lease_token"]},
        )
        assert resp.status_code == 403


def test_delete_then_exec_is_404(runner_client: TestClient):
    created = runner_client.post("/v1/sessions", headers=_auth()).json()
    sid = created["session_id"]
    token = created["lease_token"]
    headers = {"X-Lease-Token": token}
    assert runner_client.delete(f"/v1/sessions/{sid}", headers=headers).status_code == 200
    exec_resp = runner_client.post(
        f"/v1/sessions/{sid}/exec",
        headers=headers,
        json={"code": "print(1)", "lang": "python", "timeout_s": 5},
    )
    assert exec_resp.status_code == 404


def test_idle_ttl_releases_lease(tmp_path):
    app = create_app(
        token="test-token",
        sessions_root=str(tmp_path / "sessions"),
        max_sessions=1,
        lease_ttl_s=0.05,
    )
    with TestClient(app) as client:
        created = client.post("/v1/sessions", headers=_auth()).json()
        time.sleep(0.12)
        exec_resp = client.post(
            f"/v1/sessions/{created['session_id']}/exec",
            headers={"X-Lease-Token": created["lease_token"]},
            json={"code": "print(1)", "lang": "python", "timeout_s": 5},
        )
        assert exec_resp.status_code == 404
        # slot is free again
        assert client.post("/v1/sessions", headers=_auth()).status_code == 200
