"""Existing department-wide gate stays explicit; unrelated departments work."""

import pytest

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.department.domain.repositories.permission_context_repository import DepartmentContextRow
from bisheng.department.domain.services.permission_context import DepartmentPermissionContextProvider


@pytest.mark.parametrize("state", ["PROJECTING", "FAILED_CLOSED"])
async def test_member_change_closes_same_department_context_but_not_unrelated_department(state):
    rows = {
        1: DepartmentContextRow(1, None, 1, "active", "CURRENT"),
        11: DepartmentContextRow(11, 1, 1, "active", state),
        22: DepartmentContextRow(22, 1, 1, "active", "CURRENT"),
    }

    class Repository:
        async def load_ancestry(self, user_id, limit):
            return ((11,) if user_id in (31, 32) else (22,)), rows

    provider = DepartmentPermissionContextProvider(Repository())
    for user_id in (31, 32):
        with pytest.raises(PermissionPublishNotReadyError):
            await provider.load(user_id)
    assert (await provider.load(41)).subtree_department_ids == (1, 22)
    rows[11] = DepartmentContextRow(11, 1, 1, "active", "CURRENT")
    for user_id in (31, 32):
        assert (await provider.load(user_id)).subtree_department_ids == (1, 11)
