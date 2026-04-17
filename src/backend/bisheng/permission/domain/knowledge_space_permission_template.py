"""Canonical knowledge-space permission template.

This module is the backend source of truth for knowledge-space permission ids.
Runtime authorization and future frontend permission UIs should both derive from
this definition instead of maintaining duplicated lists.
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

KNOWLEDGE_SPACE_PERMISSION_TEMPLATE: dict = {
    'title': '知识空间模块',
    'columns': [
        {
            'title': '空间级',
            'items': [
                {'id': 'view_space', 'label': '查看空间', 'relation': 'can_read'},
                {'id': 'edit_space', 'label': '编辑空间信息', 'relation': 'can_edit'},
                {'id': 'delete_space', 'label': '删除空间', 'relation': 'can_delete'},
                {'id': 'share_space', 'label': '分享空间', 'relation': 'can_manage'},
                {'id': 'manage_space_relation', 'label': '管理空间协作者', 'relation': 'can_manage'},
            ],
        },
        {
            'title': '文件夹级',
            'items': [
                {'id': 'view_folder', 'label': '查看文件夹', 'relation': 'can_read'},
                {'id': 'create_folder', 'label': '创建文件夹', 'relation': 'can_edit'},
                {'id': 'rename_folder', 'label': '重命名文件夹', 'relation': 'can_edit'},
                {'id': 'delete_folder', 'label': '删除文件夹', 'relation': 'can_delete'},
                {'id': 'download_folder', 'label': '下载文件夹', 'relation': 'can_read'},
                {'id': 'manage_folder_relation', 'label': '管理文件夹协作者', 'relation': 'can_manage'},
            ],
        },
        {
            'title': '文件级',
            'items': [
                {'id': 'view_file', 'label': '查看文件', 'relation': 'can_read'},
                {'id': 'upload_file', 'label': '上传文件', 'relation': 'can_edit'},
                {'id': 'rename_file', 'label': '重命名文件', 'relation': 'can_edit'},
                {'id': 'delete_file', 'label': '删除文件', 'relation': 'can_delete'},
                {'id': 'download_file', 'label': '下载文件', 'relation': 'can_read'},
                {'id': 'share_file', 'label': '分享文件', 'relation': 'can_manage'},
                {'id': 'manage_file_relation', 'label': '管理文件协作者', 'relation': 'can_manage'},
            ],
        },
    ],
}


def knowledge_space_template_sections() -> List[dict]:
    """Return the grouped template for UI-style rendering."""
    return KNOWLEDGE_SPACE_PERMISSION_TEMPLATE['columns']


def knowledge_space_template_permissions() -> List[dict]:
    """Flatten the grouped template into a simple permission list."""
    return [
        item
        for column in knowledge_space_template_sections()
        for item in column['items']
    ]


def default_permission_ids_for_relation(relation: str) -> Set[str]:
    """System-model default permissions for owner/manager/editor/viewer.

    This is a compatibility helper for built-in relation models. Custom models
    should prefer their explicit permissions[] instead of these defaults.
    """
    relation_level = _MODEL_LEVEL.get(relation, 0)
    return {
        item['id']
        for item in knowledge_space_template_permissions()
        if relation_level >= _RELATION_LEVEL.get(item['relation'], 99)
    }
