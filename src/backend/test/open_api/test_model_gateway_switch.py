"""F051 T012 (switch half): the face exists exactly where it is deployed.

``bisheng.api.router`` evaluates ``open_platform.enabled`` at import time, so a
monkeypatched switch does not remount anything. Both states are therefore built
here with ``importlib.reload`` against a fresh app, which is the only way to see
the mounting decision actually change.
"""

import importlib
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from test.open_api.model_gateway_fixtures import (
    FakeBishengLLM,
    capture_records,
    install_catalog,
    install_fake_llm,
    model_row,
    server_row,
    service_account_principal,
)

MODELS_PATH = "/api/v2/model/v1/models"
CHAT_PATH = "/api/v2/model/v1/chat/completions"


def build_app_with_switch(enabled: bool) -> FastAPI:
    from bisheng.common.services.config_service import settings

    previous = settings.open_platform.enabled
    settings.open_platform.enabled = enabled
    try:
        router_module = importlib.reload(importlib.import_module("bisheng.api.router"))
        app = FastAPI()
        register_open_api_exception_handlers(app)
        app.include_router(router_module.router_rpc)
        return app
    finally:
        settings.open_platform.enabled = previous


@pytest.fixture(autouse=True)
def _restore_router_module():
    yield
    # Leave the imported router matching the process-wide configuration again,
    # or every later test in this session inherits this file's mounting.
    importlib.reload(importlib.import_module("bisheng.api.router"))


async def _get(app, path, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, **kwargs)


@pytest.mark.parametrize("authorization", [None, "Bearer bs-sak-something"])
async def test_the_face_is_indistinguishable_from_nothing_when_not_deployed(monkeypatch, authorization):
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(return_value=service_account_principal()),
    )
    app = build_app_with_switch(False)
    headers = {"Authorization": authorization} if authorization else None

    face = await _get(app, MODELS_PATH, headers=headers)
    never_existed = await _get(app, "/api/v2/no-such-surface/models", headers=headers)

    assert face.status_code == never_existed.status_code == 404
    # Byte-identical to a path that was never a feature: no error code that
    # would tell an outsider "there is something here, it is switched off".
    assert face.json() == never_existed.json()


async def test_chat_completions_is_equally_absent_when_not_deployed(monkeypatch):
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(return_value=service_account_principal()),
    )
    app = build_app_with_switch(False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(CHAT_PATH, json={"model": "gpt-4o", "messages": []})

    assert response.status_code == 404
    assert "error" not in response.json()


async def test_the_face_works_on_the_open_capability_layer_alone(monkeypatch):
    # No runtime-manager, no app-proxy, no hosted-app configuration involved.
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(return_value=service_account_principal()),
    )
    install_catalog(monkeypatch, [server_row(1, "azure-openai")], [model_row(10, 1, "gpt-4o")])
    install_fake_llm(monkeypatch, FakeBishengLLM())
    capture_records(monkeypatch)
    app = build_app_with_switch(True)

    response = await _get(app, MODELS_PATH)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == ["gpt-4o"]
