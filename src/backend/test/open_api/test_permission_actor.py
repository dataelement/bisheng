from types import SimpleNamespace

from bisheng.permission.application.identity import (
    reset_current_permission_actor,
    resolve_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor


def test_user_and_service_account_with_same_numeric_id_are_distinct():
    user = PermissionActor(subject_type="user", subject_id=7, tenant_id=3)
    account = PermissionActor(
        subject_type="service_account",
        subject_id=7,
        tenant_id=3,
        super_admin=True,
        tenant_admin_tenant_ids=frozenset({3}),
    )
    assert user != account
    assert user.fga_subject == "user:7"
    assert account.fga_subject == "service_account:7"
    assert account.super_admin is False
    assert account.tenant_admin_tenant_ids == frozenset()


def test_legacy_user_constructor_preserves_existing_behavior():
    actor = PermissionActor(user_id=7, current_tenant_id=3, super_admin=True)
    assert actor.subject_type == "user"
    assert actor.subject_id == actor.user_id == 7
    assert actor.tenant_id == actor.current_tenant_id == 3
    assert actor.super_admin is True


async def test_contextual_actor_wins_over_compatibility_login_user():
    service_account = PermissionActor(subject_type="service_account", subject_id=7, tenant_id=3)
    token = set_current_permission_actor(service_account)
    try:
        resolved = await resolve_permission_actor(SimpleNamespace(user_id=99, tenant_id=3, is_global_super=True))
    finally:
        reset_current_permission_actor(token)
    assert resolved is service_account
