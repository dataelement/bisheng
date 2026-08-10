from __future__ import annotations

from types import SimpleNamespace

import pytest

from bisheng.department.domain.services.department_display_service import (
    build_department_name_projection,
    department_display_sort_key,
    get_department_display_name,
)


@pytest.mark.parametrize(
    ("short_name", "expected"),
    [
        ("  研发  ", "研发"),
        (None, "技术研发中心"),
        ("", "技术研发中心"),
        ("   ", "技术研发中心"),
    ],
)
def test_display_name_prefers_trimmed_short_name_and_falls_back_to_name(
    short_name: str | None,
    expected: str,
) -> None:
    assert get_department_display_name("技术研发中心", short_name) == expected


def test_projection_preserves_official_name_and_exposes_display_fields() -> None:
    department = SimpleNamespace(id=18, name="技术研发中心", short_name="  研发  ")

    projection = build_department_name_projection(department)

    assert projection.department_id == 18
    assert projection.name == "技术研发中心"
    assert projection.short_name == "研发"
    assert projection.display_name == "研发"


def test_duplicate_short_names_are_allowed_and_sort_order_is_deterministic() -> None:
    departments = [
        SimpleNamespace(id=20, name="制造二部", short_name="制造"),
        SimpleNamespace(id=18, name="制造一部", short_name="制造"),
        SimpleNamespace(id=30, name="安全管理部", short_name=None),
    ]

    ordered = sorted(departments, key=department_display_sort_key)

    assert [department.id for department in ordered] == [18, 20, 30]
    assert [get_department_display_name(item.name, item.short_name) for item in ordered] == [
        "制造",
        "制造",
        "安全管理部",
    ]
