"""Canonical knowledge-library permission template.

This module is the backend source of truth for top-level knowledge-library
permission ids. The legacy filelib/QA runtime is not wired to consume these
ids yet; this template exists so relation-model persistence can target the
correct resource family while migration work catches up.
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
_COMPUTED_TO_MODEL_RELATION: Dict[str, str] = {
    'can_read': 'viewer',
    'can_edit': 'editor',
    'can_manage': 'manager',
    'can_delete': 'owner',
}

KNOWLEDGE_LIBRARY_PERMISSION_TEMPLATE: dict = {
    'title': '知识库模块',
    'columns': [
        {
            'title': '',
            'items': [
                {'id': 'view_kb', 'label': '查看知识库', 'relation': 'can_read'},
                {'id': 'use_kb', 'label': '使用知识库', 'relation': 'can_read'},
                {'id': 'edit_kb', 'label': '编辑知识库', 'relation': 'can_edit'},
                {'id': 'delete_kb', 'label': '删除知识库', 'relation': 'can_delete'},
            ],
        },
        {
            'title': '',
            'items': [
                {'id': 'manage_kb_owner', 'label': '管理知识库所有者', 'relation': 'can_manage'},
                {'id': 'manage_kb_manager', 'label': '管理知识库管理者', 'relation': 'can_manage'},
                {'id': 'manage_kb_viewer', 'label': '管理知识库使用者', 'relation': 'can_manage'},
            ],
        },
    ],
}


def knowledge_library_template_sections() -> List[dict]:
    return KNOWLEDGE_LIBRARY_PERMISSION_TEMPLATE['columns']


def knowledge_library_template_permissions() -> List[dict]:
    return [
        item
        for column in knowledge_library_template_sections()
        for item in column['items']
    ]


def default_permission_ids_for_relation(relation: str) -> Set[str]:
    normalized = _COMPUTED_TO_MODEL_RELATION.get(relation, relation)
    relation_level = _MODEL_LEVEL.get(normalized, 0)
    return {
        item['id']
        for item in knowledge_library_template_permissions()
        if relation_level >= _RELATION_LEVEL.get(item['relation'], 99)
    }
