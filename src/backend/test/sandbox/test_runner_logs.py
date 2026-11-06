"""Runner operational logs omit secrets and user code."""

from __future__ import annotations

import logging

from app import create_app
from starlette.testclient import TestClient


def test_session_and_exec_logs_omit_token_and_code(caplog, tmp_path):
    app = create_app(token="secret-runner-token", sessions_root=str(tmp_path / "sessions"))
    logger = logging.getLogger("sandbox")
    previous = logger.propagate
    logger.propagate = True
    secret_code = "print('UNIQUE_USER_CODE_MARKER')"
    try:
        with caplog.at_level(logging.INFO):
            with TestClient(app) as client:
                created = client.post(
                    "/v1/sessions",
                    headers={"Authorization": "Bearer secret-runner-token"},
                ).json()
                sid = created["session_id"]
                token = created["lease_token"]
                resp = client.post(
                    f"/v1/sessions/{sid}/exec",
                    headers={"X-Lease-Token": token},
                    json={"code": secret_code, "lang": "python", "timeout_s": 5},
                )
                assert resp.status_code == 200
                assert resp.json()["exitcode"] == 0
    finally:
        logger.propagate = previous

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "session created" in text
    assert f"session_id={sid}" in text
    assert "exec start" in text
    assert "exec done" in text
    assert "exitcode=0" in text
    assert "secret-runner-token" not in text
    assert token not in text
    assert "UNIQUE_USER_CODE_MARKER" not in text
    assert secret_code not in text
