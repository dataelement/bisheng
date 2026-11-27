"""Reject malformed exec admission before filesystem and subprocess boundaries."""

from __future__ import annotations

import json
from unittest.mock import Mock

import execute
import pytest
from app import create_app
from starlette.testclient import TestClient

INVALID = [
    None,
    [],
    "code",
    1,
    {},
    {"code": None},
    {"code": 1},
    {"code": []},
    {"code": "x", "lang": None},
    {"code": "x", "lang": []},
    {"code": "x", "lang": 1},
    {"code": "printf acceptance-harmless-lang-canary", "lang": "acceptance_invalid_language"},
    {"code": "x", "lang": "python-not-a-language"},
    {"code": "x", "lang": "Python"},
    {"code": "x", "lang": " python"},
    *[
        {"code": "x", "timeout_s": value}
        for value in (None, True, "5", 0, -1, 3601, float("nan"), float("inf"), [], {})
    ],
    {"code": "\ud800"},
    {"code": "print(1)", "unexpected": True},
]


@pytest.fixture
def runner(tmp_path):
    app = create_app(token="test-token", sessions_root=str(tmp_path / "sessions"))
    with TestClient(app) as client:
        session = client.post("/v1/sessions", headers={"Authorization": "Bearer test-token"}).json()
        yield client, session, app.state.store


@pytest.mark.parametrize("payload", INVALID)
def test_invalid_http_payload_never_touches_execution_boundaries(runner, monkeypatch, payload):
    client, session, _store = runner
    snapshot = Mock(side_effect=AssertionError("filesystem boundary reached"))
    popen = Mock(side_effect=AssertionError("subprocess boundary reached"))
    monkeypatch.setattr(execute, "snapshot_tree", snapshot)
    monkeypatch.setattr(execute, "_RusagePopen", popen)
    response = client.post(
        f"/v1/sessions/{session['session_id']}/exec",
        headers={"X-Lease-Token": session["lease_token"]},
        content=json.dumps(payload),
    )
    assert response.status_code == 400
    assert response.json() == {"error": "invalid exec request"}
    snapshot.assert_not_called()
    popen.assert_not_called()
    assert (
        client.delete(
            f"/v1/sessions/{session['session_id']}", headers={"X-Lease-Token": session["lease_token"]}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("payload", INVALID)
def test_direct_caller_rejected_before_lock_or_fs(payload):
    store = Mock()
    lease = Mock()
    with pytest.raises(execute.InvalidExecRequest):
        execute.handle_exec(store, lease, payload)
    store.locked.assert_not_called()


@pytest.mark.parametrize("lang", ["python", "python3", "sh", "bash", "shell"])
def test_supported_language_positive(runner, lang):
    client, session, _ = runner
    code = "print('admission-ok')" if lang in {"python", "python3"} else "printf admission-ok"
    response = client.post(
        f"/v1/sessions/{session['session_id']}/exec",
        headers={"X-Lease-Token": session["lease_token"]},
        json={"code": code, "lang": lang, "timeout_s": 5},
    )
    assert response.status_code == 200
    assert response.json()["exitcode"] == 0
    assert "admission-ok" in response.json()["stdout"]


def test_missing_optional_fields_keep_python_default(runner):
    client, session, _ = runner
    response = client.post(
        f"/v1/sessions/{session['session_id']}/exec",
        headers={"X-Lease-Token": session["lease_token"]},
        json={"code": "print('default-ok')"},
    )
    assert response.status_code == 200
    assert "default-ok" in response.json()["stdout"]


def test_exec_accepts_deep_research_timeout():
    """Deep research sends timeout_s=3600; the runner must accept it."""
    assert execute.validate_exec_payload({"code": "x", "timeout_s": execute.MAX_TIMEOUT_S})[2] == 3600.0
