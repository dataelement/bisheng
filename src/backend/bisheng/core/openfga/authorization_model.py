"""Static OpenFGA authorization model for BiSheng v2.5.

Defines 13 types: user, system, tenant, department, user_group,
knowledge_space, folder, knowledge_file, channel, workflow, assistant, tool, dashboard.

Permission pyramid: owner > manager(can_manage) > editor(can_edit) > viewer(can_read)
can_delete: owner (top-level) or owner|can_manage from parent (hierarchical)
"""

import copy

MODEL_VERSION = 'v1.0.0'


def _user_types():
    """Allowed user types for resource relations."""
    return [
        {'type': 'user'},
        {'type': 'department', 'relation': 'member'},
        {'type': 'user_group', 'relation': 'member'},
    ]


def _standard_resource_type(type_name: str, *, has_parent: bool = False,
                            parent_types: list = None) -> dict:
    """Build a standard resource type with owner/manager/editor/viewer pyramid + can_delete."""
    relations = {}
    metadata = {}

    # parent (for folder/knowledge_file)
    if has_parent and parent_types:
        relations['parent'] = {'this': {}}
        metadata['parent'] = {
            'directly_related_user_types': [{'type': t} for t in parent_types]
        }

    # owner
    relations['owner'] = {'this': {}}
    metadata['owner'] = {'directly_related_user_types': [{'type': 'user'}]}

    # manager = direct + owner [+ can_manage from parent]
    manager_children = [
        {'this': {}},
        {'computedUserset': {'relation': 'owner'}},
    ]
    if has_parent:
        manager_children.append({
            'tupleToUserset': {
                'tupleset': {'relation': 'parent'},
                'computedUserset': {'relation': 'can_manage'},
            }
        })
    relations['manager'] = {'union': {'child': manager_children}}
    metadata['manager'] = {'directly_related_user_types': _user_types()}

    # editor = direct + manager [+ can_edit from parent]
    editor_children = [
        {'this': {}},
        {'computedUserset': {'relation': 'manager'}},
    ]
    if has_parent:
        editor_children.append({
            'tupleToUserset': {
                'tupleset': {'relation': 'parent'},
                'computedUserset': {'relation': 'can_edit'},
            }
        })
    relations['editor'] = {'union': {'child': editor_children}}
    metadata['editor'] = {'directly_related_user_types': _user_types()}

    # viewer = direct + editor [+ can_read from parent]
    viewer_children = [
        {'this': {}},
        {'computedUserset': {'relation': 'editor'}},
    ]
    if has_parent:
        viewer_children.append({
            'tupleToUserset': {
                'tupleset': {'relation': 'parent'},
                'computedUserset': {'relation': 'can_read'},
            }
        })
    relations['viewer'] = {'union': {'child': viewer_children}}
    metadata['viewer'] = {'directly_related_user_types': _user_types()}

    # computed: can_manage, can_edit, can_read
    relations['can_manage'] = {'computedUserset': {'relation': 'manager'}}
    relations['can_edit'] = {'computedUserset': {'relation': 'editor'}}
    relations['can_read'] = {'computedUserset': {'relation': 'viewer'}}

    # can_delete
    if has_parent:
        # hierarchical: owner OR can_manage from parent
        relations['can_delete'] = {
            'union': {
                'child': [
                    {'computedUserset': {'relation': 'owner'}},
                    {
                        'tupleToUserset': {
                            'tupleset': {'relation': 'parent'},
                            'computedUserset': {'relation': 'can_manage'},
                        }
                    },
                ]
            }
        }
    else:
        # top-level: owner only
        relations['can_delete'] = {'computedUserset': {'relation': 'owner'}}

    return {
        'type': type_name,
        'relations': relations,
        'metadata': {'relations': metadata},
    }


AUTHORIZATION_MODEL: dict = {
    'schema_version': '1.1',
    'type_definitions': [
        # === Base types ===
        {'type': 'user', 'relations': {}, 'metadata': None},

        # === system: super_admin ===
        {
            'type': 'system',
            'relations': {
                'super_admin': {'this': {}},
            },
            'metadata': {
                'relations': {
                    'super_admin': {
                        'directly_related_user_types': [{'type': 'user'}],
                    },
                },
            },
        },

        # === tenant: admin + member ===
        {
            'type': 'tenant',
            'relations': {
                'admin': {'this': {}},
                'member': {'this': {}},
            },
            'metadata': {
                'relations': {
                    'admin': {
                        'directly_related_user_types': [{'type': 'user'}],
                    },
                    'member': {
                        'directly_related_user_types': [{'type': 'user'}],
                    },
                },
            },
        },

        # === department: parent + admin (inherits from parent) + member ===
        {
            'type': 'department',
            'relations': {
                'parent': {'this': {}},
                'admin': {
                    'union': {
                        'child': [
                            {'this': {}},
                            {
                                'tupleToUserset': {
                                    'tupleset': {'relation': 'parent'},
                                    'computedUserset': {'relation': 'admin'},
                                }
                            },
                        ]
                    }
                },
                'member': {'this': {}},
            },
            'metadata': {
                'relations': {
                    'parent': {
                        'directly_related_user_types': [{'type': 'department'}],
                    },
                    'admin': {
                        'directly_related_user_types': [{'type': 'user'}],
                    },
                    'member': {
                        'directly_related_user_types': [{'type': 'user'}],
                    },
                },
            },
        },

        # === user_group: admin + member ===
        {
            'type': 'user_group',
            'relations': {
                'admin': {'this': {}},
                'member': {'this': {}},
            },
            'metadata': {
                'relations': {
                    'admin': {
                        'directly_related_user_types': [{'type': 'user'}],
                    },
                    'member': {
                        'directly_related_user_types': [{'type': 'user'}],
                    },
                },
            },
        },

        # === Resource types (8) ===
        _standard_resource_type('knowledge_space'),
        _standard_resource_type('folder', has_parent=True,
                                parent_types=['knowledge_space', 'folder']),
        _standard_resource_type('knowledge_file', has_parent=True,
                                parent_types=['folder', 'knowledge_space']),
        _standard_resource_type('channel'),
        _standard_resource_type('workflow'),
        _standard_resource_type('assistant'),
        _standard_resource_type('tool'),
        _standard_resource_type('dashboard'),
    ],
}


def get_authorization_model() -> dict:
    """Return a deep copy of the authorization model."""
    return copy.deepcopy(AUTHORIZATION_MODEL)
