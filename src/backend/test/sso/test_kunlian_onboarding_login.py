"""覆盖 AC: AC-05, AC-06, AC-07, AC-09, AC-13。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.sso_sync import KunlianDirectoryNotReadyError
from bisheng.sso_sync.domain.models.kunlian import KunlianTenantBinding
from test.sso import test_kunlian_login_contract as fixtures

login = fixtures.login
projection = fixtures.projection
owner = fixtures.owner
directory_store = fixtures.directory_store


async def test_missing_auto_access_requests_sync_without_issuing_session(login):
    call, service, _, _, _, requested, _, _, signed, _, _, _ = login
    service.onboarding = SimpleNamespace(current_qualification=AsyncMock(side_effect=KunlianDirectoryNotReadyError()))
    with pytest.raises(KunlianDirectoryNotReadyError):
        await call()
    requested.request_directory_sync.assert_awaited_once()
    assert not signed


async def test_missing_mapping_is_not_ready_and_does_not_create_on_login(login):
    call, _, _, _, _, requested, _, controls, signed, _, _, _ = login
    async with controls() as session:
        mapping = await session.get(KunlianTenantBinding, ("fixture", "external-a"))
        await session.delete(mapping)
        await session.commit()
    with pytest.raises(KunlianDirectoryNotReadyError):
        await call()
    requested.request_directory_sync.assert_awaited_once()
    assert not signed
