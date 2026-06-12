import json
import types
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.permission.migration import reconcile_role_access_fga


@pytest.mark.asyncio
async def test_main_initializes_application_context(monkeypatch):
    fake_settings = object()
    calls = []

    fake_config_service = types.ModuleType('bisheng.common.services.config_service')
    fake_config_service.settings = fake_settings

    fake_context = types.ModuleType('bisheng.core.context')

    async def fake_initialize_app_context(config):
        calls.append(('initialize', config))

    async def fake_close_app_context():
        calls.append(('close', None))

    async def fake_reconcile(**kwargs):
        calls.append(('reconcile', kwargs))
        return reconcile_role_access_fga.Stats(
            source_role_access_rows=1,
            source_expanded_permissions=1,
            source_unique_permissions=1,
            desired=1,
            actual=1,
            to_write=0,
            to_delete=0,
            protected=0,
        )

    fake_context.initialize_app_context = fake_initialize_app_context
    fake_context.close_app_context = fake_close_app_context

    monkeypatch.setitem(
        __import__('sys').modules,
        'bisheng.common.services.config_service',
        fake_config_service,
    )
    monkeypatch.setitem(__import__('sys').modules, 'bisheng.core.context', fake_context)
    monkeypatch.setattr(reconcile_role_access_fga, 'reconcile', fake_reconcile)

    await reconcile_role_access_fga._main(dry_run=True)

    assert calls == [
        ('initialize', fake_settings),
        ('reconcile', {
            'dry_run': True,
            'report_path': None,
            'report_dir': None,
            'workspace_path': None,
            'keep_workspace': False,
            'batch_size': 1000,
            'progress': None,
        }),
        ('close', None),
    ]


class ObjectOnlyFGA:
    def __init__(self):
        self.calls = []
        self.tuples = {
            'workflow:10': [
                {'user': 'user:1', 'relation': 'viewer', 'object': 'workflow:10'},
                {'user': 'user:2', 'relation': 'editor', 'object': 'workflow:10'},
                {'user': 'user:3', 'relation': 'viewer', 'object': 'workflow:10'},
                {'user': 'department:1#member', 'relation': 'viewer', 'object': 'workflow:10'},
            ],
            'tool:20': [
                {'user': 'user:1', 'relation': 'owner', 'object': 'tool:20'},
                {'user': 'user:2', 'relation': 'viewer', 'object': 'tool:20'},
            ],
        }

    async def read_tuples(self, user=None, relation=None, object=None):
        self.calls.append({'user': user, 'relation': relation, 'object': object})
        if user is not None:
            raise AssertionError('read_tuples must not be called with user-only filter')
        return self.tuples.get(object, [])


@pytest.mark.asyncio
async def test_build_actual_set_reads_fga_by_object_not_user():
    fake_fga = ObjectOnlyFGA()

    with patch(
        'bisheng.permission.domain.services.permission_service.PermissionService._get_fga',
        return_value=fake_fga,
    ):
        actual = await reconcile_role_access_fga._build_actual_set(
            user_ids={1, 2},
            resource_objects={('workflow', '10'), ('tool', '20')},
        )

    assert actual == {
        ('user:1', 'viewer', 'workflow', '10'),
        ('user:2', 'editor', 'workflow', '10'),
        ('user:2', 'viewer', 'tool', '20'),
    }
    assert fake_fga.calls == [
        {'user': None, 'relation': None, 'object': 'tool:20'},
        {'user': None, 'relation': None, 'object': 'workflow:10'},
    ]


def test_build_compare_report_contains_source_and_planned_counts():
    source = reconcile_role_access_fga.SourcePermissionSnapshot(
        role_access_rows=3,
        expanded_permissions=5,
        desired={
            ('user:1', 'viewer', 'workflow', '10'),
            ('user:2', 'viewer', 'workflow', '10'),
            ('user:2', 'editor', 'tool', '20'),
        },
    )
    actual = {
        ('user:1', 'viewer', 'workflow', '10'),
        ('user:3', 'viewer', 'workflow', '10'),
        ('user:4', 'viewer', 'tool', '20'),
    }
    to_write = source.desired - actual
    stale = actual - source.desired
    protected = {('user:4', 'viewer', 'tool', '20')}
    to_delete = stale - protected

    report = reconcile_role_access_fga._build_compare_report(
        source=source,
        actual=actual,
        to_write=to_write,
        to_delete=to_delete,
        protected=protected,
    )

    assert report['title_zh'] == 'role_access 与 OpenFGA 权限差异 dry-run 对比报告'
    assert 'source_unique_permissions' in report['field_notes_zh']
    assert report['summary'] == {
        'source_role_access_rows': 3,
        'source_expanded_permissions': 5,
        'source_unique_permissions': 3,
        'actual_fga_permissions': 3,
        'planned_writes': 2,
        'planned_deletes': 1,
        'protected_permissions': 1,
        'actual_only_permissions': 2,
    }
    assert report['aggregates']['planned_writes']['by_object_type'] == {
        'tool': 1,
        'workflow': 1,
    }
    assert report['details']['planned_writes'] == [
        {
            'user': 'user:2',
            'relation': 'editor',
            'object_type': 'tool',
            'resource_id': '20',
            'object': 'tool:20',
        },
        {
            'user': 'user:2',
            'relation': 'viewer',
            'object_type': 'workflow',
            'resource_id': '10',
            'object': 'workflow:10',
        },
    ]


def test_write_report_outputs_json_file(tmp_path):
    report_path = tmp_path / 'compare.json'
    report = {'summary': {'planned_writes': 2}, 'details': {'planned_writes': []}}

    reconcile_role_access_fga._write_report(report, str(report_path))

    assert json.loads(report_path.read_text(encoding='utf-8')) == report


def test_export_workspace_report_writes_jsonl_files(tmp_path):
    workspace = tmp_path / 'work.sqlite3'
    report_dir = tmp_path / 'report'
    conn = reconcile_role_access_fga._create_workspace(str(workspace))
    try:
        reconcile_role_access_fga._insert_tuples(
            conn,
            'desired_tuple',
            [('user:1', 'viewer', 'workflow', '10')],
        )
        conn.execute(
            'INSERT INTO diff_tuple(action, user, relation, object_type, resource_id) '
            'VALUES (?, ?, ?, ?, ?)',
            ('write', 'user:1', 'viewer', 'workflow', '10'),
        )
        conn.commit()
        summary = {
            'title_zh': 'role_access 与 OpenFGA 权限差异 dry-run 对比报告',
            'field_notes_zh': {'planned_writes': '预写入 OpenFGA 权限数量'},
            'summary': {'planned_writes': 1},
        }

        reconcile_role_access_fga._export_workspace_report(
            conn,
            str(report_dir),
            batch_size=10,
            summary=summary,
        )
    finally:
        conn.close()

    assert json.loads((report_dir / 'summary.json').read_text(encoding='utf-8')) == summary
    aggregates = json.loads((report_dir / 'aggregates.json').read_text(encoding='utf-8'))
    assert aggregates['说明'].startswith('按 action 维度统计权限差异')
    lines = (report_dir / 'planned_writes.jsonl').read_text(encoding='utf-8').splitlines()
    assert lines == [
        '{"user": "user:1", "relation": "viewer", "object_type": "workflow", '
        '"resource_id": "10", "object": "workflow:10"}'
    ]


def test_space_channel_member_tuple_can_be_protected_from_delete(tmp_path):
    workspace = tmp_path / 'work.sqlite3'
    conn = reconcile_role_access_fga._create_workspace(str(workspace))
    try:
        reconcile_role_access_fga._insert_candidate_users(conn, ['user:1'])
        reconcile_role_access_fga._insert_tuples(
            conn,
            'actual_tuple',
            [('user:1', 'viewer', 'knowledge_space', 'sp-1')],
        )
        reconcile_role_access_fga._insert_tuples(
            conn,
            'protected_tuple',
            [('user:1', 'viewer', 'knowledge_space', 'sp-1')],
        )

        reconcile_role_access_fga._compute_workspace_diff(conn)

        assert conn.execute(
            "SELECT COUNT(*) FROM diff_tuple WHERE action = 'delete'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM diff_tuple WHERE action = 'protected'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_workspace_summary_contains_chinese_notes(tmp_path):
    workspace = tmp_path / 'work.sqlite3'
    conn = reconcile_role_access_fga._create_workspace(str(workspace))
    try:
        summary = reconcile_role_access_fga._workspace_summary(
            conn,
            source_role_access_rows=1,
            source_expanded_permissions=2,
            fga_read_failures=0,
        )
    finally:
        conn.close()

    assert summary['title_zh'] == 'role_access 与 OpenFGA 权限差异 dry-run 对比报告'
    assert 'planned_deletes' in summary['field_notes_zh']
    assert 'planned_writes.jsonl' in summary['detail_file_notes_zh']


@pytest.mark.asyncio
async def test_reconcile_writes_before_deletes(monkeypatch):
    calls = []

    async def fake_populate_desired(conn, batch_size, progress=None):
        reconcile_role_access_fga._insert_tuples(
            conn,
            'desired_tuple',
            [('user:1', 'viewer', 'workflow', 'new')],
        )
        return 1, 1

    async def fake_noop(*args, **kwargs):
        return None

    async def fake_populate_actual(conn, batch_size, progress=None):
        reconcile_role_access_fga._insert_candidate_users(conn, ['user:1'])
        reconcile_role_access_fga._insert_tuples(
            conn,
            'actual_tuple',
            [('user:1', 'viewer', 'workflow', 'old')],
        )
        return 0

    async def fake_batch_write_tuples(operations, crash_safe=True):
        calls.append([operation.action for operation in operations])

    monkeypatch.setattr(reconcile_role_access_fga, '_populate_desired_workspace', fake_populate_desired)
    monkeypatch.setattr(reconcile_role_access_fga, '_populate_candidate_users', fake_noop)
    monkeypatch.setattr(reconcile_role_access_fga, '_populate_candidate_resources', fake_noop)
    monkeypatch.setattr(reconcile_role_access_fga, '_populate_actual_workspace', fake_populate_actual)
    monkeypatch.setattr(reconcile_role_access_fga, '_populate_protected_workspace', fake_noop)

    from bisheng.permission.domain.services.permission_cache import PermissionCache
    from bisheng.permission.domain.services.permission_service import PermissionService

    monkeypatch.setattr(PermissionService, 'batch_write_tuples', fake_batch_write_tuples)
    monkeypatch.setattr(PermissionCache, 'invalidate_user', AsyncMock())

    stats = await reconcile_role_access_fga._reconcile_with_workspace(
        dry_run=False,
        batch_size=10,
    )

    assert calls == [['write'], ['delete']]
    assert stats.written == 1
    assert stats.deleted == 1


@pytest.mark.asyncio
async def test_reconcile_invalid_batch_size_rejected():
    with pytest.raises(ValueError, match='batch_size must be greater than 0'):
        await reconcile_role_access_fga._reconcile_with_workspace(
            dry_run=True,
            batch_size=0,
        )
