"""``/user/list`` returns an empty page, not a 500, when the caller manages nobody.

The endpoint gates on organisational roles — super admin, user-group admin,
department admin, sub-tenant admin. A user who merely holds `manage_permission`
on a resource is none of those, so opening the grant picker for a knowledge space
they administer answered 500 "Quit that! You don't have rights to view this." and
the dialog was unusable: allowed to manage the permissions, unable to list a
single person to grant them to.

"No organisational scope" and "an empty organisational scope" are the same fact
to the caller, and the neighbouring branch already returned an empty page for the
latter.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

_MODULE = "bisheng.user.api.user"


class _LoginUser:
    user_id = 42

    def is_admin(self) -> bool:
        return False


async def _list(*, dept_scope, tenant_scope, admin_groups=()):
    from bisheng.user.api.user import list_user

    with (
        patch(f"{_MODULE}.UserGroupDao") as group_dao,
        patch(f"{_MODULE}._department_admin_scoped_user_ids", new=AsyncMock(return_value=dept_scope)),
        patch(f"{_MODULE}._tenant_admin_scoped_user_ids", new=AsyncMock(return_value=tenant_scope)),
    ):
        group_dao.get_user_admin_group.return_value = [
            type("Row", (), {"group_id": group_id})() for group_id in admin_groups
        ]
        return await list_user(login_user=_LoginUser())


@pytest.mark.parametrize(
    ("dept_scope", "tenant_scope"),
    [
        (None, None),  # neither department nor sub-tenant admin — used to 500
        (set(), None),
        (None, set()),
        (set(), set()),
    ],
)
async def test_no_manageable_users_is_an_empty_page(dept_scope, tenant_scope) -> None:
    response = await _list(dept_scope=dept_scope, tenant_scope=tenant_scope)

    assert response.data == {"data": [], "total": 0}


async def test_the_endpoint_no_longer_refuses_a_scopeless_caller() -> None:
    """Guard the specific regression: it must not raise at all."""

    try:
        await _list(dept_scope=None, tenant_scope=None)
    except HTTPException as exc:  # pragma: no cover - the point of the test
        pytest.fail(f"scopeless caller was refused: {exc.detail}")
