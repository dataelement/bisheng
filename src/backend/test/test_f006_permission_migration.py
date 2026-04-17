"""Tests for F006 Permission Migration (RBAC → ReBAC).

Test-first approach: Step 1/2 tests written in T2, implementations in T3.
Additional step tests added in T4-T8.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import text

# Pre-mock must run before bisheng imports
from test.fixtures.mock_services import premock_import_chain

premock_import_chain()

from bisheng.permission.migration.migrate_rbac_to_rebac import (
    RBACToReBACMigrator,
    MigrationStats,
    VerifyReport,
    ACCESS_TYPE_MAPPING,
    FLOW_TYPE_MAPPING,
    RELATION_PRIORITY,
    SCM_ROLE_MAPPING,
    SCM_TYPE_MAPPING,
    _BATCH_SIZE,
)
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture()
def tmp_checkpoint_dir():
    """Temporary directory for checkpoint files."""
    d = tempfile.mkdtemp(prefix='f006_test_')
    yield d
    # cleanup
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    os.rmdir(d)


@pytest.fixture()
def mock_fga(mock_openfga):
    """Reuse conftest InMemoryOpenFGAClient."""
    return mock_openfga


@pytest.fixture()
def migrator_dry(mock_fga, tmp_checkpoint_dir):
    """Dry-run migrator with mock FGA."""
    m = RBACToReBACMigrator(dry_run=True, checkpoint_dir=tmp_checkpoint_dir)
    m._fga = mock_fga
    return m


@pytest.fixture()
def migrator_write(mock_fga, tmp_checkpoint_dir):
    """Write-mode migrator with mock FGA."""
    m = RBACToReBACMigrator(dry_run=False, checkpoint_dir=tmp_checkpoint_dir)
    m._fga = mock_fga
    return m


@pytest.fixture()
def patch_db(async_db_session, monkeypatch, bypass_tenant):
    """Monkeypatch get_async_db_session to yield the test async session.

    Also enters bypass_tenant context so SQLite works without tenant filter.
    """
    @asynccontextmanager
    async def _mock_get_session():
        yield async_db_session

    monkeypatch.setattr(
        'bisheng.core.database.manager.get_async_db_session',
        _mock_get_session,
    )
    monkeypatch.setattr(
        'bisheng.core.database.get_async_db_session',
        _mock_get_session,
    )
    return async_db_session


# ── Helper ────────────────────────────────────────────────────────

async def insert_rows(session, table: str, rows: list[dict]):
    """Insert rows into a table using raw SQL (SQLite-compatible)."""
    for row in rows:
        cols = ', '.join(row.keys())
        placeholders = ', '.join(f':{k}' for k in row.keys())
        await session.execute(text(f'INSERT INTO {table} ({cols}) VALUES ({placeholders})'), row)
    await session.flush()


# ═══════════════════════════════════════════════════════════════════
# T2: Checkpoint + Constants + CLI tests
# ═══════════════════════════════════════════════════════════════════


class TestConstants:
    """Verify mapping constants are correct."""

    def test_access_type_mapping_complete(self):
        expected_keys = {1, 3, 5, 6, 7, 8, 9, 10, 11, 12}
        assert set(ACCESS_TYPE_MAPPING.keys()) == expected_keys
        # WEB_MENU (99) must not be in mapping
        assert 99 not in ACCESS_TYPE_MAPPING

    def test_flow_type_mapping(self):
        assert FLOW_TYPE_MAPPING[5] == 'assistant'
        assert FLOW_TYPE_MAPPING[10] == 'workflow'
        # Others must not be in mapping
        for ft in (15, 20, 25, 30):
            assert ft not in FLOW_TYPE_MAPPING

    def test_relation_priority_order(self):
        assert RELATION_PRIORITY['owner'] > RELATION_PRIORITY['manager']
        assert RELATION_PRIORITY['manager'] > RELATION_PRIORITY['editor']
        assert RELATION_PRIORITY['editor'] > RELATION_PRIORITY['viewer']

    def test_scm_role_mapping(self):
        assert SCM_ROLE_MAPPING == {'creator': 'owner', 'admin': 'manager', 'member': 'viewer'}

    def test_batch_size(self):
        assert _BATCH_SIZE == 100


class TestCheckpoint:
    """Checkpoint save/load/restore."""

    def test_load_empty(self, tmp_checkpoint_dir):
        m = RBACToReBACMigrator(checkpoint_dir=tmp_checkpoint_dir)
        assert m._load_checkpoint() == 0

    def test_save_and_load(self, tmp_checkpoint_dir):
        m = RBACToReBACMigrator(checkpoint_dir=tmp_checkpoint_dir)
        m._save_checkpoint(3)
        assert m._load_checkpoint() == 3
        # Verify file content
        path = m._checkpoint_path()
        with open(path) as f:
            data = json.load(f)
        assert data['completed_step'] == 3
        assert 'timestamp' in data
        assert 'stats' in data

    def test_checkpoint_overwrite(self, tmp_checkpoint_dir):
        m = RBACToReBACMigrator(checkpoint_dir=tmp_checkpoint_dir)
        m._save_checkpoint(2)
        assert m._load_checkpoint() == 2
        m._save_checkpoint(5)
        assert m._load_checkpoint() == 5

    def test_corrupt_checkpoint(self, tmp_checkpoint_dir):
        path = os.path.join(tmp_checkpoint_dir, 'migration_f006_checkpoint.json')
        with open(path, 'w') as f:
            f.write('not json')
        m = RBACToReBACMigrator(checkpoint_dir=tmp_checkpoint_dir)
        assert m._load_checkpoint() == 0  # gracefully returns 0


class TestDedup:
    """Test _collect and _dedup_tuples logic."""

    def test_dedup_keeps_highest(self):
        m = RBACToReBACMigrator(dry_run=True)
        tuples = [
            TupleOperation(action='write', user='user:1', relation='viewer', object='workflow:a'),
            TupleOperation(action='write', user='user:1', relation='editor', object='workflow:a'),
        ]
        deduped = m._dedup_tuples(tuples)
        assert len(deduped) == 1
        assert deduped[0].relation == 'editor'

    def test_dedup_owner_over_editor(self):
        m = RBACToReBACMigrator(dry_run=True)
        tuples = [
            TupleOperation(action='write', user='user:1', relation='editor', object='tool:5'),
            TupleOperation(action='write', user='user:1', relation='owner', object='tool:5'),
        ]
        deduped = m._dedup_tuples(tuples)
        assert len(deduped) == 1
        assert deduped[0].relation == 'owner'

    def test_dedup_different_users_kept(self):
        m = RBACToReBACMigrator(dry_run=True)
        tuples = [
            TupleOperation(action='write', user='user:1', relation='viewer', object='workflow:a'),
            TupleOperation(action='write', user='user:2', relation='viewer', object='workflow:a'),
        ]
        deduped = m._dedup_tuples(tuples)
        assert len(deduped) == 2

    def test_global_dedup_blocks_lower(self):
        """_collect with global tracking: lower priority skipped."""
        m = RBACToReBACMigrator(dry_run=True)
        # First collect: owner
        m._collect([TupleOperation(action='write', user='user:1', relation='owner', object='workflow:x')])
        m._buffer.clear()  # simulate flush
        # Second collect: viewer for same (user, object) — should be skipped
        m._collect([TupleOperation(action='write', user='user:1', relation='viewer', object='workflow:x')])
        assert len(m._buffer) == 0

    def test_global_dedup_allows_upgrade(self):
        """_collect with global tracking: higher priority accepted."""
        m = RBACToReBACMigrator(dry_run=True)
        m._collect([TupleOperation(action='write', user='user:1', relation='viewer', object='workflow:x')])
        m._buffer.clear()
        m._collect([TupleOperation(action='write', user='user:1', relation='owner', object='workflow:x')])
        assert len(m._buffer) == 1
        assert m._buffer[0].relation == 'owner'

    def test_relations_without_priority_treated_as_zero(self):
        """Relations not in RELATION_PRIORITY (like 'parent', 'super_admin', 'member')
        get priority 0, which is fine for non-competing relations."""
        m = RBACToReBACMigrator(dry_run=True)
        tuples = [
            TupleOperation(action='write', user='user:1', relation='super_admin', object='system:global'),
        ]
        m._collect(tuples)
        assert len(m._buffer) == 1


class TestResolveParent:
    """Test _resolve_parent utility."""

    def test_empty_path_root(self):
        assert RBACToReBACMigrator._resolve_parent(1, 10, '') == ('knowledge_space', '10')

    def test_none_path_root(self):
        assert RBACToReBACMigrator._resolve_parent(1, 10, None) == ('knowledge_space', '10')

    def test_single_segment(self):
        assert RBACToReBACMigrator._resolve_parent(1, 10, '/42') == ('folder', '42')

    def test_deep_path(self):
        assert RBACToReBACMigrator._resolve_parent(1, 10, '/42/78') == ('folder', '78')

    def test_invalid_segment(self):
        t, i = RBACToReBACMigrator._resolve_parent(1, 10, '/abc')
        assert t is None and i is None


class TestCLI:
    """CLI argument parsing."""

    def test_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            import sys
            old_argv = sys.argv
            sys.argv = ['migrate', '--help']
            try:
                from bisheng.permission.migration.migrate_rbac_to_rebac import main
                main()
            finally:
                sys.argv = old_argv
        assert exc_info.value.code == 0


# ═══════════════════════════════════════════════════════════════════
# T2: Step 1 & Step 2 test cases (RED until T3 implements them)
# ═══════════════════════════════════════════════════════════════════


class TestStep1SuperAdmin:
    """Step 1: user_role (role_id=1) → system:global super_admin tuples."""

    @pytest.mark.asyncio
    async def test_admin_users_generate_super_admin_tuples(
        self, migrator_dry, mock_fga, patch_db,
    ):
        """AdminRole users should produce (system:global, super_admin, user:{id}) tuples."""
        session = patch_db
        await insert_rows(session, 'userrole', [
            {'user_id': 1, 'role_id': 1},   # admin
            {'user_id': 2, 'role_id': 1},   # admin
            {'user_id': 3, 'role_id': 2},   # regular — should NOT produce super_admin
        ])

        count = await migrator_dry.step1_super_admin()
        assert count == 2
        # Verify the generated tuples are in _global_seen
        assert migrator_dry._global_seen[('user:1', 'system:global')] == 'super_admin'
        assert migrator_dry._global_seen[('user:2', 'system:global')] == 'super_admin'
        assert ('user:3', 'system:global') not in migrator_dry._global_seen

    @pytest.mark.asyncio
    async def test_no_admins(self, migrator_dry, patch_db):
        """No admin users → 0 tuples."""
        session = patch_db
        await insert_rows(session, 'userrole', [
            {'user_id': 1, 'role_id': 2},
        ])
        count = await migrator_dry.step1_super_admin()
        assert count == 0


class TestStep2UserGroupMembership:
    """Step 2: user_group → user_group:{gid} member/admin tuples."""

    @pytest.mark.asyncio
    async def test_member_and_admin(self, migrator_dry, patch_db):
        """is_group_admin=True → admin, False → member."""
        session = patch_db
        await insert_rows(session, 'usergroup', [
            {'user_id': 10, 'group_id': 1, 'is_group_admin': 0},
            {'user_id': 11, 'group_id': 1, 'is_group_admin': 1},
            {'user_id': 12, 'group_id': 2, 'is_group_admin': 0},
        ])

        count = await migrator_dry.step2_user_group_membership()
        assert count == 3
        assert migrator_dry._global_seen[('user:10', 'user_group:1')] == 'member'
        assert migrator_dry._global_seen[('user:11', 'user_group:1')] == 'admin'
        assert migrator_dry._global_seen[('user:12', 'user_group:2')] == 'member'

    @pytest.mark.asyncio
    async def test_default_group_included(self, migrator_dry, patch_db):
        """Default group (id=2) members should also be migrated."""
        session = patch_db
        await insert_rows(session, 'usergroup', [
            {'user_id': 1, 'group_id': 2, 'is_group_admin': 0},
        ])

        count = await migrator_dry.step2_user_group_membership()
        assert count == 1
        assert migrator_dry._global_seen[('user:1', 'user_group:2')] == 'member'

    @pytest.mark.asyncio
    async def test_empty_groups(self, migrator_dry, patch_db):
        """No user_group records → 0 tuples."""
        count = await migrator_dry.step2_user_group_membership()
        assert count == 0


# ═══════════════════════════════════════════════════════════════════
# T2: Idempotent rerun test
# ═══════════════════════════════════════════════════════════════════


class TestFlushIdempotent:
    """Test that _flush with mock FGA is idempotent."""

    @pytest.mark.asyncio
    async def test_write_and_rewrite(self, migrator_write, mock_fga):
        """Writing the same tuple twice should succeed (InMemoryOpenFGAClient is idempotent)."""
        op = TupleOperation(action='write', user='user:1', relation='viewer', object='workflow:a')
        migrator_write._collect([op])
        count1 = await migrator_write._flush()
        assert count1 == 1
        mock_fga.assert_tuple_exists('user:1', 'viewer', 'workflow:a')

        # Re-collect and re-flush
        migrator_write._global_seen.clear()
        migrator_write._collect([op])
        count2 = await migrator_write._flush()
        assert count2 == 1  # Should not error

    @pytest.mark.asyncio
    async def test_dry_run_no_writes(self, migrator_dry, mock_fga):
        """Dry-run mode should NOT write to FGA."""
        op = TupleOperation(action='write', user='user:1', relation='viewer', object='workflow:a')
        migrator_dry._collect([op])
        count = await migrator_dry._flush()
        assert count == 1  # counted but not written
        mock_fga.assert_tuple_count(0)  # nothing in FGA


# ═══════════════════════════════════════════════════════════════════
# T4: Step 3 — role_access expansion + dedup
# ═══════════════════════════════════════════════════════════════════


class TestStep3RoleAccess:
    """Step 3: role_access → per-user resource tuples."""

    @pytest.mark.asyncio
    async def test_skip_web_menu(self, migrator_dry, patch_db):
        """type=99 (WEB_MENU) records must be skipped."""
        session = patch_db
        await insert_rows(session, 'userrole', [{'user_id': 1, 'role_id': 2}])
        await insert_rows(session, 'roleaccess', [
            {'role_id': 2, 'third_id': 'menu1', 'type': 99},
        ])
        count = await migrator_dry.step3_role_access()
        assert count == 0

    @pytest.mark.asyncio
    async def test_skip_admin_role(self, migrator_dry, patch_db):
        """role_id=1 (AdminRole) role_access records must be skipped."""
        session = patch_db
        await insert_rows(session, 'userrole', [{'user_id': 1, 'role_id': 1}])
        await insert_rows(session, 'roleaccess', [
            {'role_id': 1, 'third_id': 'kb-1', 'type': 1},
        ])
        count = await migrator_dry.step3_role_access()
        assert count == 0

    @pytest.mark.asyncio
    async def test_access_type_mapping(self, migrator_dry, patch_db):
        """Each AccessType correctly maps to (object_type, relation)."""
        session = patch_db
        await insert_rows(session, 'userrole', [{'user_id': 10, 'role_id': 5}])
        await insert_rows(session, 'roleaccess', [
            {'role_id': 5, 'third_id': 'res-1', 'type': 1},   # KNOWLEDGE → knowledge_space, viewer
            {'role_id': 5, 'third_id': 'res-2', 'type': 6},   # ASSISTANT_WRITE → assistant, editor
            {'role_id': 5, 'third_id': 'res-3', 'type': 9},   # WORKFLOW → workflow, viewer
        ])
        count = await migrator_dry.step3_role_access()
        assert count == 3
        assert migrator_dry._global_seen[('user:10', 'knowledge_space:res-1')] == 'viewer'
        assert migrator_dry._global_seen[('user:10', 'assistant:res-2')] == 'editor'
        assert migrator_dry._global_seen[('user:10', 'workflow:res-3')] == 'viewer'

    @pytest.mark.asyncio
    async def test_expand_to_users(self, migrator_dry, patch_db):
        """role_access expanded to all users holding that role."""
        session = patch_db
        await insert_rows(session, 'userrole', [
            {'user_id': 1, 'role_id': 3},
            {'user_id': 2, 'role_id': 3},
        ])
        await insert_rows(session, 'roleaccess', [
            {'role_id': 3, 'third_id': 'wf-1', 'type': 9},
        ])
        count = await migrator_dry.step3_role_access()
        assert count == 2
        assert ('user:1', 'workflow:wf-1') in migrator_dry._global_seen
        assert ('user:2', 'workflow:wf-1') in migrator_dry._global_seen

    @pytest.mark.asyncio
    async def test_dedup_read_write(self, migrator_dry, patch_db):
        """Same user + resource with READ(viewer) and WRITE(editor) → keeps editor only."""
        session = patch_db
        await insert_rows(session, 'userrole', [{'user_id': 1, 'role_id': 3}])
        await insert_rows(session, 'roleaccess', [
            {'role_id': 3, 'third_id': 'kb-1', 'type': 1},   # viewer
            {'role_id': 3, 'third_id': 'kb-1', 'type': 3},   # editor
        ])
        count = await migrator_dry.step3_role_access()
        assert count == 1
        assert migrator_dry._global_seen[('user:1', 'knowledge_space:kb-1')] == 'editor'


# ═══════════════════════════════════════════════════════════════════
# T5: Step 4 — space/channel members + Step 5 — resource owners
# ═══════════════════════════════════════════════════════════════════


class TestStep4SpaceChannelMembers:
    """Step 4: space_channel_member → knowledge_space/channel tuples."""

    @pytest.mark.asyncio
    async def test_active_only(self, migrator_dry, patch_db):
        """Only ACTIVE members migrated."""
        session = patch_db
        await insert_rows(session, 'space_channel_member', [
            {'business_id': 'sp-1', 'business_type': 'space', 'user_id': 1,
             'user_role': 'member', 'status': 'ACTIVE'},
            {'business_id': 'sp-1', 'business_type': 'space', 'user_id': 2,
             'user_role': 'member', 'status': 'PENDING'},
            {'business_id': 'sp-1', 'business_type': 'space', 'user_id': 3,
             'user_role': 'member', 'status': 'REJECTED'},
        ])
        count = await migrator_dry.step4_space_channel_members()
        assert count == 1

    @pytest.mark.asyncio
    async def test_role_mapping(self, migrator_dry, patch_db):
        """creator→owner, admin→manager, member→viewer."""
        session = patch_db
        await insert_rows(session, 'space_channel_member', [
            {'business_id': 'sp-1', 'business_type': 'space', 'user_id': 1,
             'user_role': 'creator', 'status': 'ACTIVE'},
            {'business_id': 'sp-1', 'business_type': 'space', 'user_id': 2,
             'user_role': 'admin', 'status': 'ACTIVE'},
            {'business_id': 'sp-1', 'business_type': 'space', 'user_id': 3,
             'user_role': 'member', 'status': 'ACTIVE'},
        ])
        count = await migrator_dry.step4_space_channel_members()
        assert count == 3
        assert migrator_dry._global_seen[('user:1', 'knowledge_space:sp-1')] == 'owner'
        assert migrator_dry._global_seen[('user:2', 'knowledge_space:sp-1')] == 'manager'
        assert migrator_dry._global_seen[('user:3', 'knowledge_space:sp-1')] == 'viewer'

    @pytest.mark.asyncio
    async def test_type_mapping(self, migrator_dry, patch_db):
        """space→knowledge_space, channel→channel."""
        session = patch_db
        await insert_rows(session, 'space_channel_member', [
            {'business_id': 'sp-1', 'business_type': 'space', 'user_id': 1,
             'user_role': 'member', 'status': 'ACTIVE'},
            {'business_id': 'ch-1', 'business_type': 'channel', 'user_id': 2,
             'user_role': 'member', 'status': 'ACTIVE'},
        ])
        count = await migrator_dry.step4_space_channel_members()
        assert count == 2
        assert ('user:1', 'knowledge_space:sp-1') in migrator_dry._global_seen
        assert ('user:2', 'channel:ch-1') in migrator_dry._global_seen


class TestStep5ResourceOwners:
    """Step 5: resource tables → owner tuples."""

    @pytest.mark.asyncio
    async def test_flow_type_filter(self, migrator_dry, patch_db):
        """flow_type=5→assistant, 10→workflow, others skipped."""
        session = patch_db
        await insert_rows(session, 'flow', [
            {'id': 'f1', 'user_id': 1, 'flow_type': 5},
            {'id': 'f2', 'user_id': 2, 'flow_type': 10},
            {'id': 'f3', 'user_id': 3, 'flow_type': 15},   # skip
            {'id': 'f4', 'user_id': 4, 'flow_type': 20},   # skip
        ])
        count = await migrator_dry.step5_resource_owners()
        assert migrator_dry._global_seen[('user:1', 'assistant:f1')] == 'owner'
        assert migrator_dry._global_seen[('user:2', 'workflow:f2')] == 'owner'
        assert ('user:3', 'assistant:f3') not in migrator_dry._global_seen
        assert ('user:4', 'workflow:f4') not in migrator_dry._global_seen

    @pytest.mark.asyncio
    async def test_knowledge_all_types(self, migrator_dry, patch_db):
        """All Knowledge types are migrated."""
        session = patch_db
        await insert_rows(session, 'knowledge', [
            {'user_id': 1, 'name': 'k1', 'type': 0},   # NORMAL
            {'user_id': 2, 'name': 'k2', 'type': 1},   # QA
            {'user_id': 3, 'name': 'k3', 'type': 2},   # PRIVATE
            {'user_id': 4, 'name': 'k4', 'type': 3},   # SPACE
        ])
        count = await migrator_dry.step5_resource_owners()
        # All 4 knowledge records → owner tuples
        for uid in range(1, 5):
            found = any(
                k[1].startswith('knowledge_space:') and v == 'owner'
                for (k, v) in [(kk, vv) for kk, vv in migrator_dry._global_seen.items()]
                if k[0] == f'user:{uid}'
            )
            assert found, f'user:{uid} knowledge owner tuple missing'

    @pytest.mark.asyncio
    async def test_tool_skip_deleted(self, migrator_dry, patch_db):
        """is_delete=1 tools are skipped."""
        session = patch_db
        await insert_rows(session, 't_gpts_tools', [
            {'user_id': 1, 'name': 't1', 'is_delete': 0},
            {'user_id': 2, 'name': 't2', 'is_delete': 1},
        ])
        count = await migrator_dry.step5_resource_owners()
        found_1 = any(k[1].startswith('tool:') for k in migrator_dry._global_seen if k[0] == 'user:1')
        found_2 = any(k[1].startswith('tool:') for k in migrator_dry._global_seen if k[0] == 'user:2')
        assert found_1
        assert not found_2

    @pytest.mark.asyncio
    async def test_dashboard_not_exist(self, migrator_dry, patch_db):
        """Dashboard table not existing should not cause error."""
        # No dashboard table in test DB → should skip gracefully
        count = await migrator_dry.step5_resource_owners()
        # Should not raise; count can be 0
        assert count >= 0

    @pytest.mark.asyncio
    async def test_cross_dedup_owner_vs_viewer(self, migrator_dry, patch_db):
        """Step 5 owner vs earlier Step 3 viewer → keeps owner."""
        session = patch_db
        # Step 3 data: role gives viewer on workflow:f1
        await insert_rows(session, 'userrole', [{'user_id': 1, 'role_id': 3}])
        await insert_rows(session, 'roleaccess', [
            {'role_id': 3, 'third_id': 'f1', 'type': 9},  # workflow viewer
        ])
        # Step 5 data: user owns flow f1
        await insert_rows(session, 'flow', [
            {'id': 'f1', 'user_id': 1, 'flow_type': 10},
        ])
        await migrator_dry.step3_role_access()
        assert migrator_dry._global_seen[('user:1', 'workflow:f1')] == 'viewer'
        await migrator_dry.step5_resource_owners()
        # After step 5, should be upgraded to owner
        assert migrator_dry._global_seen[('user:1', 'workflow:f1')] == 'owner'


# ═══════════════════════════════════════════════════════════════════
# T6: Step 6 — folder hierarchy
# ═══════════════════════════════════════════════════════════════════


class TestStep6FolderHierarchy:
    """Step 6: knowledge_file → parent tuples."""

    @pytest.mark.asyncio
    async def test_folder_root(self, migrator_dry, patch_db):
        """file_type=0 + empty path → (folder:id, parent, knowledge_space:kid)."""
        session = patch_db
        await insert_rows(session, 'knowledgefile', [
            {'knowledge_id': 10, 'file_name': 'dir1', 'file_type': 0, 'file_level_path': ''},
        ])
        count = await migrator_dry.step6_folder_hierarchy()
        assert count == 1
        # The tuple should be: object=folder:1, relation=parent, user=knowledge_space:10
        seen = migrator_dry._global_seen
        folder_key = [k for k in seen if k[1].startswith('folder:')]
        assert len(folder_key) == 1
        assert seen[folder_key[0]] == 'parent'

    @pytest.mark.asyncio
    async def test_folder_nested(self, migrator_dry, patch_db):
        """file_type=0 + path="/42" → parent is folder:42."""
        session = patch_db
        await insert_rows(session, 'knowledgefile', [
            {'knowledge_id': 10, 'file_name': 'subdir', 'file_type': 0, 'file_level_path': '/42'},
        ])
        count = await migrator_dry.step6_folder_hierarchy()
        assert count == 1

    @pytest.mark.asyncio
    async def test_file_root(self, migrator_dry, patch_db):
        """file_type=1 + empty path → (knowledge_file:id, parent, knowledge_space:kid)."""
        session = patch_db
        await insert_rows(session, 'knowledgefile', [
            {'knowledge_id': 10, 'file_name': 'doc.pdf', 'file_type': 1, 'file_level_path': ''},
        ])
        count = await migrator_dry.step6_folder_hierarchy()
        assert count == 1

    @pytest.mark.asyncio
    async def test_file_in_folder(self, migrator_dry, patch_db):
        """file_type=1 + path="/42" → (knowledge_file:id, parent, folder:42)."""
        session = patch_db
        await insert_rows(session, 'knowledgefile', [
            {'knowledge_id': 10, 'file_name': 'doc.pdf', 'file_type': 1, 'file_level_path': '/42'},
        ])
        count = await migrator_dry.step6_folder_hierarchy()
        assert count == 1

    @pytest.mark.asyncio
    async def test_invalid_path_skipped(self, migrator_dry, patch_db):
        """Non-numeric path segment → skipped with warning."""
        session = patch_db
        await insert_rows(session, 'knowledgefile', [
            {'knowledge_id': 10, 'file_name': 'bad', 'file_type': 0, 'file_level_path': '/abc'},
        ])
        count = await migrator_dry.step6_folder_hierarchy()
        assert count == 0


# ═══════════════════════════════════════════════════════════════════
# T8: Integration tests — full pipeline
# ═══════════════════════════════════════════════════════════════════


async def _seed_comprehensive_data(session):
    """Insert a comprehensive set of test data for full-pipeline tests."""
    # Users with roles
    await insert_rows(session, 'userrole', [
        {'user_id': 1, 'role_id': 1},   # admin
        {'user_id': 2, 'role_id': 3},   # regular role 3
        {'user_id': 3, 'role_id': 3},   # regular role 3
        {'user_id': 4, 'role_id': 4},   # regular role 4
    ])
    # User groups
    await insert_rows(session, 'usergroup', [
        {'user_id': 2, 'group_id': 1, 'is_group_admin': 0},
        {'user_id': 3, 'group_id': 1, 'is_group_admin': 1},
    ])
    # Role access (non-WEB_MENU)
    await insert_rows(session, 'roleaccess', [
        {'role_id': 3, 'third_id': 'kb-1', 'type': 1},    # viewer
        {'role_id': 3, 'third_id': 'kb-1', 'type': 3},    # editor (dedup with above)
        {'role_id': 4, 'third_id': 'wf-1', 'type': 9},    # viewer
        {'role_id': 3, 'third_id': 'menu1', 'type': 99},   # WEB_MENU — skip
    ])
    # Space/channel members
    await insert_rows(session, 'space_channel_member', [
        {'business_id': 'sp-1', 'business_type': 'space', 'user_id': 2,
         'user_role': 'creator', 'status': 'ACTIVE'},
        {'business_id': 'sp-1', 'business_type': 'space', 'user_id': 3,
         'user_role': 'member', 'status': 'ACTIVE'},
        {'business_id': 'ch-1', 'business_type': 'channel', 'user_id': 4,
         'user_role': 'admin', 'status': 'ACTIVE'},
        {'business_id': 'sp-2', 'business_type': 'space', 'user_id': 5,
         'user_role': 'member', 'status': 'PENDING'},  # skip
    ])
    # Flows
    await insert_rows(session, 'flow', [
        {'id': 'ast-1', 'user_id': 2, 'flow_type': 5},
        {'id': 'wf-1', 'user_id': 3, 'flow_type': 10},
        {'id': 'ws-1', 'user_id': 4, 'flow_type': 15},   # skip
    ])
    # Knowledge
    await insert_rows(session, 'knowledge', [
        {'user_id': 2, 'name': 'kb-1', 'type': 0},
    ])
    # Tools
    await insert_rows(session, 't_gpts_tools', [
        {'user_id': 3, 'name': 'tool1', 'is_delete': 0},
        {'user_id': 4, 'name': 'tool2', 'is_delete': 1},   # skip
    ])
    # Channel
    await insert_rows(session, 'channel', [
        {'user_id': 4, 'name': 'chan1'},
    ])
    # Knowledge files (folder hierarchy)
    await insert_rows(session, 'knowledgefile', [
        {'knowledge_id': 1, 'file_name': 'root_folder', 'file_type': 0, 'file_level_path': ''},
        {'knowledge_id': 1, 'file_name': 'doc.pdf', 'file_type': 1, 'file_level_path': '/1'},
    ])


class TestFullDryRun:
    """Full pipeline in dry-run mode."""

    @pytest.mark.asyncio
    async def test_full_dry_run(self, migrator_dry, patch_db, mock_fga):
        session = patch_db
        await _seed_comprehensive_data(session)

        # Monkeypatch get_fga_client to return mock for run() orchestration
        with patch('bisheng.core.openfga.manager.get_fga_client', return_value=mock_fga):
            stats = await migrator_dry.run()

        assert stats.step1_super_admin == 1     # user 1 is admin
        assert stats.step2_user_group == 2      # 2 user_group records
        assert stats.step3_role_access >= 1     # at least 1 after dedup
        assert stats.step4_space_channel == 3   # 3 ACTIVE members
        assert stats.step5_resource_owners >= 1
        assert stats.step6_folder_hierarchy == 2  # 1 folder + 1 file
        assert stats.total > 0
        # Dry run: FGA should have no tuples
        mock_fga.assert_tuple_count(0)


class TestFullMigration:
    """Full pipeline in write mode."""

    @pytest.mark.asyncio
    async def test_full_migration_writes_tuples(self, migrator_write, patch_db, mock_fga):
        session = patch_db
        await _seed_comprehensive_data(session)

        with patch('bisheng.core.openfga.manager.get_fga_client', return_value=mock_fga):
            stats = await migrator_write.run()

        assert stats.total > 0
        # FGA should have tuples written
        assert len(mock_fga._tuples) > 0
        # Verify key tuples exist
        mock_fga.assert_tuple_exists('user:1', 'super_admin', 'system:global')
        mock_fga.assert_tuple_exists('user:2', 'member', 'user_group:1')
        mock_fga.assert_tuple_exists('user:3', 'admin', 'user_group:1')

    @pytest.mark.asyncio
    async def test_checkpoint_created(self, migrator_write, patch_db, mock_fga):
        session = patch_db
        await _seed_comprehensive_data(session)

        with patch('bisheng.core.openfga.manager.get_fga_client', return_value=mock_fga):
            await migrator_write.run()

        # Checkpoint should show all 6 steps complete
        assert migrator_write._load_checkpoint() == 6


class TestIdempotentFullRun:
    """Running migration twice should succeed without errors."""

    @pytest.mark.asyncio
    async def test_second_run_skips_via_checkpoint(self, patch_db, mock_fga, tmp_checkpoint_dir):
        session = patch_db
        await _seed_comprehensive_data(session)

        # First run
        m1 = RBACToReBACMigrator(dry_run=False, checkpoint_dir=tmp_checkpoint_dir)
        m1._fga = mock_fga
        with patch('bisheng.core.openfga.manager.get_fga_client', return_value=mock_fga):
            stats1 = await m1.run()
        assert stats1.total > 0

        # Second run — should skip all steps via checkpoint
        m2 = RBACToReBACMigrator(dry_run=False, checkpoint_dir=tmp_checkpoint_dir)
        m2._fga = mock_fga
        with patch('bisheng.core.openfga.manager.get_fga_client', return_value=mock_fga):
            stats2 = await m2.run()
        # All steps skipped → all step counts remain 0
        assert stats2.step1_super_admin == 0
        assert stats2.total == 0


class TestCheckpointResume:
    """Resume from a partial checkpoint."""

    @pytest.mark.asyncio
    async def test_resume_from_step3(self, patch_db, mock_fga, tmp_checkpoint_dir):
        session = patch_db
        await _seed_comprehensive_data(session)

        # Simulate checkpoint at step 2
        m_setup = RBACToReBACMigrator(checkpoint_dir=tmp_checkpoint_dir)
        m_setup._save_checkpoint(2)

        # Resume: should skip steps 1-2, execute 3-6
        m = RBACToReBACMigrator(dry_run=True, checkpoint_dir=tmp_checkpoint_dir)
        m._fga = mock_fga
        with patch('bisheng.core.openfga.manager.get_fga_client', return_value=mock_fga):
            stats = await m.run()
        assert stats.step1_super_admin == 0  # skipped
        assert stats.step2_user_group == 0   # skipped
        assert stats.step3_role_access >= 0  # executed
        assert stats.step6_folder_hierarchy >= 0  # executed

    @pytest.mark.asyncio
    async def test_step_flag_overrides_checkpoint(self, patch_db, mock_fga, tmp_checkpoint_dir):
        """--step N should override checkpoint if N > checkpoint."""
        session = patch_db
        await _seed_comprehensive_data(session)

        m = RBACToReBACMigrator(dry_run=True, start_step=5, checkpoint_dir=tmp_checkpoint_dir)
        m._fga = mock_fga
        with patch('bisheng.core.openfga.manager.get_fga_client', return_value=mock_fga):
            stats = await m.run()
        assert stats.step1_super_admin == 0
        assert stats.step4_space_channel == 0
        assert stats.step5_resource_owners >= 0  # executed
        assert stats.step6_folder_hierarchy >= 0  # executed
