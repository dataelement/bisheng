"""Tests for F015 :mod:`bisheng.org_sync.domain.services.remote_dept_differ`.

The differ is a pure function so every test exercises a hand-built
snapshot of local departments + remote DTOs and inspects the returned
``ReconcileDiff``. No DB, Redis, or mocks required.

Covers:

- CreateDept → UpsertOp(is_new=True) with the requested ``ts``.
- UpdateDept → UpsertOp(is_new=False) preserving the existing
  ``dept_id`` (reconcile service re-uses it for same-id updates).
- ArchiveDept → ArchiveOp carrying ``mounted_tenant_id`` so the
  reconcile service can trigger orphan handling.
- MoveDept across tenant boundaries marks ``crosses_tenant=True`` so
  ``UserTenantSyncService.sync_user`` fires for every primary member.
- MoveDept within the same leaf tenant leaves ``crosses_tenant=False``.
- F009 topological ordering passes through (parents before children on
  upserts).
"""

from types import SimpleNamespace

import pytest

from bisheng.org_sync.domain.schemas.remote_dto import RemoteDepartmentDTO
from bisheng.org_sync.domain.services.remote_dept_differ import (
    ArchiveOp,
    MoveOp,
    RemoteDeptDiffer,
    UpsertOp,
)


def _make_local(
    *,
    id: int,
    external_id: str,
    name: str,
    parent_id=None,
    source: str = 'sso',
    is_tenant_root: int = 0,
    mounted_tenant_id=None,
    sort_order: int = 0,
    path: str = '',
    status: str = 'active',
) -> SimpleNamespace:
    """Lightweight stand-in for the :class:`Department` ORM row.

    The differ only reads attributes (``external_id``, ``name``,
    ``parent_id``, ``source``, ``is_tenant_root``, ``mounted_tenant_id``,
    ``sort_order``, ``path``, ``status``, ``id``) so a ``SimpleNamespace``
    is sufficient and avoids coupling to the full SQLModel metadata.
    """
    return SimpleNamespace(
        id=id, external_id=external_id, name=name, parent_id=parent_id,
        source=source, is_tenant_root=is_tenant_root,
        mounted_tenant_id=mounted_tenant_id, sort_order=sort_order,
        path=path, status=status,
    )


# -------------------------------------------------------------------------
# Upserts
# -------------------------------------------------------------------------


class TestUpserts:

    def test_diff_new_dept_generates_upsert_op_with_ts(self):
        remote = [RemoteDepartmentDTO(external_id='E1', name='New')]
        local: list = []
        diff = RemoteDeptDiffer.diff(remote, local, source='sso', ts=1000)
        assert len(diff.upserts) == 1
        op = diff.upserts[0]
        assert isinstance(op, UpsertOp)
        assert op.external_id == 'E1'
        assert op.incoming_ts == 1000
        assert op.is_new is True
        assert op.existing_dept_id is None
        assert diff.archives == []
        assert diff.moves == []

    def test_diff_rename_generates_upsert_op_preserves_existing_id(self):
        # Existing row with mount flags — the differ must surface the
        # original ``dept_id`` so the reconcile service updates the row
        # in place without touching ``is_tenant_root`` / ``mounted_tenant_id``.
        local = [
            _make_local(
                id=5, external_id='E1', name='OldName',
                is_tenant_root=1, mounted_tenant_id=42,
            ),
        ]
        remote = [RemoteDepartmentDTO(external_id='E1', name='NewName')]
        diff = RemoteDeptDiffer.diff(remote, local, source='sso', ts=2000)
        assert len(diff.upserts) == 1
        op = diff.upserts[0]
        assert op.external_id == 'E1'
        assert op.name == 'NewName'
        assert op.existing_dept_id == 5
        assert op.is_new is False
        assert op.incoming_ts == 2000

    def test_diff_topo_sort_parent_before_child(self):
        # Child listed before parent in the remote array — F009 topo
        # order must place the parent first so the reconcile service's
        # parent-chain check always succeeds.
        remote = [
            RemoteDepartmentDTO(external_id='C1', name='Child',
                                parent_external_id='P1'),
            RemoteDepartmentDTO(external_id='P1', name='Parent'),
        ]
        diff = RemoteDeptDiffer.diff(remote, [], source='sso', ts=10)
        ext_order = [op.external_id for op in diff.upserts]
        assert ext_order.index('P1') < ext_order.index('C1')


# -------------------------------------------------------------------------
# Archives
# -------------------------------------------------------------------------


class TestArchives:

    def test_diff_deleted_dept_generates_archive_op(self):
        # Local has E1 with the same source; remote returns nothing.
        local = [
            _make_local(
                id=7, external_id='E1', name='Gone', source='sso',
                mounted_tenant_id=3,
            ),
        ]
        diff = RemoteDeptDiffer.diff([], local, source='sso', ts=500)
        assert diff.upserts == []
        assert len(diff.archives) == 1
        op = diff.archives[0]
        assert isinstance(op, ArchiveOp)
        assert op.external_id == 'E1'
        assert op.dept_id == 7
        assert op.mounted_tenant_id == 3
        assert op.incoming_ts == 500


# -------------------------------------------------------------------------
# Moves + crosses_tenant
# -------------------------------------------------------------------------


class TestMoveCrossTenant:

    def test_diff_move_across_tenant_marks_crosses_tenant_true(self):
        # Two mount points: A→tenant 10, B→tenant 20.
        # E1 currently under A; remote moves it under B.
        mount_a = _make_local(id=1, external_id='MA', name='MountA',
                              is_tenant_root=1, mounted_tenant_id=10)
        mount_b = _make_local(id=2, external_id='MB', name='MountB',
                              is_tenant_root=1, mounted_tenant_id=20)
        e1 = _make_local(id=3, external_id='E1', name='Leaf',
                         parent_id=1, source='sso')
        local = [mount_a, mount_b, e1]
        # Remote keeps E1 name but reparents to MB.
        remote = [
            RemoteDepartmentDTO(external_id='MA', name='MountA'),
            RemoteDepartmentDTO(external_id='MB', name='MountB'),
            RemoteDepartmentDTO(external_id='E1', name='Leaf',
                                parent_external_id='MB'),
        ]
        diff = RemoteDeptDiffer.diff(remote, local, source='sso', ts=999)
        assert len(diff.moves) == 1
        mv = diff.moves[0]
        assert isinstance(mv, MoveOp)
        assert mv.external_id == 'E1'
        assert mv.new_parent_external_id == 'MB'
        assert mv.crosses_tenant is True
        assert mv.incoming_ts == 999

    def test_diff_move_within_same_leaf_tenant_crosses_tenant_false(self):
        # MountA has two children: C1, C2. E1 moves from C1 to C2 —
        # both derive to leaf tenant 10, so crosses_tenant must be False.
        mount_a = _make_local(id=1, external_id='MA', name='MountA',
                              is_tenant_root=1, mounted_tenant_id=10)
        c1 = _make_local(id=2, external_id='C1', name='C1', parent_id=1,
                         source='sso')
        c2 = _make_local(id=3, external_id='C2', name='C2', parent_id=1,
                         source='sso')
        e1 = _make_local(id=4, external_id='E1', name='Leaf', parent_id=2,
                         source='sso')
        local = [mount_a, c1, c2, e1]
        remote = [
            RemoteDepartmentDTO(external_id='MA', name='MountA'),
            RemoteDepartmentDTO(external_id='C1', name='C1',
                                parent_external_id='MA'),
            RemoteDepartmentDTO(external_id='C2', name='C2',
                                parent_external_id='MA'),
            RemoteDepartmentDTO(external_id='E1', name='Leaf',
                                parent_external_id='C2'),
        ]
        diff = RemoteDeptDiffer.diff(remote, local, source='sso', ts=1)
        assert len(diff.moves) == 1
        mv = diff.moves[0]
        assert mv.crosses_tenant is False
