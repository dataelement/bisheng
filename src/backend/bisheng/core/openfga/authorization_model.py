"""Static OpenFGA authorization model for BiSheng v2.5.1.

Defines 15 types: user, system, tenant, department, user_group,
knowledge_space, folder, knowledge_file, channel, workflow, assistant, tool, dashboard,
llm_server, llm_model.

Permission pyramid: owner > manager(can_manage) > editor(can_edit) > viewer(can_read)
can_delete: owner (top-level) or owner|can_manage from parent (hierarchical)

v2.5.1 F013 changes:
- tenant type: adds shared_to relation (Root → Child explicit share); admin no longer
  inherits via parent (two-tier admin model); tenant#parent relation removed (FGA
  redundant — parent_tenant_id lives in MySQL)
- Resource viewer adds tenant#shared_to#member directly_related_user_type for shared
  resource visibility. manager/editor are NOT extended with any tenant relation —
  resource grants stay at four sources (user + department#member + user_group#member +
  owner). 2026-04-21 Round 3 narrowing.
- New types llm_server / llm_model preallocated for F020 LLM multi-tenant.
"""

import copy

MODEL_VERSION = 'v2.0.0'


def _user_types():
    """Allowed user types for resource relations."""
    return [
        {'type': 'user'},
        {'type': 'department', 'relation': 'member'},
        {'type': 'user_group', 'relation': 'member'},
    ]


def _viewer_user_types(include_tenant_shared: bool = True):
    """Viewer-specific user types: standard sources plus optional tenant#shared_to#member.

    F013 (2026-04-21 Round 3 narrowing): only viewer carries tenant#shared_to#member;
    manager/editor stay at the standard three sources to keep resource authorization
    bounded to owner + user + department#member + user_group#member.
    """
    types = _user_types()
    if include_tenant_shared:
        types.append({'type': 'tenant', 'relation': 'shared_to#member'})
    return types


def _standard_resource_type(type_name: str, *, has_parent: bool = False,
                            parent_types: list = None,
                            viewer_includes_tenant_shared: bool = True) -> dict:
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
    metadata['viewer'] = {
        'directly_related_user_types': _viewer_user_types(viewer_includes_tenant_shared),
    }

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

        # === tenant: admin + member + shared_to ===
        # F013 (v2.5.1):
        # - admin: Child Tenant only; does NOT inherit via parent (two-tier admin model);
        #          Root tenant has no admin tuples (super_admin handles Root mgmt — INV-T3).
        # - member: belongs-to lookup; not used in resource grants (Round 3 narrowing).
        # - shared_to: Root → Child explicit share; resource viewer chains via
        #              tenant#shared_to#member directly_related_user_type.
        # tenant#parent relation intentionally absent — parent_tenant_id lives in MySQL only
        # (AD-05, 2026-04-20 Round 2 narrowing).
        {
            'type': 'tenant',
            'relations': {
                'admin': {'this': {}},
                'member': {'this': {}},
                'shared_to': {'this': {}},
            },
            'metadata': {
                'relations': {
                    'admin': {
                        'directly_related_user_types': [{'type': 'user'}],
                    },
                    'member': {
                        'directly_related_user_types': [{'type': 'user'}],
                    },
                    'shared_to': {
                        'directly_related_user_types': [{'type': 'tenant'}],
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

        # === Resource types (10) ===
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
        # F013 (v2.5.1) preallocates llm_server/llm_model for F020 LLM multi-tenant.
        # Without these types, F020 cannot write {llm_server:id}#viewer →
        # tenant:{root}#shared_to#member tuples to enable Root → Child sharing.
        _standard_resource_type('llm_server'),
        _standard_resource_type('llm_model'),
    ],
}


def get_authorization_model() -> dict:
    """Return a deep copy of the authorization model."""
    return copy.deepcopy(AUTHORIZATION_MODEL)
