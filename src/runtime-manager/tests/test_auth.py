"""HMAC boundary of the runtime manager (T018).

This process is the single component allowed to hold the orchestration backend
access face (K1). Its authentication is therefore not a formality: anything that
can reach 127.0.0.1:8091 and forge a request can build and run containers. Hence
the negative cases below outnumber the positive one, and the "unconfigured
secret" case is a *rejection*, not a bypass.
"""

from __future__ import annotations

from runtime_manager.auth import compute_signature
from runtime_manager.config import set_config


def test_signature_covers_method_path_and_body():
    """Canonical string is ``METHOD\\nPATH\\nraw_body`` — identical to F014."""
    a = compute_signature("POST", "/v1/admission", b'{"a":1}', "s")
    assert a == compute_signature("post", "/v1/admission", b'{"a":1}', "s")
    assert a != compute_signature("GET", "/v1/admission", b'{"a":1}', "s")
    assert a != compute_signature("POST", "/v1/probe", b'{"a":1}', "s")
    assert a != compute_signature("POST", "/v1/admission", b'{"a":2}', "s")
    assert a != compute_signature("POST", "/v1/admission", b'{"a":1}', "other-secret")


def test_healthz_is_the_only_unauthenticated_route(rtm_client):
    """systemd / smoke must be able to ask "are you up" without the secret."""
    assert rtm_client.client.get("/healthz").status_code == 200


def test_missing_signature_rejected(rtm_client):
    response = rtm_client.post("/v1/admission", {"tier": {"cpu": 1, "mem": 512}}, sign=False)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthorized"


def test_wrong_secret_rejected(rtm_client):
    response = rtm_client.post(
        "/v1/admission", {"tier": {"cpu": 1, "mem": 512}}, secret="not-the-secret"
    )
    assert response.status_code == 401


def test_body_tampering_rejected(rtm_client):
    """Signature is over the bytes, so swapping the tier after signing fails."""
    import json

    body = json.dumps({"tier": {"cpu": 1, "mem": 512}, "purpose": "run"}).encode()
    signature = compute_signature("POST", "/v1/admission", body, "rtm-test-secret")
    tampered = json.dumps({"tier": {"cpu": 8, "mem": 65536}, "purpose": "run"}).encode()

    response = rtm_client.client.post(
        "/v1/admission",
        content=tampered,
        headers={"X-Signature": signature, "content-type": "application/json"},
    )
    assert response.status_code == 401


def test_empty_secret_fails_closed(rtm_client, rtm_config):
    """A mis-configured rollout must reject everything, not accept everything."""
    set_config(rtm_config.with_overrides(hmac_secret=""))

    response = rtm_client.post("/v1/admission", {"tier": {"cpu": 1, "mem": 512}})

    assert response.status_code == 401
    assert "not configured" in response.json()["detail"]["message"]


def test_valid_signature_reaches_the_handler(rtm_client, monkeypatch):
    from tests.fakes import FakeHostProbe

    monkeypatch.setattr(
        "runtime_manager.admission.LinuxHostProbe.snapshot",
        lambda self: FakeHostProbe().snapshot(),
    )
    response = rtm_client.post("/v1/admission", {"tier": {"cpu": 1, "mem": 512}, "purpose": "run"})
    assert response.status_code == 200
