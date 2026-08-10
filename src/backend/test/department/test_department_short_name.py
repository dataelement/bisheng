from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from bisheng.database.models.department import Department
from bisheng.department.domain.schemas.department_schema import (
    DepartmentCreate,
    DepartmentUpdate,
)
from bisheng.department.domain.services.department_service import DepartmentService

SERVICE_MODULE = "bisheng.department.domain.services.department_service"


class _Result:
    def __init__(self, value=None):
        self.value = value

    def first(self):
        return self.value

    def one(self):
        return self.value


class _Session:
    def __init__(self, results: list[_Result]):
        self.results = list(results)
        self.added: list[Department] = []

    async def exec(self, _statement):
        return self.results.pop(0)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        if self.added and self.added[-1].id is None:
            self.added[-1].id = 2

    async def refresh(self, _value):
        return None

    async def commit(self):
        return None


def _session_context(session: _Session):
    @asynccontextmanager
    async def _context():
        yield session

    return _context


def _department(**overrides) -> Department:
    values = {
        "id": 2,
        "dept_id": "BS@child",
        "name": "研发中心",
        "short_name": "研发",
        "parent_id": 1,
        "tenant_id": 1,
        "path": "/1/2/",
        "source": "local",
        "external_id": "BS@child",
        "status": "active",
    }
    values.update(overrides)
    return Department(**values)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_create_normalizes_empty_short_name_to_none(value) -> None:
    payload = DepartmentCreate(name="研发中心", parent_id=1, short_name=value)

    assert payload.short_name is None


def test_short_name_is_trimmed_and_validated_after_normalization() -> None:
    payload = DepartmentCreate(
        name="研发中心",
        parent_id=1,
        short_name=f"  {'研' * 64}  ",
    )

    assert payload.short_name == "研" * 64

    with pytest.raises(ValidationError):
        DepartmentCreate(
            name="研发中心",
            parent_id=1,
            short_name=f"  {'研' * 65}  ",
        )


def test_update_distinguishes_omitted_short_name_from_explicit_clear() -> None:
    omitted = DepartmentUpdate()
    cleared = DepartmentUpdate(short_name="   ")

    assert "short_name" not in omitted.model_fields_set
    assert "short_name" in cleared.model_fields_set
    assert cleared.short_name is None


async def test_create_persists_normalized_short_name() -> None:
    parent = _department(id=1, dept_id="BS@root", path="/1/", parent_id=None)
    session = _Session([_Result(parent), _Result(None), _Result(None)])
    login_user = SimpleNamespace(user_id=1, user_role=[1])

    with (
        patch(
            f"{SERVICE_MODULE}.get_async_db_session",
            _session_context(session),
        ),
        patch(f"{SERVICE_MODULE}._check_permission", new_callable=AsyncMock),
        patch(
            f"{SERVICE_MODULE}.DepartmentChangeHandler.execute_async",
            new_callable=AsyncMock,
        ),
    ):
        created = await DepartmentService.acreate_department(
            DepartmentCreate(
                name="研发中心",
                parent_id=1,
                short_name="  研发  ",
            ),
            login_user,
        )

    assert created.short_name == "研发"
    assert created.model_dump()["short_name"] == "研发"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (DepartmentUpdate(), "研发"),
        (DepartmentUpdate(short_name="  研究院  "), "研究院"),
        (DepartmentUpdate(short_name=None), None),
    ],
)
async def test_update_applies_short_name_three_state_contract(
    payload: DepartmentUpdate,
    expected: str | None,
) -> None:
    department = _department()
    session = _Session([_Result(department)])
    login_user = SimpleNamespace(user_id=1, user_role=[1])

    with (
        patch(
            f"{SERVICE_MODULE}.get_async_db_session",
            _session_context(session),
        ),
        patch(f"{SERVICE_MODULE}._check_permission", new_callable=AsyncMock),
    ):
        updated = await DepartmentService.aupdate_department(
            department.dept_id,
            payload,
            login_user,
        )

    assert updated.short_name == expected


async def test_synced_department_allows_short_name_only_update() -> None:
    department = _department(source="wecom")
    session = _Session([_Result(department)])
    login_user = SimpleNamespace(user_id=1, user_role=[1])

    with (
        patch(
            f"{SERVICE_MODULE}.get_async_db_session",
            _session_context(session),
        ),
        patch(f"{SERVICE_MODULE}._check_permission", new_callable=AsyncMock),
    ):
        updated = await DepartmentService.aupdate_department(
            department.dept_id,
            DepartmentUpdate(short_name="  华东  "),
            login_user,
        )

    assert updated.name == "研发中心"
    assert updated.short_name == "华东"
