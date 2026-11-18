"""Configured assistant candidates and manual probes honor the management target."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.llm_tenant import LLMModelSharedReadonlyError
from bisheng.core.context.tenant import current_tenant_id, is_tenant_filter_bypassed, set_current_tenant_id
from bisheng.llm.domain.models.llm_server import LLMDao, LLMModel, LLMServer
from bisheng.llm.domain.services.llm import LLMService


def server(ident, tenant):
    return LLMServer(id=ident, tenant_id=tenant, name=f"Provider {ident}", type="openai", config={})


def model(ident, provider, tenant, online=True):
    return LLMModel(
        id=ident, tenant_id=tenant, server_id=provider, model_name=f"Model {ident}", model_type="llm", online=online
    )


@pytest.fixture
def composition(monkeypatch):
    token = set_current_tenant_id(60)
    servers = [server(337, 1), server(400, 60)]
    rows = [model(933, 337, 1), model(936, 337, 1, False), model(999, 400, 60), model(1000, 500, 65)]
    visible = AsyncMock(return_value=servers)
    configured = AsyncMock(
        return_value=SimpleNamespace(
            llm_list=[SimpleNamespace(model_id=i, default=i == 999) for i in [933, 936, 999, 1000]]
        )
    )

    async def models(_):
        assert is_tenant_filter_bypassed()
        return rows

    monkeypatch.setattr(LLMService, "acollect_visible_servers", visible)
    monkeypatch.setattr(LLMService, "get_assistant_llm", configured)
    monkeypatch.setattr(LLMDao, "aget_model_by_ids", models)
    yield SimpleNamespace(servers=servers, rows=rows, visible=visible, configured=configured)
    current_tenant_id.reset(token)


async def test_assistant_candidates_keep_configured_shared_models_and_default_order(composition):
    result = await LLMService.get_assistant_llm_list(None, SimpleNamespace(user_id=1))
    assert [row.id for row in result] == [400, 337]
    assert [row.id for row in result[1].models] == [933, 936]
    assert result[1].models[1].online is False
    composition.visible.assert_awaited_once_with(60, strict=True)


async def test_revoked_provider_and_inconsistent_model_owner_are_excluded(composition):
    composition.visible.return_value = [composition.servers[1]]
    composition.rows.append(model(1001, 400, 1))
    result = await LLMService.get_assistant_llm_list(None, SimpleNamespace(user_id=1))
    assert [row.id for provider in result for row in provider.models] == [999]


async def test_visibility_failure_does_not_fall_back_to_unfiltered_models(composition):
    composition.visible.side_effect = RuntimeError("authorization unavailable")
    with pytest.raises(RuntimeError, match="authorization unavailable"):
        await LLMService.get_assistant_llm_list(None, SimpleNamespace(user_id=1))


async def test_invalid_config_is_not_replaced_with_all_models(composition):
    composition.configured.side_effect = RuntimeError("invalid default reference")
    with pytest.raises(RuntimeError, match="invalid default reference"):
        await LLMService.get_assistant_llm_list(None, SimpleNamespace(user_id=1))
    composition.visible.assert_not_awaited()


async def test_child_scope_cannot_probe_root_even_for_global_super(composition, monkeypatch):
    shared = composition.rows[0]
    monkeypatch.setattr(LLMDao, "aget_model_by_id", AsyncMock(return_value=shared))
    probe = AsyncMock()
    monkeypatch.setattr(LLMService, "test_model_status", probe)
    with pytest.raises(LLMModelSharedReadonlyError):
        await LLMService.verify_model_status(shared.id, SimpleNamespace(user_id=1))
    probe.assert_not_awaited()


@pytest.mark.parametrize("tenant,provider", [(1, 337), (60, 400)])
async def test_own_scope_can_probe_and_return_status(composition, monkeypatch, tenant, provider):
    token = set_current_tenant_id(tenant)
    own = model(7, provider, tenant)
    monkeypatch.setattr(LLMDao, "aget_model_by_id", AsyncMock(return_value=own))
    probe = AsyncMock()
    monkeypatch.setattr(LLMService, "test_model_status", probe)
    from bisheng.llm.domain.services.llm import ContextWindowService

    monkeypatch.setattr(ContextWindowService, "invalidate", AsyncMock())
    try:
        result = await LLMService.verify_model_status(7, SimpleNamespace(user_id=1))
        assert result.id == 7
        probe.assert_awaited_once_with(own, SimpleNamespace(user_id=1))
    finally:
        current_tenant_id.reset(token)


async def test_invisible_other_tenant_model_is_not_probed(composition, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(LLMDao, "aget_model_by_id", AsyncMock(return_value=composition.rows[-1]))
    probe = AsyncMock()
    monkeypatch.setattr(LLMService, "test_model_status", probe)
    with pytest.raises(HTTPException) as error:
        await LLMService.verify_model_status(1000, SimpleNamespace(user_id=1))
    assert error.value.status_code == 404
    probe.assert_not_awaited()


@pytest.mark.parametrize("invalid", [None, 0, -1, True])
async def test_missing_or_invalid_management_target_never_probes(composition, monkeypatch, invalid):
    from bisheng.common.errcode.llm_tenant import LLMSystemConfigForbiddenError

    monkeypatch.setattr("bisheng.llm.domain.services.llm.get_current_tenant_id", lambda: invalid)
    probe = AsyncMock()
    monkeypatch.setattr(LLMService, "test_model_status", probe)
    with pytest.raises(LLMSystemConfigForbiddenError):
        await LLMService.verify_model_status(933, SimpleNamespace(user_id=1))
    composition.visible.assert_not_awaited()
    probe.assert_not_awaited()
