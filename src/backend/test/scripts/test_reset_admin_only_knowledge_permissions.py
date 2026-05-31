from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.reset_admin_only_knowledge_permissions import (
    ADMIN_ROLE_ID,
    AdminResolutionError,
    DEFAULT_ROLE_ID,
    FgaTupleKey,
    ResourceRef,
    UserRoleSnapshot,
    _dedupe_operations,
    _load_relation_bindings,
    build_desired_resource_tuples,
    filter_relation_bindings,
    parse_args,
    plan_resource_tuple_operations,
    plan_user_role_reset,
    resource_refs_for_knowledge,
    should_invalidate_failed_tuple,
    validate_admin_user,
    _plan_management_tuple_operations,
)
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation


class _FakeScalarResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self, row):
        self._row = row

    async def exec(self, _statement):
        return _FakeScalarResult(self._row)


def test_apply_plan_tuple_operations_are_deduplicated_before_db_pre_recording():
    operations = _dedupe_operations([
        TupleOperation(action='delete', user='user:2', relation='viewer', object='knowledge_space:100'),
        TupleOperation(action='delete', user='user:2', relation='viewer', object='knowledge_space:100'),
        TupleOperation(action='write', user='user:1', relation='owner', object='knowledge_space:100'),
    ])

    assert [(op.action, op.user, op.relation, op.object) for op in operations] == [
        ('delete', 'user:2', 'viewer', 'knowledge_space:100'),
        ('write', 'user:1', 'owner', 'knowledge_space:100'),
    ]


def test_parse_args_defaults_to_dry_run():
    args = parse_args([])

    assert args.apply is False


def test_validate_admin_user_requires_exactly_one_active_admin():
    admin = validate_admin_user([
        SimpleNamespace(user_id=1, user_name='admin', delete=0),
    ])

    assert admin.user_id == 1

    with pytest.raises(AdminResolutionError):
        validate_admin_user([])

    with pytest.raises(AdminResolutionError):
        validate_admin_user([
            SimpleNamespace(user_id=1, user_name='admin', delete=0),
            SimpleNamespace(user_id=2, user_name='admin', delete=0),
        ])


def test_plan_user_role_reset_demotes_non_admins_and_preserves_default_role():
    roles = [
        UserRoleSnapshot(id=10, user_id=1, role_id=ADMIN_ROLE_ID, tenant_id=1),
        UserRoleSnapshot(id=20, user_id=2, role_id=ADMIN_ROLE_ID, tenant_id=5),
        UserRoleSnapshot(id=21, user_id=2, role_id=7, tenant_id=5),
        UserRoleSnapshot(id=30, user_id=3, role_id=DEFAULT_ROLE_ID, tenant_id=6),
        UserRoleSnapshot(id=31, user_id=3, role_id=8, tenant_id=6),
        UserRoleSnapshot(id=40, user_id=4, role_id=9, tenant_id=None),
    ]

    plan = plan_user_role_reset(
        admin_id=1,
        all_user_ids=[1, 2, 3, 4],
        role_rows=roles,
        active_tenant_by_user={4: 9},
    )

    assert plan.delete_role_ids == (20, 21, 31, 40)
    assert plan.default_role_inserts == ((2, 5), (4, 9))
    assert plan.admin_role_missing is False


def test_resource_refs_for_knowledge_resolves_folder_and_file_parentage():
    refs = resource_refs_for_knowledge(
        space_ids=[100],
        files=[
            SimpleNamespace(id=201, knowledge_id=100, file_type=0, file_level_path=''),
            SimpleNamespace(id=202, knowledge_id=100, file_type=1, file_level_path='/201'),
        ],
    )

    assert refs == (
        ResourceRef(object_type='knowledge_space', object_id='100'),
        ResourceRef(
            object_type='folder',
            object_id='201',
            parent_type='knowledge_space',
            parent_id='100',
        ),
        ResourceRef(
            object_type='knowledge_file',
            object_id='202',
            parent_type='folder',
            parent_id='201',
        ),
    )


def test_plan_resource_tuple_operations_removes_old_access_but_keeps_parent_tuple():
    existing = [
        FgaTupleKey(user='user:2', relation='viewer', object='knowledge_space:100'),
        FgaTupleKey(user='department:9#member', relation='viewer', object='folder:201'),
        FgaTupleKey(user='knowledge_space:100', relation='parent', object='folder:201'),
        FgaTupleKey(user='user:1', relation='owner', object='folder:201'),
    ]
    desired = build_desired_resource_tuples(
        admin_id=1,
        resources=[
            ResourceRef(object_type='knowledge_space', object_id='100'),
            ResourceRef(
                object_type='folder',
                object_id='201',
                parent_type='knowledge_space',
                parent_id='100',
            ),
        ],
    )

    operations = plan_resource_tuple_operations(existing, desired)

    assert {(op.action, op.user, op.relation, op.object) for op in operations} == {
        ('delete', 'user:2', 'viewer', 'knowledge_space:100'),
        ('delete', 'department:9#member', 'viewer', 'folder:201'),
        ('write', 'user:1', 'owner', 'knowledge_space:100'),
    }


def test_plan_management_tuple_operations_revokes_non_admin_admin_grants():
    operations = _plan_management_tuple_operations(
        admin_id=1,
        existing_tuples=[
            FgaTupleKey(user='user:1', relation='admin', object='tenant:2'),
            FgaTupleKey(user='user:2', relation='admin', object='tenant:2'),
            FgaTupleKey(user='user:3', relation='admin', object='department:9'),
            FgaTupleKey(user='user:4', relation='super_admin', object='system:global'),
        ],
        user_group_member_writes=[
            FgaTupleKey(user='user:5', relation='member', object='user_group:8'),
        ],
    )

    assert {(op.action, op.user, op.relation, op.object) for op in operations} == {
        ('delete', 'user:2', 'admin', 'tenant:2'),
        ('delete', 'user:3', 'admin', 'department:9'),
        ('delete', 'user:4', 'super_admin', 'system:global'),
        ('write', 'user:1', 'super_admin', 'system:global'),
        ('write', 'user:5', 'member', 'user_group:8'),
    }


def test_filter_relation_bindings_only_removes_affected_knowledge_resources():
    kept, removed = filter_relation_bindings(
        [
            {'resource_type': 'knowledge_space', 'resource_id': '100', 'subject_id': 2},
            {'resource_type': 'folder', 'resource_id': '201', 'subject_id': 2},
            {'resource_type': 'workflow', 'resource_id': '100', 'subject_id': 2},
            {'resource_type': 'knowledge_space', 'resource_id': '999', 'subject_id': 2},
        ],
        {
            ('knowledge_space', '100'),
            ('folder', '201'),
        },
    )

    assert removed == [
        {'resource_type': 'knowledge_space', 'resource_id': '100', 'subject_id': 2},
        {'resource_type': 'folder', 'resource_id': '201', 'subject_id': 2},
    ]
    assert kept == [
        {'resource_type': 'workflow', 'resource_id': '100', 'subject_id': 2},
        {'resource_type': 'knowledge_space', 'resource_id': '999', 'subject_id': 2},
    ]


def test_should_invalidate_failed_tuple_for_affected_resources_and_non_admin_grants():
    affected = {
        ('knowledge_space', '100'),
        ('folder', '201'),
        ('knowledge_file', '202'),
    }

    assert should_invalidate_failed_tuple(
        SimpleNamespace(
            status='pending',
            fga_user='user:2',
            relation='viewer',
            object='knowledge_space:100',
        ),
        admin_id=1,
        affected_resources=affected,
    )
    assert should_invalidate_failed_tuple(
        SimpleNamespace(
            status='pending',
            fga_user='user:2',
            relation='admin',
            object='tenant:7',
        ),
        admin_id=1,
        affected_resources=affected,
    )
    assert not should_invalidate_failed_tuple(
        SimpleNamespace(
            status='pending',
            fga_user='user:1',
            relation='admin',
            object='tenant:7',
        ),
        admin_id=1,
        affected_resources=affected,
    )
    assert not should_invalidate_failed_tuple(
        SimpleNamespace(
            status='succeeded',
            fga_user='user:2',
            relation='viewer',
            object='knowledge_space:100',
        ),
        admin_id=1,
        affected_resources=affected,
    )


async def test_load_relation_bindings_returns_empty_for_missing_or_blank_config():
    assert await _load_relation_bindings(_FakeSession(None)) == []
    assert await _load_relation_bindings(_FakeSession(SimpleNamespace(value='  '))) == []


async def test_load_relation_bindings_requires_valid_json_list():
    with pytest.raises(RuntimeError, match='invalid JSON'):
        await _load_relation_bindings(_FakeSession(SimpleNamespace(value='{broken')))

    with pytest.raises(RuntimeError, match='must be a JSON list'):
        await _load_relation_bindings(_FakeSession(SimpleNamespace(value='{"items": []}')))


async def test_load_relation_bindings_returns_parsed_list():
    assert await _load_relation_bindings(
        _FakeSession(SimpleNamespace(value='[{"resource_type": "knowledge_space"}]')),
    ) == [{'resource_type': 'knowledge_space'}]
