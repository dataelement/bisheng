"""``get_daily_chat_config_with_meta`` must say when it fabricated a default.

The 工作台配置 page round-trips whatever the GET hands it, so it needs to tell a
saved config from the built-in default the service invents when nothing
resolves. Without that signal a single failed read turns into a permanent
overwrite the moment an admin hits 保存 (2026-08-13). ``is_fallback`` is the
contract the page's save guard is built on — keep it honest.
"""

from __future__ import annotations

import pytest

from bisheng.api.v1.schemas import WorkstationConfig
from bisheng.llm.domain.services.llm import LLMService
from bisheng.workstation.domain.services.workstation_service import WorkStationService

STORED = '{"welcomeMessage": "saved"}'


@pytest.fixture(autouse=True)
def _neutralize_side_lookups(monkeypatch: pytest.MonkeyPatch):
    """Keep the test on the resolve path: no DB, no tool sync, no LLM config."""
    monkeypatch.setattr(WorkStationService, "sync_tool_info", classmethod(lambda cls, tools: tools))
    monkeypatch.setattr(LLMService, "get_workbench_llm", staticmethod(_none))
    monkeypatch.setattr(
        WorkStationService,
        "_abuild_default_daily_config",
        classmethod(lambda cls: _config(WorkstationConfig(welcomeMessage="built-in default"))),
    )


async def test_saved_config_is_not_flagged_as_fallback(monkeypatch):
    monkeypatch.setattr(
        WorkStationService,
        "_aresolve_tenant_config",
        classmethod(lambda cls, key: _tuple((STORED, False, 1, True))),
    )

    (
        ret,
        inherited,
        source_tenant_id,
        has_override,
        is_fallback,
    ) = await WorkStationService.get_daily_chat_config_with_meta()

    assert ret.welcomeMessage == "saved"
    assert (inherited, source_tenant_id, has_override) == (False, 1, True)
    assert is_fallback is False


async def test_missing_config_is_flagged_as_fallback(monkeypatch):
    monkeypatch.setattr(
        WorkStationService,
        "_aresolve_tenant_config",
        classmethod(lambda cls, key: _tuple((None, False, 1, False))),
    )

    ret, _inherited, _source, has_override, is_fallback = await WorkStationService.get_daily_chat_config_with_meta()

    assert ret.welcomeMessage == "built-in default"
    assert has_override is False
    assert is_fallback is True, "a fabricated default must never look like the admin's saved config"


async def _none():
    return None


async def _tuple(value):
    return value


async def _config(value):
    return value
