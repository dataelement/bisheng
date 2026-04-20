"""Unit tests for org sync Reconciler — pure logic, no IO.

Covers AC-16 through AC-28 (department + member reconciliation).
"""

import pytest
from unittest.mock import MagicMock

from bisheng.org_sync.domain.schemas.remote_dto import RemoteDepartmentDTO, RemoteMemberDTO
from bisheng.org_sync.domain.services.reconciler import (
    ArchiveDept,
    CreateDept,
    CreateMember,
    DisableMember,
    MoveDept,
    ReactivateMember,
    TransferMember,
    UpdateDept,
    UpdateMember,
    reconcile_departments,
    reconcile_members,
)


# ---------------------------------------------------------------------------
# Helper: mock Department / User objects
# ---------------------------------------------------------------------------

def _make_dept(id, name, parent_id=None, source='feishu', external_id=None, path='/', status='active'):
    dept = MagicMock()
    dept.id = id
    dept.name = name
    dept.parent_id = parent_id
    dept.source = source
    dept.external_id = external_id
    dept.path = path
    dept.status = status
    return dept


def _make_user(user_id, user_name, source='feishu', external_id=None, delete=0, email=None, phone_number=None):
    user = MagicMock()
    user.user_id = user_id
    user.user_name = user_name
    user.source = source
    user.external_id = external_id
    user.delete = delete
    user.email = email
    user.phone_number = phone_number
    return user


def _make_user_dept(user_id, department_id, is_primary=1):
    ud = MagicMock()
    ud.user_id = user_id
    ud.department_id = department_id
    ud.is_primary = is_primary
    return ud


# ===========================================================================
# Department Tests
# ===========================================================================

class TestReconcileDepartments:

    def test_dept_create(self):
        """AC-16: remote has new department → CreateDept."""
        remote = [RemoteDepartmentDTO(external_id='d1', name='Dev')]
        local = []
        ops = reconcile_departments(remote, local, 'feishu')
        assert len(ops) == 1
        assert isinstance(ops[0], CreateDept)
        assert ops[0].remote.external_id == 'd1'

    def test_dept_rename_third_party(self):
        """AC-17: third-party sourced dept renamed → UpdateDept."""
        remote = [RemoteDepartmentDTO(external_id='d1', name='Engineering')]
        local = [_make_dept(1, 'Dev', source='feishu', external_id='d1')]
        ops = reconcile_departments(remote, local, 'feishu')
        updates = [o for o in ops if isinstance(o, UpdateDept)]
        assert len(updates) == 1
        assert updates[0].new_name == 'Engineering'
        assert updates[0].change_source is False

    def test_dept_rename_local(self):
        """AC-18: local-sourced dept matched by external_id → force overwrite."""
        remote = [RemoteDepartmentDTO(external_id='d1', name='Engineering')]
        local = [_make_dept(1, 'Engineering', source='local', external_id='d1')]
        ops = reconcile_departments(remote, local, 'feishu')
        updates = [o for o in ops if isinstance(o, UpdateDept)]
        assert len(updates) == 1
        assert updates[0].change_source is True

    def test_dept_move(self):
        """AC-19: department parent changed → MoveDept."""
        remote = [
            RemoteDepartmentDTO(external_id='d1', name='Dev', parent_external_id=None),
            RemoteDepartmentDTO(external_id='d2', name='QA', parent_external_id='d1'),
        ]
        # d2 is currently under d3 locally, but remote says under d1
        local = [
            _make_dept(1, 'Dev', parent_id=None, source='feishu', external_id='d1', path='/1/'),
            _make_dept(2, 'QA', parent_id=3, source='feishu', external_id='d2', path='/3/2/'),
            _make_dept(3, 'Old', parent_id=None, source='feishu', external_id='d3', path='/3/'),
        ]
        ops = reconcile_departments(remote, local, 'feishu')
        moves = [o for o in ops if isinstance(o, MoveDept)]
        assert len(moves) == 1
        assert moves[0].new_parent_external_id == 'd1'

    def test_dept_archive(self):
        """AC-20: remote dept disappears → ArchiveDept."""
        remote = []
        local = [_make_dept(1, 'Dev', source='feishu', external_id='d1')]
        ops = reconcile_departments(remote, local, 'feishu')
        archives = [o for o in ops if isinstance(o, ArchiveDept)]
        assert len(archives) == 1
        assert archives[0].local.id == 1

    def test_dept_archive_cascade(self):
        """AC-21: archived dept with local child → child also archived."""
        remote = []
        local = [
            _make_dept(1, 'Dev', parent_id=None, source='feishu', external_id='d1', path='/1/'),
            _make_dept(2, 'SubDev', parent_id=1, source='local', external_id=None, path='/1/2/'),
        ]
        ops = reconcile_departments(remote, local, 'feishu')
        archives = [o for o in ops if isinstance(o, ArchiveDept)]
        assert len(archives) == 2

    def test_dept_topological_order(self):
        """Create operations should be parent-first."""
        remote = [
            RemoteDepartmentDTO(external_id='child', name='Child', parent_external_id='parent'),
            RemoteDepartmentDTO(external_id='parent', name='Parent'),
        ]
        ops = reconcile_departments(remote, [], 'feishu')
        creates = [o for o in ops if isinstance(o, CreateDept)]
        assert len(creates) == 2
        assert creates[0].remote.external_id == 'parent'
        assert creates[1].remote.external_id == 'child'

    def test_dept_cycle_detection(self):
        """Circular references in create deps → skip affected nodes."""
        remote = [
            RemoteDepartmentDTO(external_id='a', name='A', parent_external_id='b'),
            RemoteDepartmentDTO(external_id='b', name='B', parent_external_id='a'),
        ]
        ops = reconcile_departments(remote, [], 'feishu')
        creates = [o for o in ops if isinstance(o, CreateDept)]
        # Cycle: both have in-degree 1, neither starts at 0 → both skipped
        assert len(creates) == 0

    def test_dept_empty_input(self):
        """No remote, no local → no operations."""
        ops = reconcile_departments([], [], 'feishu')
        assert len(ops) == 0


# ===========================================================================
# Member Tests
# ===========================================================================

class TestReconcileMembers:

    def test_member_create(self):
        """AC-22: new remote employee → CreateMember."""
        remote = [RemoteMemberDTO(external_id='m1', name='Alice', primary_dept_external_id='d1')]
        ops = reconcile_members(remote, [], {}, {'d1': 1}, 'feishu')
        assert len(ops) == 1
        assert isinstance(ops[0], CreateMember)

    def test_member_update(self):
        """AC-24: info changed → UpdateMember."""
        remote = [RemoteMemberDTO(external_id='m1', name='Alice New', email='new@x.com', primary_dept_external_id='d1')]
        local = [_make_user(1, 'Alice', source='feishu', external_id='m1', email='old@x.com')]
        user_depts = {1: [_make_user_dept(1, 10, is_primary=1)]}
        ops = reconcile_members(remote, local, user_depts, {'d1': 10}, 'feishu')
        updates = [o for o in ops if isinstance(o, UpdateMember)]
        assert len(updates) == 1
        assert updates[0].new_name == 'Alice New'
        assert updates[0].new_email == 'new@x.com'

    def test_member_transfer(self):
        """AC-25: primary department changed → TransferMember."""
        remote = [RemoteMemberDTO(external_id='m1', name='Alice', primary_dept_external_id='d2')]
        local = [_make_user(1, 'Alice', source='feishu', external_id='m1')]
        user_depts = {1: [_make_user_dept(1, 10, is_primary=1)]}
        ext_map = {'d1': 10, 'd2': 20}
        ops = reconcile_members(remote, local, user_depts, ext_map, 'feishu')
        transfers = [o for o in ops if isinstance(o, TransferMember)]
        assert len(transfers) == 1
        assert transfers[0].new_primary_dept_external_id == 'd2'
        assert transfers[0].old_primary_dept_id == 10

    def test_member_secondary_dept_change(self):
        """AC-26: secondary department added/removed."""
        remote = [RemoteMemberDTO(
            external_id='m1', name='Alice',
            primary_dept_external_id='d1',
            secondary_dept_external_ids=['d3'],  # add d3, remove d2
        )]
        local = [_make_user(1, 'Alice', source='feishu', external_id='m1')]
        user_depts = {1: [
            _make_user_dept(1, 10, is_primary=1),
            _make_user_dept(1, 20, is_primary=0),  # d2 secondary, to be removed
        ]}
        ext_map = {'d1': 10, 'd2': 20, 'd3': 30}
        ops = reconcile_members(remote, local, user_depts, ext_map, 'feishu')
        transfers = [o for o in ops if isinstance(o, TransferMember)]
        assert len(transfers) == 1
        assert 30 not in transfers[0].remove_secondary_dept_ids
        assert 20 in transfers[0].remove_secondary_dept_ids

    def test_member_disable(self):
        """AC-27: employee disappeared from remote → DisableMember."""
        remote = []
        local = [_make_user(1, 'Alice', source='feishu', external_id='m1', delete=0)]
        user_depts = {1: [_make_user_dept(1, 10, is_primary=1)]}
        ops = reconcile_members(remote, local, user_depts, {'d1': 10}, 'feishu')
        disables = [o for o in ops if isinstance(o, DisableMember)]
        assert len(disables) == 1
        assert disables[0].user_id == 1

    def test_member_reactivate(self):
        """AC-28: previously disabled user reappears → ReactivateMember."""
        remote = [RemoteMemberDTO(external_id='m1', name='Alice', primary_dept_external_id='d1')]
        local = [_make_user(1, 'Alice', source='feishu', external_id='m1', delete=1)]
        user_depts = {1: []}
        ops = reconcile_members(remote, local, user_depts, {'d1': 10}, 'feishu')
        reactivates = [o for o in ops if isinstance(o, ReactivateMember)]
        assert len(reactivates) == 1
        assert reactivates[0].user_id == 1

    def test_member_local_conflict(self):
        """Local user with matching external_id → force overwrite source."""
        remote = [RemoteMemberDTO(external_id='m1', name='Alice Updated', primary_dept_external_id='d1')]
        local = [_make_user(1, 'Alice', source='local', external_id='m1')]
        user_depts = {1: [_make_user_dept(1, 10, is_primary=1)]}
        ops = reconcile_members(remote, local, user_depts, {'d1': 10}, 'feishu')
        updates = [o for o in ops if isinstance(o, UpdateMember)]
        assert len(updates) == 1
        assert updates[0].change_source is True

    def test_member_empty_input(self):
        """No remote, no local → no operations."""
        ops = reconcile_members([], [], {}, {}, 'feishu')
        assert len(ops) == 0

    def test_member_disabled_remote_status(self):
        """Remote status=disabled → DisableMember even if local is active."""
        remote = [RemoteMemberDTO(external_id='m1', name='Alice', status='disabled', primary_dept_external_id='d1')]
        local = [_make_user(1, 'Alice', source='feishu', external_id='m1', delete=0)]
        user_depts = {1: [_make_user_dept(1, 10, is_primary=1)]}
        ops = reconcile_members(remote, local, user_depts, {'d1': 10}, 'feishu')
        disables = [o for o in ops if isinstance(o, DisableMember)]
        assert len(disables) == 1
