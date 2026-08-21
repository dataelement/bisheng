"""Canonical tool permission template."""

from __future__ import annotations

from typing import Dict, List, Set

# NOTE: keep these tier lists in lockstep with the channel template
# (channel_permission_template._DEFAULT_PERMISSION_IDS_BY_RELATION) so a
# "manager" subject never inherits the "manage_*_owner" permission by default —
# that would let a manager add or remove owners, breaking the owner/manager
# hierarchy. The previous level-based calculation gave can_manage-level managers
# the owner-tier manage permission as well (IKABS3).
_DEFAULT_PERMISSION_IDS_BY_RELATION: Dict[str, Set[str]] = {
    'owner': {
        'view_tool',
        'use_tool',
        'edit_tool',
        'delete_tool',
        'manage_tool_owner',
        'manage_tool_manager',
        'manage_tool_viewer',
    },
    'manager': {
        'view_tool',
        'use_tool',
        'edit_tool',
        'manage_tool_manager',
        'manage_tool_viewer',
    },
    'editor': {
        'view_tool',
        'use_tool',
        'edit_tool',
    },
    'viewer': {
        'view_tool',
    },
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
                {'id': 'manage_tool_viewer', 'label': '管理工具编辑者与使用者', 'relation': 'can_manage'},
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
    """System-model default permissions for owner/manager/editor/viewer.

    A manager is intentionally denied ``manage_tool_owner`` so the manager
    cannot add or remove owners — only the owner can. This mirrors the
    channel and application templates.
    """
    return set(_DEFAULT_PERMISSION_IDS_BY_RELATION.get(relation, set()))
