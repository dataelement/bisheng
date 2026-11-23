"""T282: explicit assistant model IDs never silently select another default."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.services import assistant_agent as agent_module
from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.common.errcode.assistant import AssistantModelNotConfigError
from bisheng.database.models.assistant import Assistant


@pytest.fixture
def configured_models(monkeypatch):
    models = [
        SimpleNamespace(
            model_id=model_id,
            default=model_id == 1,
            agent_executor_type="function call",
            knowledge_max_content=15000,
            knowledge_sort_index=False,
            streaming=True,
        )
        for model_id in (1, 2)
    ]
    monkeypatch.setattr(
        agent_module.LLMService, "get_assistant_llm", AsyncMock(return_value=SimpleNamespace(llm_list=models))
    )
    invoke = AsyncMock(return_value=object())
    monkeypatch.setattr(agent_module.LLMService, "get_bisheng_llm", invoke)
    return invoke


async def test_missing_explicit_model_never_falls_back_to_another_default(configured_models):
    agent = AssistantAgent(Assistant(id="assistant-a", model_name="99", tenant_id=101), "", 7)
    with pytest.raises(AssistantModelNotConfigError):
        await agent.init_llm()
    configured_models.assert_not_awaited()


@pytest.mark.parametrize("model_name", ["", None])
async def test_empty_selection_preserves_business_default_resolution(configured_models, model_name):
    agent = AssistantAgent(Assistant(id="assistant-a", model_name=model_name, tenant_id=101), "", 7)
    await agent.init_llm()
    assert configured_models.call_args.kwargs["model_id"] == 1


async def test_explicit_model_selection_keeps_its_exact_configured_id(configured_models):
    agent = AssistantAgent(Assistant(id="assistant-a", model_name="2", tenant_id=101), "", 7)
    await agent.init_llm()
    assert configured_models.call_args.kwargs["model_id"] == 2
