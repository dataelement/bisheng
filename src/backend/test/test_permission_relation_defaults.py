from bisheng.permission.domain.application_permission_template import (
    default_permission_ids_for_relation as default_app_permission_ids_for_relation,
)
from bisheng.permission.domain.knowledge_space_permission_template import (
    default_permission_ids_for_relation as default_space_permission_ids_for_relation,
)
from bisheng.permission.domain.tool_permission_template import (
    default_permission_ids_for_relation as default_tool_permission_ids_for_relation,
)
from bisheng.permission.domain.workflow_app_permission import (
    default_app_permission_ids_for_relation as default_workflow_app_permission_ids_for_relation,
)


def test_application_permission_defaults_accept_computed_relations():
    assert default_app_permission_ids_for_relation('can_read') == {'view_app', 'use_app'}
    assert default_app_permission_ids_for_relation('can_edit') == {
        'view_app', 'use_app', 'edit_app',
    }
    assert default_app_permission_ids_for_relation('can_manage') == {
        'view_app',
        'use_app',
        'edit_app',
        'publish_app',
        'unpublish_app',
        'share_app',
        'manage_app_owner',
        'manage_app_manager',
        'manage_app_viewer',
    }


def test_tool_permission_defaults_accept_computed_relations():
    assert default_tool_permission_ids_for_relation('can_read') == {'view_tool', 'use_tool'}
    assert default_tool_permission_ids_for_relation('can_manage') == {
        'view_tool',
        'use_tool',
        'edit_tool',
        'manage_tool_owner',
        'manage_tool_manager',
        'manage_tool_viewer',
    }


def test_knowledge_space_permission_defaults_accept_computed_relations():
    assert default_space_permission_ids_for_relation('can_read') >= {
        'view_space', 'view_folder', 'view_file', 'download_folder', 'download_file',
    }
    assert default_space_permission_ids_for_relation('can_manage') >= {
        'share_space', 'manage_space_relation', 'manage_folder_relation', 'share_file',
        'manage_file_relation',
    }
def test_workflow_app_default_permissions_accept_computed_relations():
    assert default_workflow_app_permission_ids_for_relation('can_read') == {
        'view_app', 'use_app',
    }
    assert default_workflow_app_permission_ids_for_relation('can_manage') >= {
        'share_app', 'manage_app_owner', 'manage_app_manager', 'manage_app_viewer',
    }
