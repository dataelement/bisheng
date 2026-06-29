"""Tests for ``SgUsersSyncService`` — SG user sync."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.sso_sync.domain.schemas.sg_payloads import (
    SgUserFieldItem,
    SgUserSyncRequest,
)

MODULE = "bisheng.sso_sync.domain.services.sg_users_sync_service"


def _dept(*, dept_id: int = 200):
    return SimpleNamespace(id=dept_id, external_id="DEPT1")


def _user(*, user_id: int = 9, external_id: str = "U1"):
    return SimpleNamespace(
        user_id=user_id,
        external_id=external_id,
        user_name="Old Name",
        dept_id="1",
        remark="Old",
        delete=0,
        disable_source=None,
    )


def _request(*fields: SgUserFieldItem, mdm_id: int = 99):
    return SgUserSyncRequest(
        mdmId=mdm_id,
        BusinessSystem=1,
        uuid="user-batch",
        Field=list(fields),
    )


def _fake_user_class():
    class FakeUser:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
            self.user_id = None

    return FakeUser


@pytest.mark.asyncio
class TestSgUsersSyncService:
    async def test_create_new_user_success(self):
        from bisheng.sso_sync.domain.services.sg_users_sync_service import (
            SgUsersSyncService,
        )

        payload = _request(
            SgUserFieldItem(
                uuid="u1",
                code="U1",
                desc34="DEPT1",
                desc1="Alice",
                desc93="01",
            ),
        )

        async def fake_add_user(user):
            user.user_id = 9
            return user

        with (
            patch(f"{MODULE}.User", _fake_user_class()),
            patch(
                f"{MODULE}.DepartmentDao.aget_by_source_external_id",
                new_callable=AsyncMock,
                return_value=_dept(),
            ),
            patch(
                f"{MODULE}.UserDao.aget_by_source_external_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                f"{MODULE}.UserDao.add_user_and_default_role",
                new_callable=AsyncMock,
                side_effect=fake_add_user,
            ) as add_user,
            patch(
                f"{MODULE}.UserDepartmentDao.aget_user_primary_department",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                f"{MODULE}.UserDepartmentDao.aget_membership",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                f"{MODULE}.UserDepartmentDao.aadd_member",
                new_callable=AsyncMock,
            ) as add_member,
            patch(
                f"{MODULE}.DepartmentChangeHandler.on_members_added",
                return_value=[],
            ),
            patch(
                f"{MODULE}.DepartmentChangeHandler.execute_async",
                new_callable=AsyncMock,
            ),
        ):
            response = await SgUsersSyncService.execute(payload)

        assert response.esb.code == "0"
        info = response.esb.data.data_infos.data_info[0]
        assert info.status == "0"
        assert info.code == "U1"
        created = add_user.await_args.args[0]
        assert created.external_id == "U1"
        assert created.user_name == "Alice"
        assert created.dept_id == "200"
        assert created.delete == 0
        add_member.assert_awaited_once_with(
            9,
            200,
            is_primary=1,
            source=SgUsersSyncService.SOURCE,
        )

    async def test_update_existing_user_success(self):
        from bisheng.sso_sync.domain.services.sg_users_sync_service import (
            SgUsersSyncService,
        )

        existing = _user()
        payload = _request(
            SgUserFieldItem(
                uuid="u1",
                code="U1",
                desc34="DEPT1",
                desc1="Alice Updated",
                desc93="01",
            ),
        )
        with (
            patch(
                f"{MODULE}.DepartmentDao.aget_by_source_external_id",
                new_callable=AsyncMock,
                return_value=_dept(),
            ),
            patch(
                f"{MODULE}.UserDao.aget_by_source_external_id",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                f"{MODULE}.UserDao.aupdate_user",
                new_callable=AsyncMock,
            ) as update_user,
            patch(
                f"{MODULE}.UserDepartmentDao.aget_user_primary_department",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                f"{MODULE}.UserDepartmentDao.aget_membership",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                f"{MODULE}.UserDepartmentDao.aadd_member",
                new_callable=AsyncMock,
            ) as add_member,
            patch(
                f"{MODULE}.DepartmentChangeHandler.on_members_added",
                return_value=[],
            ),
            patch(
                f"{MODULE}.DepartmentChangeHandler.execute_async",
                new_callable=AsyncMock,
            ),
        ):
            response = await SgUsersSyncService.execute(payload)

        assert response.esb.code == "0"
        update_user.assert_awaited_once()
        updated = update_user.await_args.args[0]
        assert updated.remark == "Alice Updated"
        assert updated.dept_id == "200"
        assert updated.delete == 0
        assert updated.disable_source is None
        add_member.assert_awaited_once_with(
            9,
            200,
            is_primary=1,
            source=SgUsersSyncService.SOURCE,
        )

    async def test_off_job_user_sets_delete_and_disable_source(self):
        from bisheng.sso_sync.domain.services.sg_users_sync_service import (
            SgUsersSyncService,
        )

        existing = _user()
        payload = _request(
            SgUserFieldItem(
                uuid="u1",
                code="U1",
                desc34="DEPT1",
                desc1="Alice",
                desc93="02",
            ),
        )
        membership = SimpleNamespace(
            department_id=200,
            source=SgUsersSyncService.SOURCE,
        )
        with (
            patch(
                f"{MODULE}.DepartmentDao.aget_by_source_external_id",
                new_callable=AsyncMock,
                return_value=_dept(),
            ),
            patch(
                f"{MODULE}.UserDao.aget_by_source_external_id",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                f"{MODULE}.UserDao.aupdate_user",
                new_callable=AsyncMock,
            ) as update_user,
            patch(
                f"{MODULE}.UserDepartmentDao.aget_user_departments",
                new_callable=AsyncMock,
                return_value=[membership],
            ),
            patch(
                f"{MODULE}.UserDepartmentDao.aremove_member",
                new_callable=AsyncMock,
            ) as remove_member,
            patch(
                f"{MODULE}.DepartmentChangeHandler.on_member_removed",
                return_value=["member-removed"],
            ) as member_removed,
            patch(
                f"{MODULE}.DepartmentChangeHandler.on_admin_removed",
                return_value=["admin-removed"],
            ),
            patch(
                f"{MODULE}.DepartmentChangeHandler.execute_async",
                new_callable=AsyncMock,
            ) as execute_async,
            patch(
                f"{MODULE}.DepartmentAdminGrantDao.adelete",
                new_callable=AsyncMock,
            ) as delete_grant,
            patch(
                f"{MODULE}.UserDepartmentDao.aadd_member",
                new_callable=AsyncMock,
            ) as add_member,
            patch(
                f"{MODULE}.DepartmentChangeHandler.on_members_added",
                return_value=[],
            ),
        ):
            response = await SgUsersSyncService.execute(payload)

        assert response.esb.code == "0"
        updated = update_user.await_args.args[0]
        assert updated.delete == 1
        assert updated.disable_source == "sg_sync"
        remove_member.assert_awaited_once_with(9, 200)
        member_removed.assert_called_once_with(200, 9)
        execute_async.assert_awaited_once()
        delete_grant.assert_awaited_once_with(9, 200)
        add_member.assert_not_awaited()

    async def test_department_not_found_marks_row_failed(self):
        from bisheng.sso_sync.domain.services.sg_users_sync_service import (
            SgUsersSyncService,
        )

        payload = _request(
            SgUserFieldItem(
                uuid="u1",
                code="U1",
                desc34="MISSING",
                desc1="Bob",
                desc93="01",
            ),
        )
        with (
            patch(
                f"{MODULE}.DepartmentDao.aget_by_source_external_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                f"{MODULE}.DepartmentDao.aget_by_external_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            response = await SgUsersSyncService.execute(payload)

        assert response.esb.code == "1"
        info = response.esb.data.data_infos.data_info[0]
        assert info.status == "1"
        assert "department external_id=MISSING not found" in info.error_text

    async def test_missing_desc34_returns_validation_failure(self):
        from bisheng.sso_sync.domain.services.sg_users_sync_service import (
            SgUsersSyncService,
        )

        payload = _request(
            SgUserFieldItem(uuid="u1", code="U1", desc34="", desc93="01"),
        )
        response = await SgUsersSyncService.execute(payload)

        assert response.esb.code == "1"
        info = response.esb.data.data_infos.data_info[0]
        assert info.status == "1"
        assert "desc34 is required" in info.error_text

    async def test_invalid_desc93_returns_validation_failure(self):
        from bisheng.sso_sync.domain.services.sg_users_sync_service import (
            SgUsersSyncService,
        )

        payload = _request(
            SgUserFieldItem(
                uuid="u1",
                code="U1",
                desc34="DEPT1",
                desc93="99",
            ),
        )
        response = await SgUsersSyncService.execute(payload)

        assert response.esb.code == "1"
        info = response.esb.data.data_infos.data_info[0]
        assert "desc93 must be 01(on-job) or 02(off-job)" in info.error_text

    async def test_ensure_primary_membership_adds_new_row(self):
        from bisheng.sso_sync.domain.services.sg_users_sync_service import (
            SgUsersSyncService,
        )

        with (
            patch(
                f"{MODULE}.UserDepartmentDao.aget_user_primary_department",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                f"{MODULE}.UserDepartmentDao.aget_membership",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                f"{MODULE}.UserDepartmentDao.aadd_member",
                new_callable=AsyncMock,
            ) as add_member,
            patch(
                f"{MODULE}.SgUsersSyncService._sync_department_member_tuples",
                new_callable=AsyncMock,
            ) as sync_tuples,
        ):
            await SgUsersSyncService._ensure_primary_membership(9, 200)

        add_member.assert_awaited_once_with(
            9,
            200,
            is_primary=1,
            source=SgUsersSyncService.SOURCE,
        )
        sync_tuples.assert_awaited_once_with(9, [200])

    async def test_ensure_primary_membership_removes_old_department_on_change(self):
        from bisheng.sso_sync.domain.services.sg_users_sync_service import (
            SgUsersSyncService,
        )

        old_primary = SimpleNamespace(department_id=100)
        with (
            patch(
                f"{MODULE}.UserDepartmentDao.aget_user_primary_department",
                new_callable=AsyncMock,
                return_value=old_primary,
            ),
            patch.object(
                SgUsersSyncService,
                "_remove_department_membership",
                new_callable=AsyncMock,
            ) as remove_membership,
            patch(
                f"{MODULE}.UserDepartmentDao.aget_membership",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                f"{MODULE}.UserDepartmentDao.aadd_member",
                new_callable=AsyncMock,
            ) as add_member,
            patch(
                f"{MODULE}.SgUsersSyncService._sync_department_member_tuples",
                new_callable=AsyncMock,
            ) as sync_tuples,
        ):
            await SgUsersSyncService._ensure_primary_membership(9, 200)

        remove_membership.assert_awaited_once_with(9, 100)
        add_member.assert_awaited_once_with(
            9,
            200,
            is_primary=1,
            source=SgUsersSyncService.SOURCE,
        )
        sync_tuples.assert_awaited_once_with(9, [200])

    async def test_remove_department_membership_clears_fga_and_admin_grant(self):
        from bisheng.sso_sync.domain.services.sg_users_sync_service import (
            SgUsersSyncService,
        )

        with (
            patch(
                f"{MODULE}.UserDepartmentDao.aremove_member",
                new_callable=AsyncMock,
            ) as remove_member,
            patch(
                f"{MODULE}.DepartmentChangeHandler.on_member_removed",
                return_value=["member-removed"],
            ) as member_removed,
            patch(
                f"{MODULE}.DepartmentChangeHandler.on_admin_removed",
                return_value=["admin-removed"],
            ) as admin_removed,
            patch(
                f"{MODULE}.DepartmentChangeHandler.execute_async",
                new_callable=AsyncMock,
            ) as execute_async,
            patch(
                f"{MODULE}.DepartmentAdminGrantDao.adelete",
                new_callable=AsyncMock,
            ) as delete_grant,
        ):
            await SgUsersSyncService._remove_department_membership(9, 200)

        remove_member.assert_awaited_once_with(9, 200)
        member_removed.assert_called_once_with(200, 9)
        admin_removed.assert_called_once_with(200, [9])
        execute_async.assert_awaited_once_with(["member-removed", "admin-removed"])
        delete_grant.assert_awaited_once_with(9, 200)
