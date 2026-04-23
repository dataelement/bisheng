from bisheng.permission.domain.knowledge_library_permission_template import (
    KNOWLEDGE_LIBRARY_PERMISSION_TEMPLATE,
    default_permission_ids_for_relation,
)


def test_knowledge_library_template_title_and_items():
    assert KNOWLEDGE_LIBRARY_PERMISSION_TEMPLATE['title'] == '知识库模块'
    item_ids = [
        item['id']
        for column in KNOWLEDGE_LIBRARY_PERMISSION_TEMPLATE['columns']
        for item in column['items']
    ]
    assert item_ids == [
        'view_kb',
        'use_kb',
        'edit_kb',
        'delete_kb',
        'manage_kb_owner',
        'manage_kb_manager',
        'manage_kb_viewer',
    ]


def test_knowledge_library_default_permissions_follow_relation_pyramid():
    assert default_permission_ids_for_relation('viewer') == {'view_kb', 'use_kb'}
    assert default_permission_ids_for_relation('editor') == {
        'view_kb', 'use_kb', 'edit_kb',
    }
    assert default_permission_ids_for_relation('manager') == {
        'view_kb',
        'use_kb',
        'edit_kb',
        'manage_kb_owner',
        'manage_kb_manager',
        'manage_kb_viewer',
    }
    assert default_permission_ids_for_relation('owner') == {
        'view_kb',
        'use_kb',
        'edit_kb',
        'delete_kb',
        'manage_kb_owner',
        'manage_kb_manager',
        'manage_kb_viewer',
    }
