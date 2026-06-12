from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.tool.domain.services.executor import ToolExecutor


@pytest.mark.asyncio
async def test_init_by_tool_ids_can_skip_unauthorized_tools(monkeypatch):
    tool_one = SimpleNamespace(id=1, type=10)
    tool_two = SimpleNamespace(id=2, type=20)
    type_one = SimpleNamespace(id=10)
    type_two = SimpleNamespace(id=20)

    monkeypatch.setattr(
        'bisheng.tool.domain.services.executor.GptsToolsDao.aget_list_by_ids',
        AsyncMock(return_value=[tool_one, tool_two]),
    )
    monkeypatch.setattr(
        'bisheng.tool.domain.services.executor.GptsToolsDao.aget_all_tool_type',
        AsyncMock(return_value=[type_one, type_two]),
    )

    async def ensure_permission(tool_type, user_id):
        if tool_type.id == 20:
            raise PermissionError('no tool permission')

    monkeypatch.setattr(ToolExecutor, '_ensure_use_permission_async', ensure_permission)
    monkeypatch.setattr(
        ToolExecutor,
        '_init_by_tool_and_type',
        lambda tool, tool_type, **kwargs: f'tool:{tool.id}',
    )

    result = await ToolExecutor.init_by_tool_ids(
        [1, 2],
        app_id='assistant-1',
        app_name='assistant',
        app_type=ApplicationTypeEnum.ASSISTANT,
        user_id=7,
        skip_unauthorized=True,
    )

    assert result == ['tool:1']


@pytest.mark.asyncio
async def test_init_by_tool_ids_still_raises_by_default(monkeypatch):
    tool = SimpleNamespace(id=2, type=20)
    tool_type = SimpleNamespace(id=20)

    monkeypatch.setattr(
        'bisheng.tool.domain.services.executor.GptsToolsDao.aget_list_by_ids',
        AsyncMock(return_value=[tool]),
    )
    monkeypatch.setattr(
        'bisheng.tool.domain.services.executor.GptsToolsDao.aget_all_tool_type',
        AsyncMock(return_value=[tool_type]),
    )

    async def ensure_permission(tool_type, user_id):
        raise PermissionError('no tool permission')

    monkeypatch.setattr(ToolExecutor, '_ensure_use_permission_async', ensure_permission)

    with pytest.raises(PermissionError):
        await ToolExecutor.init_by_tool_ids(
            [2],
            app_id='direct-tool-use',
            app_name='direct',
            app_type=ApplicationTypeEnum.ASSISTANT,
            user_id=7,
        )
