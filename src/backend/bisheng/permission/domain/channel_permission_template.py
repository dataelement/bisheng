from __future__ import annotations

from typing import Dict, List, Set

CHANNEL_PERMISSION_TEMPLATE: dict = {
    'title': '频道模块',
    'columns': [
        {
            'title': '频道级',
            'items': [
                {'id': 'view_channel', 'label': '查看频道', 'relation': 'can_read'},
                {'id': 'edit_channel', 'label': '编辑频道设置', 'relation': 'can_edit'},
                {'id': 'delete_channel', 'label': '删除频道', 'relation': 'can_delete'},
                {'id': 'manage_channel_owner', 'label': '管理频道所有者', 'relation': 'owner'},
                {'id': 'manage_channel_manager', 'label': '管理频道管理者', 'relation': 'owner'},
                {'id': 'manage_channel_user', 'label': '管理频道使用者', 'relation': 'can_manage'},
            ],
        },
    ],
}

_DEFAULT_PERMISSION_IDS_BY_RELATION: Dict[str, Set[str]] = {
    'owner': {
        'view_channel',
        'edit_channel',
        'delete_channel',
        'manage_channel_owner',
        'manage_channel_manager',
        'manage_channel_user',
    },
    'manager': {
        'view_channel',
        'edit_channel',
        'manage_channel_user',
    },
    'editor': {'view_channel', 'edit_channel'},
    'viewer': {'view_channel'},
}

_COMPUTED_TO_MODEL_RELATION: Dict[str, str] = {
    'can_read': 'viewer',
    'can_edit': 'editor',
    'can_manage': 'manager',
    'can_delete': 'owner',
}


def channel_template_sections() -> List[dict]:
    return CHANNEL_PERMISSION_TEMPLATE['columns']


def channel_template_permissions() -> List[dict]:
    return [
        item
        for column in channel_template_sections()
        for item in column['items']
    ]


def default_permission_ids_for_relation(relation: str) -> Set[str]:
    normalized = _COMPUTED_TO_MODEL_RELATION.get(relation, relation)
    return set(_DEFAULT_PERMISSION_IDS_BY_RELATION.get(normalized, set()))


def validate_channel_grant_subject(subject_type: str, relation: str) -> bool:
    return not (relation == 'owner' and subject_type != 'user')


def can_channel_actor_grant_relation(actor_relation: str, target_relation: str) -> bool:
    if actor_relation == 'owner':
        return target_relation in {'owner', 'manager', 'editor', 'viewer'}
    if actor_relation == 'manager':
        return target_relation in {'editor', 'viewer'}
    return False
