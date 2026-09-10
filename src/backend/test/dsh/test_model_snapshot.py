"""覆盖 AC: AC-18, AC-19, AC-21, AC-30. Actual LLM classes, isolated DAO reads."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.dsh import DshModelNotAllowedError
from bisheng.core.context.tenant import current_tenant_id, is_tenant_filter_bypassed, set_current_tenant_id


@pytest.fixture
def models(monkeypatch):
    from bisheng.llm.domain.services.llm import LLMDao, LLMService

    model = SimpleNamespace(
        id=42, tenant_id=2, server_id=8, online=True, model_type="llm", model_name="m", config={"temperature": 0.5}
    )
    server = SimpleNamespace(id=8, tenant_id=2, type="openai", config={"model": "current"})

    async def read_model(model_id, *, cache=False):
        assert cache is False
        return model if is_tenant_filter_bypassed() or model.tenant_id == 2 else None

    monkeypatch.setattr(LLMDao, "aget_model_by_id", AsyncMock(side_effect=read_model))
    monkeypatch.setattr(LLMDao, "aget_server_by_id", AsyncMock(return_value=server))
    monkeypatch.setattr(LLMDao, "aget_shared_server_ids_for_leaf", AsyncMock(return_value=[8]))
    token = set_current_tenant_id(2)
    yield LLMService, LLMDao, model, server
    current_tenant_id.reset(token)


async def test_snapshot_reuses_authorized_model_and_uncached_provider(models):
    service, dao, model, server = models
    fresh_model, fresh_server = await service.get_dsh_model_snapshot(42)
    dao.aget_model_by_id.assert_awaited_once_with(42)
    dao.aget_server_by_id.assert_awaited_once_with(8, cache=False)
    assert fresh_model is model
    assert fresh_server is server


@pytest.mark.parametrize(
    "mutation", ["offline", "wrong_type", "deleted_model", "deleted_server", "mismatched_owner", "foreign_owner"]
)
async def test_unavailable_and_cross_tenant_models_refused(models, mutation):
    service, dao, model, server = models
    if mutation == "offline":
        model.online = False
    if mutation == "wrong_type":
        model.model_type = "embedding"
    if mutation == "deleted_model":
        dao.aget_model_by_id.side_effect = AsyncMock(return_value=None)
    if mutation == "deleted_server":
        dao.aget_server_by_id.return_value = None
    if mutation == "mismatched_owner":
        server.tenant_id = 3
    if mutation == "foreign_owner":
        model.tenant_id = server.tenant_id = 3
    with pytest.raises(DshModelNotAllowedError):
        await service.get_dsh_model_snapshot(42)


async def test_root_shared_allowed_only_via_current_canonical_authorization(models):
    service, dao, model, server = models
    model.tenant_id = server.tenant_id = 1
    assert (await service.get_dsh_model_snapshot(42))[0].tenant_id == 1
    dao.aget_shared_server_ids_for_leaf.return_value = []
    with pytest.raises(DshModelNotAllowedError):
        await service.get_dsh_model_snapshot(42)


def test_builder_uses_same_snapshot_without_cache_lookup(monkeypatch):
    from bisheng.llm.domain.llm.base import BishengBase

    class Recording(BishengBase):
        def __init__(self, **kwargs):
            object.__setattr__(self, "values", kwargs)

    monkeypatch.setattr(BishengBase, "get_model_server_info_sync", lambda *args: pytest.fail("unexpected cache read"))
    model = SimpleNamespace(id=42, model_name="latest", server_id=8, config={"version": 2})
    server = SimpleNamespace(id=8, config={"version": 3})
    result = Recording.get_class_instance_from_snapshot(model_info=model, server_info=server, user_id=20, max_retries=0)
    assert result.values["model_info"].config["version"] == 2
    assert result.values["max_retries"] == 0
    assert "user_kwargs" not in model.config
    assert result.values["server_info"].config["version"] == 3
    assert result.values["model_id"] == 42
    assert result.values["model_info"] is model
    with pytest.raises(ValueError):
        Recording.get_class_instance_from_snapshot(model_info=model, server_info=server, model_id=43)


def test_actual_bisheng_wrapper_receives_no_retry_provider_config(monkeypatch):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from bisheng.llm.domain.services.llm import BishengLLM, LLMModel, LLMServer, LLMService

    captured = {}

    def create_provider(**kwargs):
        captured.update(kwargs)
        return FakeListChatModel(responses=["ok"])

    monkeypatch.setattr(BishengLLM, "_get_llm_class", staticmethod(lambda kind: create_provider))
    model = LLMModel(
        id=42,
        server_id=8,
        tenant_id=2,
        model_name="test",
        model_type="llm",
        online=True,
        config={"user_kwargs": {"max_retries": 5}},
    )
    server = LLMServer(id=8, tenant_id=2, name="test", type="openai", config={})
    wrapper = LLMService.build_dsh_llm(model, server, user_id=20)
    assert isinstance(wrapper, BishengLLM)
    assert captured["max_retries"] == 0
    assert model.config["user_kwargs"]["max_retries"] == 5


@pytest.mark.parametrize("provider", ["openai", "qwen"])
@pytest.mark.parametrize("serialized", [False, True])
@pytest.mark.parametrize("configured_retries", [None, 5])
async def test_real_clients_keep_retry_override_local_to_dsh(provider, serialized, configured_retries):
    from sqlalchemy import inspect
    from sqlalchemy.orm import make_transient_to_detached

    from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
    from bisheng.llm.domain.services.llm import BishengLLM, LLMModel, LLMServer, LLMService

    advanced = {"extra_body": {"custom_option": True}}
    if configured_retries is not None:
        advanced["max_retries"] = configured_retries
    model = LLMModel(
        id=42,
        server_id=8,
        tenant_id=2,
        model_name="test",
        model_type="llm",
        online=True,
        config={"user_kwargs": json.dumps(advanced) if serialized else advanced},
    )
    server = LLMServer(
        id=8,
        tenant_id=2,
        name="test",
        type=provider,
        config={"openai_api_key": "test-placeholder", "openai_api_base": "http://127.0.0.1:1/v1"},
    )
    # Loaded ORM rows are clean: this is the state that triggered ObjectDereferencedError.
    make_transient_to_detached(model)
    make_transient_to_detached(server)
    original_config = json.dumps(model.config, sort_keys=True)
    original_server_config = json.dumps(server.config, sort_keys=True)
    dsh = LLMService.build_dsh_llm(model, server, user_id=20)
    ordinary = BishengLLM(
        model_id=model.id,
        model_info=model,
        server_info=server,
        app_id="test",
        app_name="test",
        app_type=ApplicationTypeEnum.DSH_DESKTOP,
        user_id=20,
    )
    try:
        assert dsh.llm.root_client.max_retries == 0
        assert dsh.llm.root_async_client.max_retries == 0
        expected = configured_retries if configured_retries is not None else 2
        assert ordinary.llm.root_client.max_retries == expected
        assert ordinary.llm.root_async_client.max_retries == expected
        assert dsh.model_info is model and dsh.server_info is server
        assert json.dumps(model.config, sort_keys=True) == original_config
        assert json.dumps(server.config, sort_keys=True) == original_server_config
        assert not inspect(model).modified and not inspect(server).modified
    finally:
        dsh.llm.root_client.close()
        ordinary.llm.root_client.close()
        await dsh.llm.root_async_client.close()
        await ordinary.llm.root_async_client.close()
