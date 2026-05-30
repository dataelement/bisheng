from __future__ import annotations

from bisheng.permission.domain.channel_permission_template import (
    CHANNEL_PERMISSION_TEMPLATE,
    can_channel_actor_grant_relation,
    default_permission_ids_for_relation,
    validate_channel_grant_subject,
)
from bisheng.permission.domain.services.fine_grained_permission_service import (
    FineGrainedPermissionService,
)


def test_channel_permission_template_contains_management_permissions():
    permission_ids = {
        item['id']
        for column in CHANNEL_PERMISSION_TEMPLATE['columns']
        for item in column['items']
    }

    assert {
        'view_channel',
        'edit_channel',
        'delete_channel',
        'manage_channel_owner',
        'manage_channel_manager',
        'manage_channel_user',
    }.issubset(permission_ids)
    assert 'create_channel' not in permission_ids


def test_channel_default_permissions_follow_relation_pyramid():
    assert default_permission_ids_for_relation('viewer') == {'view_channel'}
    assert default_permission_ids_for_relation('editor') == {
        'view_channel',
        'edit_channel',
    }
    assert default_permission_ids_for_relation('manager') == {
        'view_channel',
        'edit_channel',
        'manage_channel_user',
    }
    assert default_permission_ids_for_relation('owner') == {
        'view_channel',
        'edit_channel',
        'delete_channel',
        'manage_channel_owner',
        'manage_channel_manager',
        'manage_channel_user',
    }


def test_fine_grained_permission_service_uses_channel_defaults():
    assert FineGrainedPermissionService.default_permission_ids_for_relation(
        'channel',
        'manager',
    ) == {
        'view_channel',
        'edit_channel',
        'manage_channel_user',
    }


def test_channel_grant_subject_validation_rejects_organization_owner():
    assert validate_channel_grant_subject('user', 'owner') is True
    assert validate_channel_grant_subject('department', 'owner') is False
    assert validate_channel_grant_subject('user_group', 'owner') is False


def test_channel_actor_grant_scope():
    assert can_channel_actor_grant_relation('owner', 'owner') is True
    assert can_channel_actor_grant_relation('owner', 'manager') is True
    assert can_channel_actor_grant_relation('manager', 'editor') is True
    assert can_channel_actor_grant_relation('manager', 'viewer') is True
    assert can_channel_actor_grant_relation('manager', 'manager') is False
    assert can_channel_actor_grant_relation('editor', 'viewer') is False
    assert can_channel_actor_grant_relation('viewer', 'viewer') is False
