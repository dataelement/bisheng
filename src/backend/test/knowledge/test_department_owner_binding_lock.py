"""The canonical binding is fenced before any owner/member side effect."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge_space import SpaceAdminConflictError, SpaceNotFoundError
from bisheng.knowledge.domain.repositories import department_space_owner_repository as repository


@pytest.mark.parametrize(
    "actual,expected,excluded,error",
    [
        (2, 3, None, SpaceAdminConflictError),
        (2, None, 2, SpaceAdminConflictError),
        (None, 2, None, SpaceNotFoundError),
        (2, 2, None, None),
    ],
)
async def test_stale_or_reselected_admin_is_rejected_under_lock(monkeypatch, actual, expected, excluded, error):
    binding = SimpleNamespace(admin_user_id=actual) if actual is not None else None
    entered = False

    @asynccontextmanager
    async def transaction():
        nonlocal entered
        entered = True
        try:
            yield
        finally:
            entered = False

    session = SimpleNamespace(begin=transaction, exec=AsyncMock(return_value=SimpleNamespace(first=lambda: binding)))

    @asynccontextmanager
    async def sessions():
        yield session

    monkeypatch.setattr(repository, "get_async_db_session", sessions)
    if error:
        with pytest.raises(error):
            async with repository.DepartmentSpaceOwnerRepository.lock_binding(
                42, expected_admin_user_id=expected, excluded_admin_user_id=excluded
            ):
                pytest.fail("A stale operation reached its permission side effects")
    else:
        async with repository.DepartmentSpaceOwnerRepository.lock_binding(
            42, expected_admin_user_id=expected, excluded_admin_user_id=excluded
        ):
            assert entered
            assert session.exec.await_args.args[0]._for_update_arg is not None
    assert not entered
