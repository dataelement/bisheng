from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.department.domain.schemas.department_schema import DepartmentUpdate
from bisheng.department.domain.services import department_service as department_module
from bisheng.department.domain.services.department_service import DepartmentService


class _EmptyResult:
    def first(self):
        return None


@pytest.mark.parametrize(
    ("requested_name", "expected_calls"),
    [
        ("新部门", 1),
        ("原部门", 0),
    ],
)
@pytest.mark.asyncio
async def test_department_name_change_only_enqueues_when_name_changed(
    monkeypatch,
    requested_name,
    expected_calls,
):
    department = SimpleNamespace(
        id=7,
        name="原部门",
        short_name=None,
        default_role_ids=[],
        parent_id=1,
        source="local",
        status="active",
    )
    session = SimpleNamespace(
        exec=AsyncMock(return_value=_EmptyResult()),
        add=lambda _value: None,
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )

    @asynccontextmanager
    async def fake_session():
        yield session

    async def get_department(_session, _dept_id, _login_user):
        return department

    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(department_module, "get_async_db_session", fake_session)
    monkeypatch.setattr(
        department_module,
        "_get_dept_and_check_permission",
        get_department,
    )
    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.knowledge_space_content."
        "KnowledgeSpaceContentStat.enqueue_department_stat_async",
        enqueue,
    )

    result = await DepartmentService.aupdate_department(
        "BS@7",
        DepartmentUpdate(name=requested_name),
        SimpleNamespace(user_id=1),
    )

    assert result.name == requested_name
    assert enqueue.await_count == expected_calls
    if expected_calls:
        enqueue.assert_awaited_once_with([7])
