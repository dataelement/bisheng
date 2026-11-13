"""覆盖 AC: AC-05, AC-06, AC-08, AC-09, AC-13。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.sso_sync import KunlianIdentityUnavailableError
from test.sso import test_kunlian_admission as fixtures

base_admission = fixtures.admission


@pytest.fixture(params=["fixed", "tenant_workspace_map", "directory_active_tenants"])
async def admission(request, base_admission):
    service = base_admission[0]
    service.config.login_scope_mode = request.param
    service.config.tenant_workspace_allowlist = {"external-a": ["fixture-workspace"]}
    if request.param != "fixed":
        service.config.allowed_tenant_id, service.config.allowed_workspace_ids = "", []
    return base_admission
session_store = fixtures.session_store
directory_store = fixtures.directory_store


@pytest.mark.parametrize("transport", ["HTTP", "WEBSOCKET"])
async def test_source_revocation_during_introspection_blocks_new_action(admission, transport):
    service, _, _, _, issued, _, _, users, _ = admission
    current = users.read_current_qualification.return_value
    service.onboarding = SimpleNamespace(
        current_qualification=AsyncMock(side_effect=[current, KunlianIdentityUnavailableError()])
    )
    with pytest.raises(KunlianIdentityUnavailableError):
        await service.admit_kunlian_session(issued.reference, fixtures.action(transport=transport))
    users.build_admitted_payload.assert_not_awaited()


async def test_payload_uses_roles_reread_after_network_round_trip(admission):
    service, _, _, _, issued, _, _, users, _ = admission
    initial = users.read_current_qualification.return_value
    latest = SimpleNamespace(user_id=101, user_name="最新名称", token_version=1, role_ids=(920,))
    users.read_current_qualification.side_effect = [initial, latest]
    await service.admit_kunlian_session(issued.reference, fixtures.action())
    assert users.build_admitted_payload.await_args.args[0] is latest


async def test_revoked_basic_access_without_other_entry_permission_is_denied(admission):
    from bisheng.common.errcode.user import UserNoRoleForLoginError

    service, _, _, _, issued, _, _, users, _ = admission
    current = SimpleNamespace(user_id=101, user_name="用户", token_version=1, role_ids=())
    service.onboarding = SimpleNamespace(current_qualification=AsyncMock(return_value=current))
    users.require_login_access = AsyncMock(side_effect=UserNoRoleForLoginError())
    with pytest.raises(KunlianIdentityUnavailableError):
        await service.admit_kunlian_session(issued.reference, fixtures.action())
    users.build_admitted_payload.assert_not_awaited()
