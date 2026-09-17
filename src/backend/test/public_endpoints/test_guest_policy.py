from types import SimpleNamespace

import pytest

from bisheng.common.errcode.public_endpoints import (
    PublicGuestAccessDisabledError,
)
from bisheng.core.context.tenant import get_current_tenant_id, get_visible_tenant_ids
from bisheng.permission.application.identity import (
    get_current_permission_actor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.public_endpoints.domain.context import get_current_public_api_principal
from bisheng.public_endpoints.domain.services import guest_policy


@pytest.fixture
def operator_identity(monkeypatch):
    """Stub the identity lookups ``_load_default_operator`` depends on.

    Defaults describe an ordinary account: no roles, not a super admin, not a
    tenant admin. Tests flip one knob at a time.
    """

    state = SimpleNamespace(role_ids=[], is_global_super=False, is_tenant_admin=False)

    async def aget_user_roles(_user_id):
        return [SimpleNamespace(role_id=r) for r in state.role_ids]

    async def check_is_global_super(_user_id, role_ids=None):
        del role_ids
        return state.is_global_super

    async def is_tenant_admin(_user_id, _tenant_id):
        return state.is_tenant_admin

    monkeypatch.setattr("bisheng.user.domain.services.auth.UserRoleDao.aget_user_roles", aget_user_roles)
    monkeypatch.setattr("bisheng.utils.http_middleware._check_is_global_super", check_is_global_super)
    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", is_tenant_admin)
    return state


@pytest.fixture
def guest_config(monkeypatch):
    """Stub the config row plus the operator liveness lookups."""

    state = SimpleNamespace(
        enable_guest_access=True,
        user=41,
        user_row=SimpleNamespace(user_id=41, user_name="guest", delete=0),
        membership=SimpleNamespace(status="active"),
        tenant=SimpleNamespace(status="active"),
    )

    async def config(_key):
        return {"user": state.user, "enable_guest_access": state.enable_guest_access}

    async def aget_user(_user_id):
        return state.user_row

    async def aget_user_tenant(_user_id, _tenant_id):
        return state.membership

    async def aget_by_id(_tenant_id):
        return state.tenant

    monkeypatch.setattr(guest_policy, "settings", SimpleNamespace(aget_from_db=config))
    monkeypatch.setattr(guest_policy.UserDao, "aget_user", aget_user)
    monkeypatch.setattr(guest_policy.UserTenantDao, "aget_user_tenant", aget_user_tenant)
    monkeypatch.setattr(guest_policy.TenantDao, "aget_by_id", aget_by_id)
    return state


@pytest.mark.asyncio
async def test_public_execution_sets_and_resets_strict_identity(monkeypatch) -> None:
    resource = SimpleNamespace(tenant_id=23)
    operator = SimpleNamespace(user_id=41, user_name="guest", tenant_id=23, is_global_super=False)

    async def load_resource(resource_type, resource_id):
        assert (resource_type, resource_id) == ("workflow", "flow-1")
        return resource

    async def load_operator(tenant_id):
        assert tenant_id == 23
        return operator

    async def is_tenant_admin(_user_id, _tenant_id):
        return False

    monkeypatch.setattr(guest_policy, "_load_published_resource", load_resource)
    monkeypatch.setattr(guest_policy, "_load_default_operator", load_operator)
    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", is_tenant_admin)

    assert get_current_tenant_id() is None
    async with guest_policy.public_execution("workflow", "flow-1") as execution:
        assert get_current_tenant_id() == 23
        assert get_visible_tenant_ids() == frozenset({23})
        assert execution.snapshot.channel == "public_v3"
        assert execution.snapshot.credential_id is None
        assert execution.session_subject.subject_type == "public_v3"
        assert get_current_permission_actor().fga_subject == "user:41"
        assert get_current_permission_actor().super_admin is False
        assert get_current_public_api_principal().resource_id == "flow-1"

    assert get_current_tenant_id() is None
    assert get_visible_tenant_ids() is None
    assert get_current_permission_actor() is None
    assert get_current_public_api_principal() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("is_global_super", "tenant_admin", "expected_super", "expected_tenant_admin"),
    [
        # A super-admin operator hands guests the short-circuit. That is the
        # point: the operator's reach IS the visitor's reach.
        (True, False, True, frozenset()),
        (False, False, False, frozenset()),
        (False, True, False, frozenset({23})),
    ],
    ids=["super_admin", "plain_account", "tenant_admin"],
)
async def test_guest_actor_tracks_operator_privilege(
    monkeypatch, is_global_super, tenant_admin, expected_super, expected_tenant_admin
) -> None:
    operator = SimpleNamespace(user_id=41, tenant_id=23, is_global_super=is_global_super)
    calls = []

    async def is_tenant_admin(user_id, tenant_id):
        calls.append((user_id, tenant_id))
        return tenant_admin

    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", is_tenant_admin)

    actor = await guest_policy._resolve_guest_actor(operator)

    assert actor.super_admin is expected_super
    assert actor.tenant_admin_tenant_ids == expected_tenant_admin
    assert actor.fga_subject == "user:41"
    # A super admin needs no tenant-admin lookup; asserting it keeps the
    # short-circuit from silently becoming an extra FGA round trip.
    assert calls == ([] if is_global_super else [(41, 23)])


@pytest.mark.asyncio
async def test_guest_actor_never_inherits_an_ambient_actor(monkeypatch) -> None:
    """An anonymous channel must not adopt whatever identity is already installed."""

    resource = SimpleNamespace(tenant_id=23)
    operator = SimpleNamespace(user_id=41, user_name="guest", tenant_id=23, is_global_super=False)

    async def load_resource(_resource_type, _resource_id):
        return resource

    async def load_operator(_tenant_id):
        return operator

    async def is_tenant_admin(_user_id, _tenant_id):
        return False

    monkeypatch.setattr(guest_policy, "_load_published_resource", load_resource)
    monkeypatch.setattr(guest_policy, "_load_default_operator", load_operator)
    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", is_tenant_admin)

    outer = PermissionActor(subject_type="user", subject_id=999, tenant_id=7, super_admin=True)
    token = set_current_permission_actor(outer)
    try:
        async with guest_policy.public_execution("workflow", "flow-1"):
            inside = get_current_permission_actor()
            assert inside.fga_subject == "user:41"
            assert inside.tenant_id == 23
            assert inside.super_admin is False
        # The ambient actor is restored, not cleared.
        assert get_current_permission_actor() is outer
    finally:
        reset_current_permission_actor(token)


@pytest.mark.asyncio
async def test_default_operator_carries_real_roles_and_super_flag(guest_config, operator_identity) -> None:
    """Pins the decision: the operator's real identity, never a stripped one."""

    operator_identity.role_ids = [7, 9]
    operator_identity.is_global_super = True

    operator = await guest_policy._load_default_operator(23)

    assert operator.user_id == 41
    assert operator.user_role == [7, 9]
    assert operator.is_global_super is True
    # Pinned to the resource's tenant, not the operator's own active tenant.
    assert operator.tenant_id == 23


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "break_it",
    [
        pytest.param(lambda s: setattr(s, "enable_guest_access", False), id="guest_disabled"),
        pytest.param(lambda s: setattr(s, "user", 0), id="operator_unset"),
        pytest.param(lambda s: setattr(s, "user_row", None), id="operator_absent"),
        pytest.param(
            lambda s: setattr(s, "user_row", SimpleNamespace(user_id=41, user_name="g", delete=1)),
            id="operator_deleted",
        ),
        pytest.param(lambda s: setattr(s, "membership", None), id="not_a_member"),
        pytest.param(
            lambda s: setattr(s, "membership", SimpleNamespace(status="disabled")),
            id="membership_inactive",
        ),
        pytest.param(lambda s: setattr(s, "tenant", SimpleNamespace(status="disabled")), id="tenant_inactive"),
        pytest.param(lambda s: setattr(s, "tenant", None), id="tenant_absent"),
    ],
)
async def test_operator_liveness_fails_closed(guest_config, operator_identity, break_it) -> None:
    break_it(guest_config)
    resolved = []

    async def aget_user_roles(_user_id):
        resolved.append(_user_id)
        return []

    # Privilege resolution must never run for a rejected operator.
    import bisheng.user.domain.services.auth as auth_module

    original = auth_module.UserRoleDao.aget_user_roles
    auth_module.UserRoleDao.aget_user_roles = staticmethod(aget_user_roles)
    try:
        with pytest.raises(PublicGuestAccessDisabledError) as caught:
            await guest_policy._load_default_operator(23)
    finally:
        auth_module.UserRoleDao.aget_user_roles = original

    assert caught.value.http_status == 403
    assert caught.value.code == 26103
    assert resolved == []
