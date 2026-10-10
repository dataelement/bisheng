"""Standalone startup must not seed or mount the production application."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from bisheng.eplus.debug_app import create_app


def test_app_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("EPLUS_DEBUG_ENABLED", raising=False)
    with pytest.raises(RuntimeError):
        create_app()


def test_isolated_app_has_only_debug_routes_and_no_production_lifespan(monkeypatch):
    import bisheng.eplus.debug_app as module

    monkeypatch.setenv("EPLUS_DEBUG_ENABLED", "true")
    app = create_app()
    paths = {r.path for r in app.routes}
    assert "/robot-debug/api/status" in paths
    assert not any(p.startswith("/api/v1") or p.startswith("/api/v2") for p in paths)
    initialize, close = AsyncMock(), AsyncMock()
    monkeypatch.setattr(module, "initialize_app_context", initialize)
    monkeypatch.setattr(module, "close_app_context", close)
    monkeypatch.setattr(module, "register_permission_context", lambda: None)
    monkeypatch.setattr(module, "configure_debug_logging", lambda: None)
    with TestClient(app):
        pass
    initialize.assert_awaited_once()
    close.assert_awaited_once()


def test_body_limit_before_authentication(monkeypatch):
    monkeypatch.setenv("EPLUS_DEBUG_ENABLED", "true")
    response = TestClient(create_app()).post("/robot-debug/api/assistants/a/run", content=b"x" * (512 * 1024 + 1))
    assert response.status_code == 413


def test_debug_auth_uses_same_cookie_first_selection_as_middleware(monkeypatch):
    from starlette.requests import Request
    from starlette.responses import Response

    from bisheng.eplus.debug_app import DebugAuthJwt

    # Other suites reload auth modules; patch the actual subclass under test.
    monkeypatch.setattr(DebugAuthJwt, "decode_jwt_token", lambda self, token: {"selected": token})

    def identity(headers):
        req = Request({"type": "http", "headers": headers})
        return DebugAuthJwt(req=req, res=Response()).get_subject()

    assert identity([(b"authorization", b"Bearer bearer-token")]) == {"selected": "bearer-token"}
    assert identity([(b"authorization", b"Bearer bearer-token"), (b"cookie", b"access_token_cookie=cookie-token")]) == {
        "selected": "cookie-token"
    }


async def test_debug_permission_discovery_never_bootstraps_even_when_development_config_requests_it(monkeypatch):
    from types import SimpleNamespace

    import bisheng.common.permission_identity as identity
    import bisheng.core.openfga.manager as fga_module
    import bisheng.eplus.debug_app as module
    from bisheng.common.errcode.permission import AuthorizationModelMismatchError
    from bisheng.core.config.openfga import OpenFGAConf

    contexts = {}
    conf = OpenFGAConf(force_write_model=True)
    monkeypatch.setattr(module, "settings", SimpleNamespace(openfga=conf))
    # Restore the shared permission hook after registering this isolated fixture.
    monkeypatch.setattr(identity, "_tenant_admin_checker", identity._tenant_admin_checker)
    monkeypatch.setattr(module.app_context, "unregister_context", lambda name: None)
    monkeypatch.setattr(
        module.app_context, "register_context", lambda context, **kwargs: contexts.update({context.name: context})
    )
    seen = []

    async def missing_store(config, **kwargs):
        seen.append(kwargs["allow_bootstrap"])
        raise AuthorizationModelMismatchError(msg="missing store")

    monkeypatch.setattr(fga_module, "discover_openfga_runtime", missing_store)
    module.register_permission_context()
    with pytest.raises(AuthorizationModelMismatchError):
        await contexts["openfga"]._async_initialize()
    assert seen == [False]
    assert conf.force_write_model is True


def test_safe_logging_is_installed_before_infrastructure_initialization(monkeypatch):
    import bisheng.eplus.debug_app as module

    monkeypatch.setenv("EPLUS_DEBUG_ENABLED", "true")
    order = []

    async def initialize(*args):
        order.append("initialize")

    monkeypatch.setattr(module, "initialize_app_context", initialize)
    monkeypatch.setattr(module, "close_app_context", AsyncMock())
    monkeypatch.setattr(module, "register_permission_context", lambda: None)
    monkeypatch.setattr(module, "configure_debug_logging", lambda: order.append("logging"))
    with TestClient(create_app()):
        pass
    assert order == ["logging", "initialize"]


def test_safe_logging_suppresses_standard_library_provider_payloads(monkeypatch, caplog):
    import logging
    from unittest.mock import MagicMock

    import bisheng.eplus.debug_app as module

    # Keep the global Loguru sinks untouched while exercising real stdlib logging.
    monkeypatch.setattr(module, "logger", MagicMock())
    previous = logging.root.manager.disable
    try:
        logging.disable(logging.NOTSET)
        module.configure_debug_logging()
        logging.getLogger("uvicorn.error").critical("sensitive startup provider body")
        assert "sensitive startup provider body" not in caplog.text
    finally:
        logging.disable(previous)


async def test_uvicorn_startup_failure_does_not_log_raw_provider_body(monkeypatch):
    import io
    import logging
    from unittest.mock import MagicMock

    from uvicorn import Config
    from uvicorn.lifespan.on import LifespanOn

    import bisheng.eplus.debug_app as module

    monkeypatch.setenv("EPLUS_DEBUG_ENABLED", "true")
    monkeypatch.setattr(module, "logger", MagicMock())
    monkeypatch.setattr(
        module, "initialize_app_context", AsyncMock(side_effect=RuntimeError("sensitive startup marker"))
    )
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    logger = logging.getLogger("uvicorn.error")
    previous = logging.root.manager.disable
    logger.addHandler(handler)
    try:
        logging.disable(logging.NOTSET)
        lifespan = LifespanOn(Config(create_app(), lifespan="on", log_config=None))
        await lifespan.startup()
        assert lifespan.should_exit
        assert "sensitive startup marker" not in output.getvalue()
    finally:
        logger.removeHandler(handler)
        logging.disable(previous)
