"""覆盖 AC: AC-05, AC-06, AC-07, AC-09, AC-13。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.sso_sync import KunlianDirectoryNotReadyError, KunlianIdentityUnavailableError
from bisheng.sso_sync.domain.models.kunlian import KunlianIdentityBinding, KunlianTenantBinding
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


@pytest.fixture(autouse=True, params=["fixed", "directory_active_tenants"])
def login_mode(request, login):
    service = login[1]
    service.config.login_scope_mode = request.param
    if request.param == "directory_active_tenants":
        service.config.allowed_tenant_id, service.config.allowed_workspace_ids = "", []


async def test_current_directory_mapping_is_the_only_local_tenant(login):
    call, _, _, _, _, _, _, _, signed, _, uid, _ = login
    result = await call()
    assert result.user_id == uid and result.tenant_id == 7
    assert signed


@pytest.mark.parametrize("failure", ["unknown", "disabled", "override", "pending", "mapping"])
async def test_scope_precheck_never_bypasses_current_source(login, failure):
    from dataclasses import replace

    call, _, _, _, idp, _, _, controls, signed, _, _, key = login
    if failure == "unknown":
        idp.verify_id_token.return_value = replace(idp.verify_id_token.return_value, subject="unknown-subject")
    else:
        async with controls() as session:
            binding = await session.get(KunlianIdentityBinding, key)
            if failure == "disabled":
                binding.admission_status = "DISABLED"
            elif failure == "override":
                binding.local_override = True
            elif failure == "pending":
                binding.projected_revision = None
            else:
                mapping = await session.get(KunlianTenantBinding, ("fixture", "external-a"))
                mapping.enabled = False
                session.add(mapping)
            session.add(binding)
            await session.commit()
    with pytest.raises((KunlianDirectoryNotReadyError, KunlianIdentityUnavailableError)):
        await call()
    assert not signed
