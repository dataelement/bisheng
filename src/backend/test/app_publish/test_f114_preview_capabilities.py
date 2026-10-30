"""Frozen preview declaration and current-purpose guards (AC-38/AC-50/AC-59)."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


async def test_preview_draft_declaration_uses_bound_version_not_current(monkeypatch):
    from bisheng.app_publish.domain.services import capability_bus_service as mod
    from bisheng.open_api.application import access_context
    from bisheng.open_api.domain.services import preview_context

    app = SimpleNamespace(id="app", name="App", tenant_id=3, state="draft", current_version_id="old")
    version = SimpleNamespace(id="pending", capabilities={"models": [{"name": "preview-model"}]})

    @asynccontextmanager
    async def sessions():
        yield object()

    monkeypatch.setattr(mod, "get_async_db_session", sessions)
    monkeypatch.setattr(mod.AppDao, "aget", AsyncMock(return_value=app))
    monkeypatch.setattr(mod.AppVersionDao, "aget", AsyncMock(return_value=version))
    monkeypatch.setattr(mod, "_resolve_knowledge_refs", AsyncMock(return_value=()))
    monkeypatch.setattr(
        access_context,
        "get_current_open_api_principal",
        lambda: SimpleNamespace(actor_kind="hosted_app", preview_session_id="s"),
    )
    monkeypatch.setattr(
        preview_context,
        "revalidate_preview",
        AsyncMock(return_value=SimpleNamespace(app_id="app", version_id="pending")),
    )
    result = await mod.load_effective_declaration("app")
    assert result.version_id == "pending" and result.model_names == frozenset({"preview-model"})
    assert mod.AppVersionDao.aget.call_args.args[2] == "pending"


async def test_terminal_preview_is_not_reinterpreted_as_production(monkeypatch):
    from bisheng.app_publish.domain.services import capability_bus_service as mod
    from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError
    from bisheng.open_api.application import access_context
    from bisheng.open_api.domain.services import preview_context

    monkeypatch.setattr(
        access_context,
        "get_current_open_api_principal",
        lambda: SimpleNamespace(actor_kind="hosted_app", preview_session_id="s"),
    )
    monkeypatch.setattr(preview_context, "revalidate_preview", AsyncMock(side_effect=OpenApiCredentialInvalidError()))
    with pytest.raises(OpenApiCredentialInvalidError):
        await mod.load_effective_declaration("app")
