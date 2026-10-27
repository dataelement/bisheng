"""Does the thing systemd starts actually start?

This file exists because of a real incident in this package's own history: a
batch shipped with a green suite and a process that would not boot, because the
dependency floor had no ceiling — the test environment resolved one FastAPI, the
production venv resolved another, and the difference only showed up at
``uvicorn runtime_manager.main:app``. The import below is at **module level on
purpose**: collecting this file is already the smoke test.

The routing check is written as "unsigned request → 401" rather than by walking
``app.routes``, because the route object graph is a FastAPI internal that has
changed shape between releases — and the property worth asserting is not "a
route object exists" but "this path is mounted *and* behind the HMAC gate".
``/healthz`` is the single deliberate exception (systemd and smoke scripts do
not hold the secret).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from runtime_manager.config import set_config
from runtime_manager.main import app, get_reconcile_loop

SIGNED_GET_PATHS = [
    "/v1/apps/app-1/route",
    "/v1/apps/app-1/status",
    "/v1/apps/app-1/logs",
    "/v1/runtime/status",
    "/v1/builds/build-1",
]

SIGNED_POST_PATHS = [
    "/v1/admission",
    "/v1/intents/build",
    "/v1/intents/deploy",
    "/v1/intents/stop",
    "/v1/intents/destroy",
    "/v1/intents/probe",
]


def test_production_entrypoint_is_importable():
    """``uvicorn runtime_manager.main:app`` — the exact object systemd runs."""
    assert app.title == "BiSheng runtime manager"
    # No OpenAPI surface: this process is reachable only from localhost and has
    # no business publishing a schema of the orchestration API.
    assert app.openapi_url is None


def test_healthz_needs_no_signature(rtm_client):
    response = rtm_client.client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_every_v1_endpoint_is_mounted_and_signed(rtm_client):
    for path in SIGNED_GET_PATHS:
        assert rtm_client.get(path, sign=False).status_code == 401, path
    for path in SIGNED_POST_PATHS:
        assert rtm_client.post(path, {}, sign=False).status_code == 401, path
    # A path that does not exist must still 404 — otherwise the assertion above
    # would pass on an app with no routes at all.
    assert rtm_client.get("/v1/nope", sign=False).status_code == 404


def test_lifespan_starts_and_stops_the_reconcile_loop(rtm_config, fake_docker):
    """AC-50 — booting the process is what triggers the alignment pass."""
    set_config(rtm_config.with_overrides(reconcile_enabled=True))
    with TestClient(app):
        loop = get_reconcile_loop()
        assert loop is not None
        assert loop.wait_for_first_pass(timeout=5.0) is True
    assert get_reconcile_loop() is None
