"""Only platform-backed v2 control is registered; common helpers remain available."""

import pytest

from runtime_manager.config import Config


def test_default_v2_and_non_v2_refused():
    assert Config().protocol_version == 2
    for value in (1, 0, 3):
        with pytest.raises(ValueError, match="v2"):
            Config(protocol_version=value)


def test_legacy_routes_not_registered():
    from runtime_manager.main import create_app

    app = create_app(Config(reconcile_enabled=False))
    paths = {route.path for route in app.routes}
    assert "/healthz" in paths
    assert any(path.startswith("/v2/") for path in paths)
    assert not any(path.startswith("/v1/") or "upgrade" in path or "inventory" in path for path in paths)
    from runtime_manager import appdb, builder

    assert builder is not None and appdb is not None


def test_health_and_unsigned_v2_control_fail_closed():
    from fastapi.testclient import TestClient

    from runtime_manager.main import create_app

    with TestClient(create_app(Config(reconcile_enabled=False))) as client:
        assert client.get("/healthz").status_code == 200
        assert client.post("/v2/operations", json={"operation_id": "op"}).status_code == 403
        assert client.post("/v1/intents/deploy", json={}).status_code == 404
