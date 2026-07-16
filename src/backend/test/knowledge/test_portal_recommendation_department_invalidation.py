from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.department.domain.services.department_service import DepartmentService


class _Result:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


@pytest.mark.asyncio
async def test_remove_primary_department_invalidates_recommendation_after_commit():
    membership = SimpleNamespace(user_id=9, department_id=20, is_primary=1)
    session = SimpleNamespace(
        exec=AsyncMock(return_value=_Result(membership)),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )

    @asynccontextmanager
    async def session_context():
        yield session

    department = SimpleNamespace(id=20, status="active")
    login_user = SimpleNamespace(user_id=1)
    with (
        patch(
            "bisheng.department.domain.services.department_service.get_async_db_session",
            side_effect=session_context,
        ),
        patch(
            "bisheng.department.domain.services.department_service._get_dept_and_check_permission",
            new_callable=AsyncMock,
            return_value=department,
        ),
        patch(
            "bisheng.department.domain.services.department_service.invalidate_portal_recommendation_users_best_effort",
        ) as invalidate,
        patch.object(
            __import__(
                "bisheng.department.domain.services.department_service",
                fromlist=["DepartmentChangeHandler"],
            ).DepartmentChangeHandler,
            "on_member_removed",
            return_value=[],
        ),
        patch.object(
            __import__(
                "bisheng.department.domain.services.department_service",
                fromlist=["DepartmentChangeHandler"],
            ).DepartmentChangeHandler,
            "on_admin_removed",
            return_value=[],
        ),
        patch.object(
            __import__(
                "bisheng.department.domain.services.department_service",
                fromlist=["DepartmentChangeHandler"],
            ).DepartmentChangeHandler,
            "execute_async",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.department.domain.services.department_service.DepartmentAdminGrantDao.adelete",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.knowledge.domain.services.department_knowledge_space_service.DepartmentKnowledgeSpaceService.sync_department_admin_memberships",
            new_callable=AsyncMock,
        ),
    ):
        await DepartmentService.aremove_member("D20", 9, login_user)

    session.commit.assert_awaited_once()
    invalidate.assert_called_once_with([9])


@pytest.mark.asyncio
async def test_remove_secondary_department_does_not_invalidate_recommendation():
    membership = SimpleNamespace(user_id=9, department_id=20, is_primary=0)
    session = SimpleNamespace(
        exec=AsyncMock(return_value=_Result(membership)),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )

    @asynccontextmanager
    async def session_context():
        yield session

    handler = __import__(
        "bisheng.department.domain.services.department_service",
        fromlist=["DepartmentChangeHandler"],
    ).DepartmentChangeHandler
    with (
        patch(
            "bisheng.department.domain.services.department_service.get_async_db_session",
            side_effect=session_context,
        ),
        patch(
            "bisheng.department.domain.services.department_service._get_dept_and_check_permission",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(id=20, status="active"),
        ),
        patch(
            "bisheng.department.domain.services.department_service.invalidate_portal_recommendation_users_best_effort",
        ) as invalidate,
        patch.object(handler, "on_member_removed", return_value=[]),
        patch.object(handler, "on_admin_removed", return_value=[]),
        patch.object(handler, "execute_async", new_callable=AsyncMock),
        patch(
            "bisheng.department.domain.services.department_service.DepartmentAdminGrantDao.adelete",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.knowledge.domain.services.department_knowledge_space_service.DepartmentKnowledgeSpaceService.sync_department_admin_memberships",
            new_callable=AsyncMock,
        ),
    ):
        await DepartmentService.aremove_member("D20", 9, SimpleNamespace(user_id=1))

    invalidate.assert_not_called()
