"""Unit tests for OpenFGA authorization model DSL (F013 T02).

Verifies:
- v2.0.2 model version bump (user_group admin/member compatibility)
- tenant type carries shared_to relation; no parent relation
- Every resource gets shared_with: [tenant] + viewer tupleToUserset(shared_with, member)
- viewer's directly_related_user_types stays at 3 canonical sources (no #-nesting,
  which OpenFGA protobuf rejects)
- manager/editor stay at the three standard sources
- llm_server / llm_model types preallocated for F020
"""

import pytest

from bisheng.core.openfga.authorization_model import (
    AUTHORIZATION_MODEL,
    MODEL_VERSION,
    get_authorization_model,
)


@pytest.fixture
def types_by_name() -> dict:
    """Index type_definitions by type name for easier lookup."""
    return {td['type']: td for td in AUTHORIZATION_MODEL['type_definitions']}


# ── Model version & top-level invariants ─────────────────────────


def test_model_version_bumped_to_v2():
    """MODEL_VERSION must change when the static OpenFGA DSL changes."""
    assert MODEL_VERSION == 'v2.0.2'


def test_get_authorization_model_returns_deep_copy():
    """get_authorization_model must return an independent dict (mutation safety)."""
    a = get_authorization_model()
    b = get_authorization_model()
    a['type_definitions'].append({'type': 'mutated'})
    assert {'type': 'mutated'} not in b['type_definitions']


def test_schema_version_is_1_1():
    assert AUTHORIZATION_MODEL['schema_version'] == '1.1'


# ── Tenant type ──────────────────────────────────────────────────


def test_tenant_has_shared_to_relation(types_by_name):
    """Tenant type must carry shared_to relation pointing to tenant type."""
    tenant = types_by_name['tenant']
    assert 'shared_to' in tenant['relations']
    shared_to_meta = tenant['metadata']['relations']['shared_to']
    assert shared_to_meta['directly_related_user_types'] == [{'type': 'tenant'}]


def test_tenant_has_no_parent_relation(types_by_name):
    """AD-05: tenant#parent removed in v2.5.1; parent_tenant_id lives in MySQL only."""
    tenant = types_by_name['tenant']
    assert 'parent' not in tenant['relations']
    assert 'parent' not in tenant['metadata']['relations']


def test_tenant_admin_member_unchanged(types_by_name):
    """admin and member relations must persist (used for Child Admin and belongs-to lookup)."""
    tenant = types_by_name['tenant']
    assert tenant['relations']['admin'] == {'this': {}}
    assert tenant['relations']['member'] == {'this': {}}


def test_tenant_admin_does_not_inherit(types_by_name):
    """INV-T3: tenant#admin must NOT inherit from parent (two-tier admin model)."""
    tenant = types_by_name['tenant']
    # admin must be a plain {'this': {}} — no union with tupleToUserset on parent
    assert tenant['relations']['admin'] == {'this': {}}


# ── Resource viewer narrowing ────────────────────────────────────


@pytest.mark.parametrize('resource_type', [
    'knowledge_space', 'knowledge_library', 'folder', 'knowledge_file', 'channel',
    'workflow', 'assistant', 'tool', 'dashboard',
    'llm_server', 'llm_model',
])
def test_resource_has_shared_with_relation(types_by_name, resource_type):
    """2026-04-19 redesign: each resource carries shared_with: [tenant]."""
    resource = types_by_name[resource_type]
    assert 'shared_with' in resource['relations']
    shared_with_meta = resource['metadata']['relations']['shared_with']
    assert shared_with_meta['directly_related_user_types'] == [{'type': 'tenant'}]


@pytest.mark.parametrize('resource_type', [
    'knowledge_space', 'knowledge_library', 'folder', 'knowledge_file', 'channel',
    'workflow', 'assistant', 'tool', 'dashboard',
    'llm_server', 'llm_model',
])
def test_resource_viewer_chains_shared_with_member(types_by_name, resource_type):
    """viewer relation includes tupleToUserset(shared_with, member)."""
    resource = types_by_name[resource_type]
    children = resource['relations']['viewer']['union']['child']
    assert {
        'tupleToUserset': {
            'tupleset': {'relation': 'shared_with'},
            'computedUserset': {'relation': 'member'},
        }
    } in children


@pytest.mark.parametrize('resource_type', [
    'knowledge_space', 'knowledge_library', 'folder', 'knowledge_file', 'channel',
    'workflow', 'assistant', 'tool', 'dashboard',
    'llm_server', 'llm_model',
])
def test_resource_viewer_drut_uses_only_valid_relations(types_by_name, resource_type):
    """directly_related_user_types must not carry nested-relation strings (e.g. 'shared_to#member'):
    OpenFGA's protobuf rejects any ``relation`` value matching /[:#@\\s]/."""
    resource = types_by_name[resource_type]
    viewer_types = resource['metadata']['relations']['viewer']['directly_related_user_types']
    for entry in viewer_types:
        relation = entry.get('relation', '')
        assert '#' not in relation, f'{resource_type}.viewer carries forbidden nested relation {relation!r}'
        assert ':' not in relation
        assert '@' not in relation


@pytest.mark.parametrize('resource_type', [
    'knowledge_space', 'knowledge_library', 'folder', 'knowledge_file', 'channel',
    'workflow', 'assistant', 'tool', 'dashboard',
    'llm_server', 'llm_model',
])
def test_resource_manager_excludes_tenant(types_by_name, resource_type):
    """Round 3 narrowing: manager must NOT contain any tenant# relation."""
    resource = types_by_name[resource_type]
    manager_types = resource['metadata']['relations']['manager']['directly_related_user_types']
    assert all(t.get('type') != 'tenant' for t in manager_types), \
        f'{resource_type}.manager unexpectedly carries tenant type: {manager_types}'


@pytest.mark.parametrize('resource_type', [
    'knowledge_space', 'knowledge_library', 'folder', 'knowledge_file', 'channel',
    'workflow', 'assistant', 'tool', 'dashboard',
    'llm_server', 'llm_model',
])
def test_resource_editor_excludes_tenant(types_by_name, resource_type):
    """Round 3 narrowing: editor must NOT contain any tenant# relation."""
    resource = types_by_name[resource_type]
    editor_types = resource['metadata']['relations']['editor']['directly_related_user_types']
    assert all(t.get('type') != 'tenant' for t in editor_types), \
        f'{resource_type}.editor unexpectedly carries tenant type: {editor_types}'


def test_resource_viewer_three_standard_sources_preserved(types_by_name):
    """Viewer must still keep user / department#member / user_group#member."""
    viewer_types = types_by_name['workflow']['metadata']['relations']['viewer'][
        'directly_related_user_types']
    assert {'type': 'user'} in viewer_types
    assert {'type': 'department', 'relation': 'member'} in viewer_types
    assert {'type': 'user_group', 'relation': 'member'} in viewer_types


def test_user_group_admin_is_member(types_by_name):
    """Group admins must satisfy user_group#member grants."""
    user_group = types_by_name['user_group']
    assert user_group['relations']['admin'] == {'this': {}}
    assert {'computedUserset': {'relation': 'admin'}} in user_group['relations']['member']['union']['child']


def test_resource_manager_accepts_user_group_admin(types_by_name):
    """Legacy groupresource migration grants manager to user_group#admin."""
    manager_types = types_by_name['workflow']['metadata']['relations']['manager'][
        'directly_related_user_types']
    assert {'type': 'user_group', 'relation': 'admin'} in manager_types


def test_folder_parent_accepts_knowledge_library(types_by_name):
    parent_types = types_by_name['folder']['metadata']['relations']['parent']['directly_related_user_types']
    assert {'type': 'knowledge_library'} in parent_types


def test_knowledge_file_parent_accepts_knowledge_library(types_by_name):
    parent_types = types_by_name['knowledge_file']['metadata']['relations']['parent']['directly_related_user_types']
    assert {'type': 'knowledge_library'} in parent_types


# ── LLM types preallocation (F020 dependency) ────────────────────


def test_llm_server_type_exists(types_by_name):
    """F020 needs llm_server type to write Root → Child shared_to viewer tuples."""
    assert 'llm_server' in types_by_name


def test_llm_model_type_exists(types_by_name):
    assert 'llm_model' in types_by_name


def test_llm_server_has_full_pyramid(types_by_name):
    """llm_server must use _standard_resource_type pyramid (owner/manager/editor/viewer)."""
    relations = types_by_name['llm_server']['relations']
    for r in ['owner', 'manager', 'editor', 'viewer',
              'can_manage', 'can_edit', 'can_read', 'can_delete']:
        assert r in relations, f'llm_server missing relation {r}'


def test_llm_model_has_full_pyramid(types_by_name):
    relations = types_by_name['llm_model']['relations']
    for r in ['owner', 'manager', 'editor', 'viewer',
              'can_manage', 'can_edit', 'can_read', 'can_delete']:
        assert r in relations, f'llm_model missing relation {r}'


# ── Type count ───────────────────────────────────────────────────


def test_total_type_count_is_16():
    """v2.5.1 model: user + system + tenant + department + user_group + 11 resources = 16."""
    assert len(AUTHORIZATION_MODEL['type_definitions']) == 16
