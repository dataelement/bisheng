"""T004 — department short-name resolver (F058, AC-04 / AC-11)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.telemetry_search.domain.services.department_label_resolver import resolve_short_name


async def test_resolves_by_department_id_exact(monkeypatch):
    from bisheng.telemetry_search.domain.services import department_label_resolver as module

    dept = SimpleNamespace(short_name="生产部", name="生产制造部")
    monkeypatch.setattr(module.DepartmentDao, "aget_by_id", AsyncMock(return_value=dept))

    result = await resolve_short_name(department_id=1, name_text="生产制造部")

    assert result == "生产部"


async def test_department_id_lookup_falls_back_to_name_when_no_short_name(monkeypatch):
    from bisheng.telemetry_search.domain.services import department_label_resolver as module

    dept = SimpleNamespace(short_name=None, name="安全环保监察部")
    monkeypatch.setattr(module.DepartmentDao, "aget_by_id", AsyncMock(return_value=dept))

    result = await resolve_short_name(department_id=2, name_text=None)

    assert result == "安全环保监察部"


async def test_resolves_by_unique_name_text_match(monkeypatch):
    from bisheng.telemetry_search.domain.services import department_label_resolver as module

    dept = SimpleNamespace(short_name="生产部", name="生产制造部")
    monkeypatch.setattr(module.DepartmentDao, "aget_by_name", AsyncMock(return_value=[dept]))

    result = await resolve_short_name(department_id=None, name_text="生产制造部")

    assert result == "生产部"


async def test_name_text_no_match_falls_back_to_original_text(monkeypatch):
    """Renamed/deleted department: name snapshot no longer resolves — return the snapshot text as-is."""
    from bisheng.telemetry_search.domain.services import department_label_resolver as module

    monkeypatch.setattr(module.DepartmentDao, "aget_by_name", AsyncMock(return_value=[]))

    result = await resolve_short_name(department_id=None, name_text="已撤销的旧部门")

    assert result == "已撤销的旧部门"


async def test_name_text_ambiguous_match_falls_back_to_original_text(monkeypatch):
    """Duplicate department names across the org tree: do not guess, return the original text."""
    from bisheng.telemetry_search.domain.services import department_label_resolver as module

    dupes = [
        SimpleNamespace(short_name="生产一", name="生产部"),
        SimpleNamespace(short_name="生产二", name="生产部"),
    ]
    monkeypatch.setattr(module.DepartmentDao, "aget_by_name", AsyncMock(return_value=dupes))

    result = await resolve_short_name(department_id=None, name_text="生产部")

    assert result == "生产部"


async def test_department_id_not_found_falls_back_to_name_text(monkeypatch):
    from bisheng.telemetry_search.domain.services import department_label_resolver as module

    monkeypatch.setattr(module.DepartmentDao, "aget_by_id", AsyncMock(return_value=None))

    result = await resolve_short_name(department_id=999, name_text="不存在的部门快照")

    assert result == "不存在的部门快照"


async def test_no_department_id_and_no_name_text_returns_empty_string():
    result = await resolve_short_name(department_id=None, name_text=None)

    assert result == ""
