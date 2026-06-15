"""F022 T02 LLMService refactor tests — verify the 5 system-config
methods route through ``TenantSystemModelConfigDao`` and the new
``tenant_id`` parameter.

Mocks the DAO entirely so we test the Service-layer wiring, not the
persistence path. The DAO itself is covered by
``test_tenant_system_model_config_dao.py``.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.models.config import ConfigKeyEnum


# --- _resolve_tenant_id helper ---------------------------------------------


def test_resolve_tenant_id_prefers_explicit_arg():
    from bisheng.llm.domain.services.llm import _resolve_tenant_id
    with patch('bisheng.llm.domain.services.llm.get_current_tenant_id',
               return_value=99):
        assert _resolve_tenant_id(5) == 5  # explicit wins


def test_resolve_tenant_id_falls_back_to_context_var():
    from bisheng.llm.domain.services.llm import _resolve_tenant_id
    with patch('bisheng.llm.domain.services.llm.get_current_tenant_id',
               return_value=7):
        assert _resolve_tenant_id(None) == 7


def test_resolve_tenant_id_falls_back_to_root_and_warns():
    from bisheng.llm.domain.services.llm import _resolve_tenant_id, ROOT_TENANT_ID
    with patch('bisheng.llm.domain.services.llm.get_current_tenant_id',
               return_value=None), \
         patch('bisheng.llm.domain.services.llm.logger') as mock_logger:
        result = _resolve_tenant_id(None)
    assert result == ROOT_TENANT_ID
    mock_logger.warning.assert_called_once()
    assert 'Celery' in mock_logger.warning.call_args[0][0]


# --- aget_*_llm with tenant_id routing -------------------------------------


@pytest.mark.asyncio
async def test_aget_knowledge_llm_routes_to_dao_with_explicit_tenant():
    from bisheng.llm.domain.services.llm import LLMService

    payload = {'embedding_model_id': 99}
    aresolve_mock = AsyncMock(return_value=(json.dumps(payload), False, False))
    with patch('bisheng.llm.domain.services.llm.TenantSystemModelConfigDao.aresolve',
               aresolve_mock):
        cfg = await LLMService.aget_knowledge_llm(tenant_id=5)
    assert cfg.embedding_model_id == 99
    aresolve_mock.assert_awaited_once_with(
        tenant_id=5, key=ConfigKeyEnum.KNOWLEDGE_LLM.value,
    )


@pytest.mark.asyncio
async def test_aget_knowledge_llm_with_meta_returns_envelope():
    from bisheng.llm.domain.services.llm import LLMService

    aresolve_mock = AsyncMock(
        return_value=(json.dumps({'embedding_model_id': 1}), True, False),
    )
    with patch('bisheng.llm.domain.services.llm.TenantSystemModelConfigDao.aresolve',
               aresolve_mock):
        cfg, inherited, blocked = await LLMService.aget_knowledge_llm_with_meta(
            tenant_id=5,
        )
    assert cfg.embedding_model_id == 1
    assert inherited is True
    assert blocked is False


@pytest.mark.asyncio
async def test_get_assistant_llm_returns_typed_config_only():
    """Backward compat: get_assistant_llm still returns a single value
    even though it goes through the with_meta path internally."""
    from bisheng.llm.domain.services.llm import LLMService

    aresolve_mock = AsyncMock(return_value=(None, False, False))
    with patch('bisheng.llm.domain.services.llm.TenantSystemModelConfigDao.aresolve',
               aresolve_mock):
        cfg = await LLMService.get_assistant_llm(tenant_id=5)
    # Empty config: AssistantLLMConfig defaults
    assert cfg.llm_list == []


@pytest.mark.asyncio
async def test_aget_workflow_llm_with_meta_blocked_by_root():
    """AC-06 surface: blocked=True propagates."""
    from bisheng.llm.domain.services.llm import LLMService

    aresolve_mock = AsyncMock(return_value=(None, False, True))
    with patch('bisheng.llm.domain.services.llm.TenantSystemModelConfigDao.aresolve',
               aresolve_mock):
        cfg, inherited, blocked = await LLMService.aget_workflow_llm_with_meta(
            tenant_id=5,
        )
    assert inherited is False
    assert blocked is True


# --- sync_get_*_llm sync resolve --------------------------------------------


def test_sync_get_assistant_llm_routes_to_sync_resolve():
    from bisheng.llm.domain.services.llm import LLMService

    resolve_mock = MagicMock(return_value=(json.dumps({'llm_list': []}), False, False))
    with patch('bisheng.llm.domain.services.llm.TenantSystemModelConfigDao.resolve',
               resolve_mock):
        cfg = LLMService.sync_get_assistant_llm(tenant_id=5)
    assert cfg.llm_list == []
    resolve_mock.assert_called_once_with(
        tenant_id=5, key=ConfigKeyEnum.ASSISTANT_LLM.value,
    )


# --- update_*_llm goes through aupsert -------------------------------------


@pytest.mark.asyncio
async def test_update_knowledge_llm_writes_via_aupsert():
    from bisheng.llm.domain.schemas import KnowledgeLLMConfig
    from bisheng.llm.domain.services.llm import LLMService

    payload = KnowledgeLLMConfig(embedding_model_id=42)
    aupsert_mock = AsyncMock()
    with patch('bisheng.llm.domain.services.llm.TenantSystemModelConfigDao.aupsert',
               aupsert_mock):
        result = await LLMService.update_knowledge_llm(payload, tenant_id=5)
    assert result is payload
    aupsert_mock.assert_awaited_once()
    call_kwargs = aupsert_mock.call_args.kwargs
    assert call_kwargs['tenant_id'] == 5
    assert call_kwargs['key'] == ConfigKeyEnum.KNOWLEDGE_LLM.value
    assert json.loads(call_kwargs['value'])['embedding_model_id'] == 42


@pytest.mark.asyncio
async def test_update_assistant_llm_default_tenant_falls_back_to_context():
    from bisheng.llm.domain.schemas import AssistantLLMConfig
    from bisheng.llm.domain.services.llm import LLMService

    payload = AssistantLLMConfig(llm_list=[])
    aupsert_mock = AsyncMock()
    with patch('bisheng.llm.domain.services.llm.TenantSystemModelConfigDao.aupsert',
               aupsert_mock), \
         patch('bisheng.llm.domain.services.llm.get_current_tenant_id',
               return_value=7):
        await LLMService.update_assistant_llm(payload)  # no tenant_id arg
    assert aupsert_mock.call_args.kwargs['tenant_id'] == 7


@pytest.mark.asyncio
async def test_update_evaluation_llm_writes_with_tenant():
    from bisheng.llm.domain.schemas import EvaluationLLMConfig
    from bisheng.llm.domain.services.llm import LLMService

    payload = EvaluationLLMConfig(model_id=12)
    aupsert_mock = AsyncMock()
    with patch('bisheng.llm.domain.services.llm.TenantSystemModelConfigDao.aupsert',
               aupsert_mock):
        await LLMService.update_evaluation_llm(payload, tenant_id=8)
    call_kwargs = aupsert_mock.call_args.kwargs
    assert call_kwargs['tenant_id'] == 8
    assert call_kwargs['key'] == ConfigKeyEnum.EVALUATION_LLM.value


@pytest.mark.asyncio
async def test_update_workflow_llm_writes_with_tenant():
    from bisheng.llm.domain.schemas import EvaluationLLMConfig
    from bisheng.llm.domain.services.llm import LLMService

    payload = EvaluationLLMConfig(model_id=13)
    aupsert_mock = AsyncMock()
    with patch('bisheng.llm.domain.services.llm.TenantSystemModelConfigDao.aupsert',
               aupsert_mock):
        await LLMService.update_workflow_llm(payload, tenant_id=9)
    call_kwargs = aupsert_mock.call_args.kwargs
    assert call_kwargs['tenant_id'] == 9
    assert call_kwargs['key'] == ConfigKeyEnum.WORKFLOW_LLM.value
