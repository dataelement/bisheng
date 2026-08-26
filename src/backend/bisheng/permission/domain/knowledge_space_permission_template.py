"""Canonical knowledge-space permission template.

This module is the backend source of truth for knowledge-space permission ids.
Runtime authorization and future frontend permission UIs should both derive from
this definition instead of maintaining duplicated lists.
"""

from __future__ import annotations

_RELATION_LEVEL: dict[str, int] = {
    "can_read": 1,
    "can_edit": 2,
    "can_manage": 3,
    "can_delete": 4,
}

_MODEL_LEVEL: dict[str, int] = {
    "viewer": 1,
    "editor": 2,
    "manager": 3,
    "owner": 4,
}
_COMPUTED_TO_MODEL_RELATION: dict[str, str] = {
    "can_read": "viewer",
    "can_edit": "editor",
    "can_manage": "manager",
    "can_delete": "owner",
}

KNOWLEDGE_SPACE_PERMISSION_TEMPLATE: dict = {
    "title": "知识空间模块",
    "columns": [
        {
            "title": "空间级",
            "items": [
                {"id": "view_space", "label": "查看空间", "relation": "can_read"},
                {"id": "edit_space", "label": "编辑空间信息", "relation": "can_edit"},
                {"id": "delete_space", "label": "删除空间", "relation": "can_delete"},
                {"id": "share_space", "label": "分享空间", "relation": "can_manage"},
                {"id": "manage_space_relation", "label": "管理空间协作者", "relation": "can_manage"},
            ],
        },
        {
            "title": "文件夹级",
            "items": [
                {"id": "view_folder", "label": "查看文件夹", "relation": "can_read"},
                {"id": "create_folder", "label": "创建文件夹", "relation": "can_edit"},
                {"id": "rename_folder", "label": "重命名文件夹", "relation": "can_edit"},
                {"id": "move_folder", "label": "移动文件夹", "relation": "can_edit"},
                {"id": "delete_folder", "label": "删除文件夹", "relation": "can_delete"},
                {"id": "download_folder", "label": "下载文件夹", "relation": "can_read"},
                {"id": "manage_folder_relation", "label": "管理文件夹协作者", "relation": "can_manage"},
            ],
        },
        {
            "title": "文件级",
            "items": [
                {"id": "view_file", "label": "查看文件", "relation": "can_read"},
                {"id": "upload_file", "label": "上传文件", "relation": "can_edit"},
                {"id": "rename_file", "label": "重命名文件", "relation": "can_edit"},
                {"id": "move_file", "label": "移动文件", "relation": "can_edit"},
                {"id": "delete_file", "label": "删除文件", "relation": "can_delete"},
                {"id": "download_file", "label": "下载文件", "relation": "can_read"},
                {"id": "share_file", "label": "分享文件", "relation": "can_manage"},
                {"id": "manage_file_relation", "label": "管理文件协作者", "relation": "can_manage"},
            ],
        },
    ],
}


def knowledge_space_template_sections() -> list[dict]:
    """Return the grouped template for UI-style rendering."""
    return KNOWLEDGE_SPACE_PERMISSION_TEMPLATE["columns"]


def knowledge_space_template_permissions() -> list[dict]:
    """Flatten the grouped template into a simple permission list."""
    return [item for column in knowledge_space_template_sections() for item in column["items"]]


def default_permission_ids_for_relation(relation: str) -> set[str]:
    """System-model default permissions for owner/manager/editor/viewer.

    This is a compatibility helper for built-in relation models. Custom models
    should prefer their explicit permissions[] instead of these defaults.
    """
    normalized = _COMPUTED_TO_MODEL_RELATION.get(relation, relation)
    relation_level = _MODEL_LEVEL.get(normalized, 0)
    return {
        item["id"]
        for item in knowledge_space_template_permissions()
        if relation_level >= _RELATION_LEVEL.get(item["relation"], 99)
    }


def _column_items(column_title: str) -> list[dict]:
    return next(
        column["items"] for column in KNOWLEDGE_SPACE_PERMISSION_TEMPLATE["columns"] if column["title"] == column_title
    )


# IKBA8U: a binding placed on a specific column-level resource (knowledge_space,
# folder, knowledge_file) must only grant the permissions of THAT column --
# otherwise a space-level viewer binding leaks "view_file" into every file
# inside the space, which the knowledge QA retrieval filter then cannot
# distinguish from a real per-file grant. ``column_permission_ids_for_relation``
# returns the resource-type-scoped permission set with the correct transitive
# semantics:
# - knowledge_space + viewer: "view_space" only -- browsing the space does
#   not automatically grant folder/file access.
# - folder + viewer: the folder column's view/download ids AND transitively
#   the file column's view/download ids (a folder-level grant must unlock the
#   files inside the folder -- the F036 listing UI relies on this).
# - knowledge_file + viewer: the file column's view/download ids only.
# Higher relations (editor / manager / owner) follow the same column scoping
# while preserving "higher level subsumes lower level" semantics within a
# column.
_COLUMN_PERMISSIONS_FOR_OBJECT_TYPE: dict[str, list[dict]] = {
    "knowledge_space": _column_items("空间级"),
    "folder": _column_items("文件夹级"),
    "knowledge_file": _column_items("文件级"),
}


def column_permission_ids_for_relation(object_type: str, relation: str) -> set[str]:
    """Resource-type-scoped system-model defaults for the lineage walk.

    Unlike ``default_permission_ids_for_relation`` (which returns ALL level-1
    permission ids across all three columns), this returns the permission ids
    from the column matching ``object_type`` only. For ``folder`` the file
    column's level-1 ids are added transitively so that a folder-level
    ``viewer`` binding still unlocks the files inside the folder. Returns
    an empty set for unknown object types.
    """
    column_items = _COLUMN_PERMISSIONS_FOR_OBJECT_TYPE.get(object_type)
    if not column_items:
        return set()
    normalized = _COMPUTED_TO_MODEL_RELATION.get(relation, relation)
    relation_level = _MODEL_LEVEL.get(normalized, 0)
    own_column_ids = {
        item["id"] for item in column_items if relation_level >= _RELATION_LEVEL.get(item["relation"], 99)
    }
    if object_type == "folder":
        # Transitive: a folder-level grant unlocks the files in that folder.
        file_column_ids = {
            item["id"]
            for item in _COLUMN_PERMISSIONS_FOR_OBJECT_TYPE["knowledge_file"]
            if _RELATION_LEVEL.get(item["relation"], 99) == 1
        }
        own_column_ids.update(file_column_ids)
    return own_column_ids
