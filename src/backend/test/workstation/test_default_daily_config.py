"""Fresh-install defaults for the daily workstation config.

``_abuild_default_daily_config`` is what a brand-new deployment sees before an
admin ever saves the 工作台 config. It must ship the two builtin tools the daily
chat and the linsight task mode are expected to work with out of the box — 联网搜索
and 代码执行器 — both pre-checked, and with the 技能管理 (skillEntry) toggle on.

The code interpreter now binds in task mode only when the user has it toggled on
(see test/linsight/test_init_config_tools.py), so shipping it pre-checked is what
keeps a fresh install able to produce Excel/图表 deliverables.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.workstation.domain.services.workstation_service import WorkStationService

_ROWS = {
    "web_search": SimpleNamespace(id=1, type=11, name="联网搜索", tool_key="web_search", desc="搜索互联网信息"),
    "bisheng_code_interpreter": SimpleNamespace(
        id=6, type=6, name="代码执行器", tool_key="bisheng_code_interpreter", desc="执行 Python 代码"
    ),
}

_TYPES = {
    11: SimpleNamespace(id=11, name="联网搜索", is_preset=1, description="搜索互联网信息"),
    6: SimpleNamespace(
        id=6, name="代码执行器", is_preset=1, description="通过执行代码完成图表绘制、文件处理等编程类操作"
    ),
}


def _patch_tool_lookups(monkeypatch: pytest.MonkeyPatch, rows: dict) -> None:
    monkeypatch.setattr(
        WorkStationService, "_lookup_builtin_tool", classmethod(lambda cls, tool_key: rows.get(tool_key))
    )
    monkeypatch.setattr(
        GptsToolsDao,
        "get_all_tool_type",
        staticmethod(lambda type_ids: [_TYPES[tid] for tid in type_ids if tid in _TYPES]),
    )


async def test_default_config_ships_web_search_and_code_interpreter(monkeypatch: pytest.MonkeyPatch):
    _patch_tool_lookups(monkeypatch, _ROWS)

    cfg = await WorkStationService._abuild_default_daily_config()

    assert [grp.name for grp in cfg.tools] == ["联网搜索", "代码执行器"]
    # Both pre-checked, so a fresh install has them toggled on in the input bar.
    assert all(grp.default_checked for grp in cfg.tools)
    # Each group carries the real GptsTools leaf id the executor resolves against.
    assert [grp.children[0]["tool_key"] for grp in cfg.tools] == ["web_search", "bisheng_code_interpreter"]


async def test_default_config_enables_skill_entry(monkeypatch: pytest.MonkeyPatch):
    _patch_tool_lookups(monkeypatch, _ROWS)

    cfg = await WorkStationService._abuild_default_daily_config()

    assert cfg.skillEntry is not None
    assert cfg.skillEntry.enabled is True


async def test_default_config_degrades_when_a_builtin_row_is_missing(monkeypatch: pytest.MonkeyPatch):
    """A missing builtin row drops that tool only — the config still builds."""
    _patch_tool_lookups(monkeypatch, {"web_search": _ROWS["web_search"]})

    cfg = await WorkStationService._abuild_default_daily_config()

    assert [grp.name for grp in cfg.tools] == ["联网搜索"]
    assert cfg.skillEntry.enabled is True


async def test_default_config_tools_none_when_no_builtin_rows(monkeypatch: pytest.MonkeyPatch):
    _patch_tool_lookups(monkeypatch, {})

    cfg = await WorkStationService._abuild_default_daily_config()

    # None (not []) keeps the historical "no tools configured" shape.
    assert cfg.tools is None
