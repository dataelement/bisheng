"""Canonical tool permission template."""

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
_COMPUTED_TO_MODEL_RELATION: Dict[str, str] = {
    'can_read': 'viewer',
    'can_edit': 'editor',
    'can_manage': 'manager',
    'can_delete': 'owner',
}

TOOL_PERMISSION_TEMPLATE: dict = {
    'title': '工具模块',
    'columns': [
        {
            'title': '',
            'items': [
                {'id': 'view_tool', 'label': '查看工具', 'relation': 'can_read'},
                {'id': 'use_tool', 'label': '使用工具', 'relation': 'can_read'},
                {'id': 'edit_tool', 'label': '编辑工具', 'relation': 'can_edit'},
                {'id': 'delete_tool', 'label': '删除工具', 'relation': 'can_delete'},
            ],
        },
        {
            'title': '',
            'items': [
                {'id': 'manage_tool_owner', 'label': '管理工具所有者', 'relation': 'can_manage'},
                {'id': 'manage_tool_manager', 'label': '管理工具管理者', 'relation': 'can_manage'},
                {'id': 'manage_tool_viewer', 'label': '管理工具使用者', 'relation': 'can_manage'},
            ],
        },
    ],
}


def tool_template_sections() -> List[dict]:
    return TOOL_PERMISSION_TEMPLATE['columns']


def tool_template_permissions() -> List[dict]:
    return [
        item
        for column in tool_template_sections()
        for item in column['items']
    ]


def default_permission_ids_for_relation(relation: str) -> Set[str]:
    normalized = _COMPUTED_TO_MODEL_RELATION.get(relation, relation)
    relation_level = _MODEL_LEVEL.get(normalized, 0)
    return {
        item['id']
        for item in tool_template_permissions()
        if relation_level >= _RELATION_LEVEL.get(item['relation'], 99)
    }
