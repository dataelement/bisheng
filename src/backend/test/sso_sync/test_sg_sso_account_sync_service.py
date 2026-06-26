"""Tests for ``SgSsoAccountSyncService`` — SG SSO account sync."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.sso_sync.domain.schemas.sg_payloads import (
    SgSsoAccountSyncRequest,
    SgSsoRowItem,
)

MODULE = "bisheng.sso_sync.domain.services.sg_sso_account_sync_service"


def _user(*, user_id: int = 5, guid: str | None = None, user_name: str = "Old"):
    return SimpleNamespace(
        user_id=user_id,
        external_id="P001",
        user_name=user_name,
        guid=guid,
    )


def _request(*rows: SgSsoRowItem):
    return SgSsoAccountSyncRequest(ROW=list(rows))


@pytest.mark.asyncio
class TestSgSsoAccountSyncService:
    async def test_resolve_user_by_person_no_and_update(self):
        from bisheng.sso_sync.domain.services.sg_sso_account_sync_service import (
            SgSsoAccountSyncService,
        )

        target = _user(guid="existing-guid")
        payload = _request(
            SgSsoRowItem(
                PersonNO="P001",
                UserName="New Name",
                Guid="existing-guid",
            ),
        )
        with (
            patch(
                f"{MODULE}.UserDao.aget_by_external_id",
                new_callable=AsyncMock,
                return_value=target,
            ),
            patch(
                f"{MODULE}.UserDao.aget_by_guid",
                new_callable=AsyncMock,
                return_value=target,
            ),
            patch(
                f"{MODULE}.UserDao.aupdate_user",
                new_callable=AsyncMock,
            ) as update_user,
        ):
            response = await SgSsoAccountSyncService.execute(payload)

        assert len(response.items) == 1
        item = response.items[0]
        assert item.result == "0"
        assert item.user_name == "New Name"
        assert item.guid == "existing-guid"
        updated = update_user.await_args.args[0]
        assert updated.user_name == "New Name"
        assert updated.guid == "existing-guid"

    async def test_fallback_resolve_user_by_guid(self):
        from bisheng.sso_sync.domain.services.sg_sso_account_sync_service import (
            SgSsoAccountSyncService,
        )

        target = _user(guid="guid-only")
        payload = _request(
            SgSsoRowItem(
                PersonNO="P001",
                UserName="Guid User",
                Guid="guid-only",
            ),
        )
        with (
            patch(
                f"{MODULE}.UserDao.aget_by_external_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                f"{MODULE}.UserDao.aget_by_guid",
                new_callable=AsyncMock,
                return_value=target,
            ),
            patch(
                f"{MODULE}.UserDao.aupdate_user",
                new_callable=AsyncMock,
            ),
        ):
            response = await SgSsoAccountSyncService.execute(payload)

        assert response.items[0].result == "0"
        assert response.items[0].guid == "guid-only"

    async def test_empty_guid_generates_uuid(self):
        from bisheng.sso_sync.domain.services.sg_sso_account_sync_service import (
            SgSsoAccountSyncService,
        )

        target = _user(guid=None)
        payload = _request(
            SgSsoRowItem(PersonNO="P001", UserName="Alice", Guid=""),
        )
        with (
            patch(
                f"{MODULE}.UserDao.aget_by_external_id",
                new_callable=AsyncMock,
                return_value=target,
            ),
            patch(
                f"{MODULE}.UserDao.aget_by_guid",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                f"{MODULE}.UserDao.aupdate_user",
                new_callable=AsyncMock,
            ) as update_user,
        ):
            response = await SgSsoAccountSyncService.execute(payload)

        assert response.items[0].result == "0"
        generated = update_user.await_args.args[0].guid
        assert generated
        assert response.items[0].guid == generated

    async def test_empty_guid_preserves_existing_guid(self):
        from bisheng.sso_sync.domain.services.sg_sso_account_sync_service import (
            SgSsoAccountSyncService,
        )

        target = _user(guid="stable-guid")
        payload = _request(
            SgSsoRowItem(PersonNO="P001", UserName="Alice", Guid=""),
        )
        with (
            patch(
                f"{MODULE}.UserDao.aget_by_external_id",
                new_callable=AsyncMock,
                return_value=target,
            ),
            patch(
                f"{MODULE}.UserDao.aget_by_guid",
                new_callable=AsyncMock,
                return_value=target,
            ),
            patch(
                f"{MODULE}.UserDao.aupdate_user",
                new_callable=AsyncMock,
            ) as update_user,
            patch(
                f"{MODULE}.SgSsoAccountSyncService._generate_unique_guid",
                new_callable=AsyncMock,
            ) as generate_guid,
        ):
            response = await SgSsoAccountSyncService.execute(payload)

        assert response.items[0].result == "0"
        assert response.items[0].guid == "stable-guid"
        updated = update_user.await_args.args[0]
        assert updated.guid == "stable-guid"
        generate_guid.assert_not_awaited()

    async def test_user_not_found_returns_failure_row(self):
        from bisheng.sso_sync.domain.services.sg_sso_account_sync_service import (
            SgSsoAccountSyncService,
        )

        payload = _request(
            SgSsoRowItem(PersonNO="MISSING", UserName="Nobody", Guid=""),
        )
        with (
            patch(
                f"{MODULE}.UserDao.aget_by_external_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                f"{MODULE}.UserDao.aget_by_guid",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            response = await SgSsoAccountSyncService.execute(payload)

        item = response.items[0]
        assert item.result == "1"
        assert "user not found by PersonNO or Guid" in item.description

    async def test_guid_bound_to_other_user_fails(self):
        from bisheng.sso_sync.domain.services.sg_sso_account_sync_service import (
            SgSsoAccountSyncService,
        )

        target = _user(user_id=5)
        other = _user(user_id=99, guid="taken-guid")
        payload = _request(
            SgSsoRowItem(
                PersonNO="P001",
                UserName="Alice",
                Guid="taken-guid",
            ),
        )
        with (
            patch(
                f"{MODULE}.UserDao.aget_by_external_id",
                new_callable=AsyncMock,
                return_value=target,
            ),
            patch(
                f"{MODULE}.UserDao.aget_by_guid",
                new_callable=AsyncMock,
                return_value=other,
            ),
        ):
            response = await SgSsoAccountSyncService.execute(payload)

        item = response.items[0]
        assert item.result == "1"
        assert "Guid already bound to another user" in item.description

    async def test_missing_person_no_returns_validation_failure(self):
        from bisheng.sso_sync.domain.services.sg_sso_account_sync_service import (
            SgSsoAccountSyncService,
        )

        payload = _request(
            SgSsoRowItem(PersonNO="", UserName="Alice", Guid=""),
        )
        response = await SgSsoAccountSyncService.execute(payload)

        item = response.items[0]
        assert item.result == "1"
        assert "PersonNO is required" in item.description
