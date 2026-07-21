from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.user.domain.repositories.implementations.user_repository_impl import (
    UserRepositoryImpl,
)
from bisheng.user.domain.services.user import UserService


class _Result:
    def __init__(self, value: str | None) -> None:
        self.value = value

    def first(self) -> str | None:
        return self.value


class _Session:
    def __init__(self, value: str | None) -> None:
        self.value = value
        self.statements = []

    async def exec(self, statement):
        self.statements.append(statement)
        return _Result(self.value)


@pytest.mark.asyncio
async def test_user_repository_returns_trimmed_primary_department_name() -> None:
    session = _Session(" 设备管理部 ")
    repository = UserRepositoryImpl(session)

    department_name = await repository.get_primary_department_name(7)

    assert department_name == "设备管理部"
    statement = str(session.statements[0])
    assert "user_department.is_primary" in statement
    assert "user_department.user_id" in statement


@pytest.mark.asyncio
async def test_user_repository_returns_none_without_primary_department() -> None:
    repository = UserRepositoryImpl(_Session(None))

    assert await repository.get_primary_department_name(7) is None


@pytest.mark.asyncio
async def test_user_service_resolves_primary_department_name(monkeypatch) -> None:
    monkeypatch.setattr(
        UserDepartmentDao,
        "aget_user_primary_department",
        AsyncMock(return_value=SimpleNamespace(department_id=12)),
    )
    monkeypatch.setattr(
        DepartmentDao,
        "aget_by_id",
        AsyncMock(return_value=SimpleNamespace(name=" 设备管理部 ")),
    )

    assert await UserService.get_primary_department_name(7) == "设备管理部"


@pytest.mark.asyncio
async def test_user_service_returns_none_without_primary_department(monkeypatch) -> None:
    monkeypatch.setattr(
        UserDepartmentDao,
        "aget_user_primary_department",
        AsyncMock(return_value=None),
    )
    department_lookup = AsyncMock()
    monkeypatch.setattr(DepartmentDao, "aget_by_id", department_lookup)

    assert await UserService.get_primary_department_name(7) is None
    department_lookup.assert_not_awaited()


def test_user_info_endpoint_exposes_primary_department_name() -> None:
    source = Path("bisheng/user/api/user.py").read_text(encoding="utf-8")

    assert "UserService.get_primary_department_name(user_id)" in source
    assert "department_name=department_name" in source
