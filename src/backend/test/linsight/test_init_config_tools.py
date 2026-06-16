"""Linsight tool init: code-interpreter whitelist source + missing-config safety.

Unified-resource direction (2026-06-16): task mode reuses the DAILY chat config
tool selection (``get_daily_chat_config``), not the legacy per-app linsight
config. ``init_linsight_config_tools`` reads that config to compute the
code-interpreter whitelist (``config_tool_ids``).

Two behaviours are pinned:
1. A missing/None daily config degrades gracefully (no code interpreter bound,
   user-selected tools still initialize) instead of crashing the whole task
   with ``'NoneType' object has no attribute 'tools'``.
2. The daily config's tools are pydantic ``ToolConfig`` models (the config
   re-validates ``tools`` on assignment), so ``_extract_tool_ids`` must tolerate
   models, not only raw dicts.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.v1.schemas import ToolConfig
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl
from bisheng.workstation.domain.services.workstation_service import WorkStationService


def _session_with_tools() -> LinsightSessionVersion:
    return LinsightSessionVersion(
        id="SV-1",
        session_id="chat-1",
        user_id=42,
        question="帮我写周报",
        tenant_id=7,
        tools=[{"children": [{"id": 100}]}],
    )


async def test_init_config_tools_when_daily_config_missing(monkeypatch: pytest.MonkeyPatch):
    """A None daily config must not crash tool init."""
    monkeypatch.setattr(WorkStationService, "get_daily_chat_config", AsyncMock(return_value=None))

    from bisheng.tool.domain.services.executor import ToolExecutor

    init_mock = AsyncMock(return_value=[object()])
    monkeypatch.setattr(ToolExecutor, "init_by_tool_ids", init_mock)

    tools = await LinsightWorkbenchImpl.init_linsight_config_tools(
        session_version=_session_with_tools(), llm=object(), need_upload=False, file_dir=None
    )

    # User-selected tool 100 still binds; code interpreter (config-gated) is skipped.
    assert len(tools) == 1
    assert init_mock.await_args.args[0] == [100]


def test_extract_tool_ids_tolerates_pydantic_models():
    """Daily config tools come back as ToolConfig models, not raw dicts."""
    model_tools = [ToolConfig(id=1, name="grp", children=[{"id": 11}, {"id": 12}])]
    assert LinsightWorkbenchImpl._extract_tool_ids(model_tools) == [11, 12]
    # raw-dict shape (session_version.tools / linsight config) still works
    assert LinsightWorkbenchImpl._extract_tool_ids([{"children": [{"id": 21}]}]) == [21]


async def test_init_config_tools_reads_code_interpreter_from_daily_config(monkeypatch: pytest.MonkeyPatch):
    """config_tool_ids for the code-interpreter branch comes from the daily config."""
    daily_cfg = SimpleNamespace(tools=[ToolConfig(id=1, name="grp", children=[{"id": 100}, {"id": 200}])])
    monkeypatch.setattr(WorkStationService, "get_daily_chat_config", AsyncMock(return_value=daily_cfg))

    captured = {}

    async def fake_code_tool(config_tool_ids, file_dir, user_id):
        captured["ids"] = list(config_tool_ids)
        return []

    monkeypatch.setattr(LinsightWorkbenchImpl, "_init_bisheng_code_tool", fake_code_tool)

    from bisheng.tool.domain.services.executor import ToolExecutor

    monkeypatch.setattr(ToolExecutor, "init_by_tool_ids", AsyncMock(return_value=[object()]))

    await LinsightWorkbenchImpl.init_linsight_config_tools(
        session_version=_session_with_tools(), llm=object(), need_upload=True, file_dir="/tmp/x"
    )

    assert captured["ids"] == [100, 200]
