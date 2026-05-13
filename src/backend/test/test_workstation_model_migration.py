from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.v1.schemas import WorkstationConfig
from bisheng.llm.domain.schemas import WSModel, WorkbenchModelConfig
from bisheng.workstation.domain.services.workstation_service import WorkStationService


@pytest.mark.asyncio
async def test_update_daily_chat_config_ignores_models_field(monkeypatch):
    saved = {}

    async def fake_insert_or_update_config(key, value):
        saved['config_key'] = key
        saved['config_value'] = value
        return SimpleNamespace(key=key, value=value)

    result_config = WorkstationConfig(
        models=[WSModel(id='101', name='gpt-4o', displayName='GPT-4o', visual=True)],
    )

    monkeypatch.setattr(
        'bisheng.workstation.domain.services.workstation_service.ConfigDao.insert_or_update_config',
        fake_insert_or_update_config,
    )
    monkeypatch.setattr(
        WorkStationService,
        'get_daily_chat_config',
        AsyncMock(return_value=result_config),
    )

    result = await WorkStationService.update_daily_chat_config(result_config)

    assert '"models": null' in saved['config_value']
    assert result.models == result_config.models
    assert result.models[0].visual is True


def test_apply_workbench_models_returns_minimal_config_when_only_models_exist():
    workbench_config = WorkbenchModelConfig(
        models=[WSModel(id='101', name='qwen-max', displayName='Qwen Max', visual=True)],
    )

    result = WorkStationService._apply_workbench_models(None, workbench_config)

    assert result is not None
    assert result.models is not None
    assert result.models[0].id == '101'
    assert result.models[0].visual is True
    assert result.systemPrompt is None
    assert result.welcomeMessage == ''
    assert result.model_dump(exclude_unset=True) == {
        'models': [{'id': '101', 'name': 'qwen-max', 'displayName': 'Qwen Max', 'visual': True}],
    }


def test_apply_workbench_models_returns_none_when_both_configs_absent():
    result = WorkStationService._apply_workbench_models(None, None)

    assert result is None
