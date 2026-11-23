"""Chat/Work enforce platform model visibility in both DSH deployment modes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.v1.schemas import WorkstationConfig
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.dsh.domain.services import model_catalog, vision
from bisheng.llm.domain.schemas import WorkbenchModelConfig
from bisheng.llm.domain.services.llm import LLMService


@pytest.fixture(params=[False, True], ids=["without-dsh", "with-dsh"])
async def ordinary_catalog(monkeypatch, request):
    from bisheng.common.services import config_service

    monkeypatch.setattr(
        config_service,
        "settings",
        SimpleNamespace(
            dsh=SimpleNamespace(enabled=request.param),
            get_linsight_conf=lambda: SimpleNamespace(default_temperature=0),
        ),
    )
    server = SimpleNamespace(id=1, name="Own provider", type="openai", tenant_id=1)
    models = [
        (SimpleNamespace(id=mid, server_id=1, tenant_id=1, model_name=f"m{mid}", name=f"m{mid}"), server)
        for mid in (7, 8)
    ]
    monkeypatch.setattr(LLMService, "aget_online_chat_models", AsyncMock(return_value=models))
    visible = AsyncMock(return_value={7})
    monkeypatch.setattr(model_catalog, "read_visible_model_ids", visible)
    monkeypatch.setattr(vision, "read_catalog_vision", AsyncMock(return_value={7: False}))
    config = WorkbenchModelConfig(
        models=[{"id": "7", "name": "visible"}, {"id": "8", "name": "hidden"}], linsight_default_model_id="7"
    )
    monkeypatch.setattr(LLMService, "get_workbench_llm_candidates", AsyncMock(return_value=config))
    monkeypatch.setattr(model_catalog, "read_workbench_metadata", AsyncMock(return_value=config))
    return SimpleNamespace(
        user=UserPayload(user_id=42, user_name="ordinary", tenant_id=1, user_role=[]), visible=visible
    )


async def test_work_keeps_hidden_explicit_identity_and_refuses_before_model_creation(ordinary_catalog, monkeypatch):
    from bisheng.linsight.domain.services import agent_factory

    factory = AsyncMock(return_value="model")
    monkeypatch.setattr(LLMService, "get_bisheng_linsight_llm", factory)
    session = SimpleNamespace(tenant_id=1, user_id=ordinary_catalog.user.user_id)
    with pytest.raises(ValueError, match="not currently available"):
        await agent_factory._resolve_model(session, "8")
    ordinary_catalog.visible.assert_awaited_once_with(42, [7, 8])
    factory.assert_not_awaited()


async def test_chat_rejects_hidden_explicit_id_before_session_or_model_creation(ordinary_catalog, monkeypatch):
    from bisheng.api.v1.schema.chat_schema import APIChatCompletion
    from bisheng.workstation.domain.services import chat_service

    monkeypatch.setattr(chat_service.WorkStationService, "aget_config", AsyncMock(return_value=WorkstationConfig()))
    insert = AsyncMock(side_effect=AssertionError("hidden model request created a session"))
    monkeypatch.setattr(chat_service.MessageSessionDao, "async_insert_one", insert)
    factory = AsyncMock(side_effect=AssertionError("hidden model request initialized a model"))
    monkeypatch.setattr(LLMService, "get_bisheng_llm", factory)
    data = APIChatCompletion(clientTimestamp="t", model="8", text="hello")
    with pytest.raises(ValueError, match="not found"):
        await chat_service._agent_initialize_chat(data, ordinary_catalog.user)
    ordinary_catalog.visible.assert_awaited_once_with(42, [7, 8])
    insert.assert_not_awaited()
    factory.assert_not_awaited()
