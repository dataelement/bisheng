"""Canonical application permission template.

Applies to both workflow and assistant top-level app resources.
"""

from __future__ import annotations

from typing import Dict, List, Set

_RELATION_LEVEL: Dict[str, int] = {
    'can_read': 1,
    'can_edit': 2,
    'can_manage': 3,
    'can_delete': 4,
}

_MODEL_LEVEL: Dict[str, int] = {
    'viewer': 1,
    'editor': 2,
    'manager': 3,
    'owner': 4,
}

APPLICATION_PERMISSION_TEMPLATE: dict = {
    'title': '应用/工作流模块',
    'columns': [
        {
            'title': '',
            'items': [
                {'id': 'view_app', 'label': '查看应用', 'relation': 'can_read'},
                {'id': 'use_app', 'label': '使用应用', 'relation': 'can_read'},
                {'id': 'edit_app', 'label': '编辑应用', 'relation': 'can_edit'},
                {'id': 'delete_app', 'label': '删除应用', 'relation': 'can_delete'},
            ],
        },
        {
            'title': '',
            'items': [
                {'id': 'publish_app', 'label': '发布应用', 'relation': 'can_manage'},
                {'id': 'unpublish_app', 'label': '下线应用', 'relation': 'can_manage'},
                {'id': 'share_app', 'label': '分享应用', 'relation': 'can_manage'},
            ],
        },
        {
            'title': '',
            'items': [
                {'id': 'manage_app_owner', 'label': '管理应用所有者', 'relation': 'can_manage'},
                {'id': 'manage_app_manager', 'label': '管理应用管理者', 'relation': 'can_manage'},
                {'id': 'manage_app_viewer', 'label': '管理应用使用者', 'relation': 'can_manage'},
            ],
        },
    ],
}


def application_template_sections() -> List[dict]:
    return APPLICATION_PERMISSION_TEMPLATE['columns']


def application_template_permissions() -> List[dict]:
    return [
        item
        for column in application_template_sections()
        for item in column['items']
    ]


def default_permission_ids_for_relation(relation: str) -> Set[str]:
    relation_level = _MODEL_LEVEL.get(relation, 0)
    return {
        item['id']
        for item in application_template_permissions()
        if relation_level >= _RELATION_LEVEL.get(item['relation'], 99)
    }
