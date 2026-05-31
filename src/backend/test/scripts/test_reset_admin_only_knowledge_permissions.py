from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import scripts.reset_admin_only_knowledge_permissions as reset_script

from scripts.reset_admin_only_knowledge_permissions import (
    ADMIN_ROLE_ID,
    AdminResolutionError,
    DEFAULT_ROLE_ID,
    ApplyVerification,
    FgaTupleKey,
    ResourceRef,
    ResetPlan,
    UserRoleSnapshot,
    UserRoleResetPlan,
    _aget_fga_client_for_script,
    _close_script_contexts,
    _dedupe_operations,
    _load_relation_bindings,
    _read_management_tuples,
    build_desired_resource_tuples,
    filter_relation_bindings,
    print_apply_verification,
    parse_args,
    apply_reset_plan,
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


def _minimal_reset_plan(
    *,
    resource_operations: tuple[TupleOperation, ...] = (),
    management_operations: tuple[TupleOperation, ...] = (),
    knowledge_space_ids: tuple[int, ...] = (),
    knowledge_file_ids: tuple[int, ...] = (),
) -> ResetPlan:
    return ResetPlan(
        admin_id=1,
        admin_user_name='admin',
        non_admin_user_ids=(),
        user_role_plan=UserRoleResetPlan(
            delete_role_ids=(),
            default_role_inserts=(),
            admin_role_missing=False,
            admin_role_tenant_id=1,
        ),
        group_admin_row_ids=(),
        user_group_member_writes=(),
        knowledge_space_ids=knowledge_space_ids,
        knowledge_file_ids=knowledge_file_ids,
        resource_refs=(),
        resource_tuple_operations=resource_operations,
        management_tuple_operations=management_operations,
        relation_bindings_kept=(),
        relation_bindings_removed=(),
        admin_member_insert_space_ids=(),
        failed_tuple_ids_to_invalidate=(),
        counts={},
        warnings=(),
    )


async def test_apply_db_changes_preserves_knowledge_space_scope_and_department_bindings(monkeypatch):
    class _FakeStatement:
        def __init__(self, action, table):
            self.action = action
            self.table = table

        def where(self, *_, **__):
            return self

        def values(self, *_, **__):
            return self

        def __str__(self):
            return f'{self.action} {self.table}'

    def fake_table_name(model):
        if model is getattr(reset_script, 'KnowledgeSpaceScope', None):
            return 'knowledge_space_scope'
        if model is getattr(reset_script, 'DepartmentKnowledgeSpace', None):
            return 'department_knowledge_space'
        return repr(model)

    def capture_statement(statement):
        session.statements.append(str(statement))
        return _FakeScalarResult(None)

    session = SimpleNamespace(
        statements=[],
        added=[],
        exec=AsyncMock(side_effect=capture_statement),
        add=lambda row: session.added.append(row),
        add_all=lambda rows: session.added.extend(rows),
        flush=AsyncMock(),
        commit=AsyncMock(),
    )

    class _FakeSessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(reset_script, 'get_async_db_session', lambda: _FakeSessionContext())
    monkeypatch.setattr(
        reset_script,
        'sa_update',
        lambda model: _FakeStatement('UPDATE', fake_table_name(model)),
    )
    monkeypatch.setattr(
        reset_script,
        'sa_delete',
        lambda model: _FakeStatement('DELETE', fake_table_name(model)),
    )
    plan = _minimal_reset_plan(
        knowledge_space_ids=(100,),
        knowledge_file_ids=(200,),
    )

    await reset_script._apply_db_changes(plan, ())

    emitted_sql = '\n'.join(session.statements).lower()
    assert 'knowledge_space_scope' not in emitted_sql
    assert 'department_knowledge_space' not in emitted_sql
    session.commit.assert_awaited_once()


async def test_get_fga_client_for_script_registers_openfga_context_when_missing(monkeypatch):
    fake_client = object()
    monkeypatch.setattr(
        reset_script,
        'aget_fga_client',
        AsyncMock(return_value=None),
    )

    class _FakeFGAManager:
        name = 'openfga'

        def __init__(self, openfga_config):
            self.openfga_config = openfga_config

    class _FakeAppContext:
        def __init__(self):
            self.registered = []

        def get_context(self, name):
            raise KeyError(name)

        def register_context(self, context, optional=False):
            self.registered.append((context, optional))

        async def async_get_instance(self, name):
            assert name == 'openfga'
            return fake_client

    app_context = _FakeAppContext()
    openfga_config = SimpleNamespace(enabled=True)

    client = await _aget_fga_client_for_script(
        settings_obj=SimpleNamespace(openfga=openfga_config),
        app_context_obj=app_context,
        fga_manager_cls=_FakeFGAManager,
    )

    assert client is fake_client
    assert len(app_context.registered) == 1
    registered_context, optional = app_context.registered[0]
    assert isinstance(registered_context, _FakeFGAManager)
    assert registered_context.openfga_config is openfga_config
    assert optional is True


async def test_apply_reset_plan_returns_post_apply_verification(monkeypatch):
    resource_op = TupleOperation(
        action='delete',
        user='user:2',
        relation='viewer',
        object='knowledge_space:100',
    )
    management_op = TupleOperation(
        action='write',
        user='user:1',
        relation='super_admin',
        object='system:global',
    )
    plan = _minimal_reset_plan(
        resource_operations=(resource_op,),
        management_operations=(management_op,),
    )
    monkeypatch.setattr(reset_script, '_apply_db_changes', AsyncMock(return_value=(10, 11, 12)))
    monkeypatch.setattr(reset_script.PermissionService, 'batch_write_tuples', AsyncMock())
    monkeypatch.setattr(reset_script, '_mark_reset_failed_tuples_succeeded', AsyncMock())
    pending_count = AsyncMock(return_value=1)
    monkeypatch.setattr(reset_script, '_count_pending_reset_failed_tuples', pending_count)
    monkeypatch.setattr(reset_script, '_invalidate_permission_caches', AsyncMock())

    verification = await apply_reset_plan(plan)

    assert verification == ApplyVerification(
        resource_tuple_operations=1,
        management_tuple_operations=1,
        pre_recorded_failed_tuples=3,
        pending_pre_recorded_failed_tuples=1,
    )
    pending_count.assert_awaited_once_with((10, 11, 12))


def test_print_apply_verification_includes_tuple_counts_and_pending_failed_tuples(capsys):
    verification = ApplyVerification(
        resource_tuple_operations=2,
        management_tuple_operations=1,
        pre_recorded_failed_tuples=3,
        pending_pre_recorded_failed_tuples=0,
    )

    print_apply_verification(verification, as_json=False)

    output = capsys.readouterr().out
    assert '- resource_tuple_operations: 2' in output
    assert '- management_tuple_operations: 1' in output
    assert '- pre_recorded_failed_tuples: 3' in output
    assert '- pending_pre_recorded_failed_tuples: 0' in output


async def test_close_script_contexts_closes_registry_after_lazy_context_registration():
    events = []

    async def fake_close_app_context():
        events.append('close_app_context')

    class _FakeRegistry:
        async def async_close_all(self):
            events.append('registry_close_all')

    app_context = SimpleNamespace(get_registry=lambda: _FakeRegistry())

    await _close_script_contexts(
        close_app_context_fn=fake_close_app_context,
        app_context_obj=app_context,
    )

    assert events == ['close_app_context', 'registry_close_all']


async def test_read_management_tuples_uses_object_scoped_admin_reads():
    class _FakeFGA:
        def __init__(self):
            self.calls = []

        async def read_tuples(self, user=None, relation=None, object=None):
            self.calls.append((user, relation, object))
            if relation == 'admin' and object is None:
                raise AssertionError('admin tuple reads must be scoped by object')
            if object == 'tenant:2':
                return [{'user': 'user:2', 'relation': 'admin', 'object': 'tenant:2'}]
            if object == 'department:9':
                return [{'user': 'user:3', 'relation': 'admin', 'object': 'department:9'}]
            if object == 'system:global':
                return [{'user': 'user:4', 'relation': 'super_admin', 'object': 'system:global'}]
            return []

    fga = _FakeFGA()

    tuples = await _read_management_tuples(fga, ('tenant:2', 'department:9'))

    assert fga.calls == [
        (None, 'admin', 'tenant:2'),
        (None, 'admin', 'department:9'),
        (None, 'super_admin', 'system:global'),
    ]
    assert tuples == [
        FgaTupleKey(user='user:2', relation='admin', object='tenant:2'),
        FgaTupleKey(user='user:3', relation='admin', object='department:9'),
        FgaTupleKey(user='user:4', relation='super_admin', object='system:global'),
    ]


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
