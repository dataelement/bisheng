"""覆盖 AC: AC-18, AC-19, AC-21, AC-30. Actual LLM classes, isolated DAO reads."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.dsh import DshModelNotAllowedError
from bisheng.core.context.tenant import current_tenant_id, is_tenant_filter_bypassed, set_current_tenant_id


class SnapshotRow(SimpleNamespace):
    def model_copy(self, *, deep=False):
        return deepcopy(self) if deep else SnapshotRow(**vars(self))


@pytest.fixture
def models(monkeypatch):
    from bisheng.llm.domain.services.llm import LLMDao, LLMService

    model = SnapshotRow(
        id=42, tenant_id=2, server_id=8, online=True, model_type="llm", model_name="m", config={"temperature": 0.5}
    )
    server = SnapshotRow(id=8, tenant_id=2, type="openai", config={"model": "current"})

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
    model.config["temperature"] = 2
    server.config["model"] = "modified later"
    assert fresh_model.config["temperature"] == 0.5
    assert fresh_server.config["model"] == "current"


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
    model = SnapshotRow(id=42, model_name="latest", server_id=8, config={"version": 2})
    server = SnapshotRow(id=8, config={"version": 3})
    result = Recording.get_class_instance_from_snapshot(
        model_info=model, server_info=server, user_id=20, disable_retries=True
    )
    assert result.values["model_info"].config["version"] == 2
    assert result.values["model_info"].config["user_kwargs"]["max_retries"] == 0
    assert "user_kwargs" not in model.config
    assert result.values["server_info"].config["version"] == 3
    assert result.values["model_id"] == 42
    assert result.values["model_info"] is not model
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
