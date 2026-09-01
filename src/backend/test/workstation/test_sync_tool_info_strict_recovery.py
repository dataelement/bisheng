"""A narrowed tenant filter must not read back as "the admin deleted the tools".

``sync_tool_info`` drops tool groups it cannot find — that is how a real
deletion reaches saved configs. The trap is that the tenant auto-filter produces
the same "not found" for the config owner's own rows whenever the request's
visible-tenant IN-list excludes that tenant. The 工作台配置 page round-trips what
it is shown, so one filtered read would persist as a cleared tool pool — the
narrower survivor of the 2026-08-13 incident, after the config body itself was
protected by the resolve-level fix.

So an unresolved group triggers a re-read pinned to the config's own tenant
(``strict_tenant_filter`` narrows to ``tenant_id = current``; it never widens),
and only a drop that survives *that* is believed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bisheng.core.context.tenant import is_strict_tenant_filter
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.workstation.domain.services.workstation_service import WorkStationService

ROOT = 1
OTHER = 36

TYPES = {
    16: SimpleNamespace(id=16, name="联网搜索", is_preset=1, description="搜索互联网信息"),
    6: SimpleNamespace(id=6, name="代码执行器", is_preset=1, description="执行代码"),
}
CHILDREN = {
    38: SimpleNamespace(id=38, type=16, name="联网搜索", tool_key="web_search", desc="联网检索"),
    6: SimpleNamespace(id=6, type=6, name="代码执行器", tool_key="bisheng_code_interpreter", desc="执行 Python"),
}

STORED = [
    {"id": 16, "name": "联网搜索", "default_checked": True, "children": [{"id": 38, "tool_key": "web_search"}]},
    {
        "id": 6,
        "name": "代码执行器",
        "default_checked": False,
        "children": [{"id": 6, "tool_key": "bisheng_code_interpreter"}],
    },
]


def _patch_dao(monkeypatch: pytest.MonkeyPatch, visible: set[int] | None, types: dict = TYPES) -> None:
    """DAO stand-ins that honour a visible-tenant IN-list unless pinned strict.

    All rows belong to Root, mirroring the incident: the request's IN-list did
    not contain Root, so Root's own tools read back empty.
    """

    def _readable() -> bool:
        return is_strict_tenant_filter() or visible is None or ROOT in visible

    monkeypatch.setattr(
        GptsToolsDao,
        "get_all_tool_type",
        staticmethod(lambda type_ids: [types[t] for t in type_ids if t in types] if _readable() else []),
    )
    monkeypatch.setattr(
        GptsToolsDao,
        "get_list_by_type",
        staticmethod(lambda type_ids: [c for c in CHILDREN.values() if c.type in type_ids] if _readable() else []),
    )


def _group_ids(tools: list[dict]) -> list[int]:
    return [t["id"] for t in tools]


def test_visible_set_containing_the_owner_resolves_normally(monkeypatch):
    _patch_dao(monkeypatch, visible={ROOT})
    assert _group_ids(WorkStationService.sync_tool_info(STORED)) == [16, 6]


def test_visible_set_excluding_the_owner_no_longer_clears_the_pool(monkeypatch):
    """The incident shape: current tenant is Root, the IN-list is not."""
    _patch_dao(monkeypatch, visible={OTHER})

    synced = WorkStationService.sync_tool_info(STORED)

    assert _group_ids(synced) == [16, 6], "a filtered read must not look like a deleted tool pool"
    assert [c["tool_key"] for t in synced for c in t["children"]] == [
        "web_search",
        "bisheng_code_interpreter",
    ]


def test_genuinely_deleted_group_is_still_dropped(monkeypatch):
    """The strict re-read is a recovery path, not a resurrection path."""
    _patch_dao(monkeypatch, visible=None, types={16: TYPES[16]})  # tool type 6 really is gone

    assert _group_ids(WorkStationService.sync_tool_info(STORED)) == [16]


def test_everything_deleted_returns_empty(monkeypatch):
    _patch_dao(monkeypatch, visible=None, types={})

    assert WorkStationService.sync_tool_info(STORED) == []


def test_empty_input_is_untouched(monkeypatch):
    _patch_dao(monkeypatch, visible=None)

    assert WorkStationService.sync_tool_info([]) == []
