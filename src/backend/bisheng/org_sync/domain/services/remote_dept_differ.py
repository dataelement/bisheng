"""F015 RemoteDeptDiffer — thin wrapper over F009 ``reconcile_departments``.

F015 runs the same remote-vs-local diff that F009 already produced, but
annotates each operation with:

* ``incoming_ts``: the source-system timestamp the Celery beat captured
  when it started the 6h reconcile. Feeds ``OrgSyncTsGuard`` (INV-T12)
  so Gateway realtime pushes and Celery catch-up converge on "ts max
  wins; same-ts upsert/remove → remove wins".
* ``crosses_tenant`` on :class:`MoveOp`: True iff the move changes the
  department's derived leaf tenant. That is the only signal the
  reconcile service needs in order to fire
  ``UserTenantSyncService.sync_user`` for every primary member of the
  moving department.

The differ itself does NO I/O — consumers pass in the full local
snapshot and the remote DTO list. All topological guarantees (parents
before children for upserts, children before parents for archives) are
inherited from :func:`reconcile_departments`.
"""

from dataclasses import dataclass, field
from typing import Optional

from bisheng.database.models.department import Department
from bisheng.org_sync.domain.schemas.remote_dto import RemoteDepartmentDTO
from bisheng.org_sync.domain.services.reconciler import (
    ArchiveDept,
    CreateDept,
    MoveDept,
    UpdateDept,
    reconcile_departments,
)


@dataclass
class UpsertOp:
    """A department to upsert (CREATE or UPDATE semantics)."""

    external_id: str
    name: str
    parent_external_id: Optional[str]
    sort_order: int
    incoming_ts: int
    is_new: bool
    #: Existing ``Department.id`` when the op is an update. ``None`` when
    #: the op will create a fresh row.
    existing_dept_id: Optional[int] = None


@dataclass
class ArchiveOp:
    """A department to soft-archive because the remote no longer lists it."""

    external_id: str
    dept_id: int
    mounted_tenant_id: Optional[int]
    incoming_ts: int


@dataclass
class MoveOp:
    """Parent-change with leaf-tenant impact flag.

    ``crosses_tenant`` drives whether the reconcile service must call
    ``UserTenantSyncService.sync_user`` for each primary member so the
    JWT's ``tenant_id`` + ``token_version`` are refreshed (INV-T2).
    """

    external_id: str
    dept_id: int
    new_parent_external_id: Optional[str]
    crosses_tenant: bool
    incoming_ts: int


@dataclass
class ReconcileDiff:
    upserts: list[UpsertOp] = field(default_factory=list)
    archives: list[ArchiveOp] = field(default_factory=list)
    moves: list[MoveOp] = field(default_factory=list)


class RemoteDeptDiffer:
    """Pure-function diff with F015-specific annotations.

    The class is stateless; it exposes a single ``diff`` classmethod so
    callers can stub it out with a simple ``MagicMock`` in the reconcile
    service integration tests.
    """

    @classmethod
    def diff(
        cls,
        remote_depts: list[RemoteDepartmentDTO],
        local_depts: list[Department],
        source: str,
        ts: int,
    ) -> ReconcileDiff:
        """Diff ``remote`` vs ``local`` and annotate with ``ts``.

        ``ts`` becomes the ``incoming_ts`` on every emitted op. The
        caller is responsible for deriving ``ts`` from the beat start
        time or provider response header — the differ does not call
        ``time.time``.
        """
        ops = reconcile_departments(remote_depts, local_depts, source)

        # Pre-index locals for fast lookups.
        local_by_ext = {d.external_id: d for d in local_depts if d.external_id}
        local_by_id = {d.id: d for d in local_depts}
        remote_by_ext = {d.external_id: d for d in remote_depts}

        result = ReconcileDiff()

        for op in ops:
            if isinstance(op, CreateDept):
                result.upserts.append(UpsertOp(
                    external_id=op.remote.external_id,
                    name=op.remote.name,
                    parent_external_id=op.remote.parent_external_id,
                    sort_order=op.remote.sort_order,
                    incoming_ts=ts,
                    is_new=True,
                    existing_dept_id=None,
                ))
            elif isinstance(op, UpdateDept):
                # Find the matching remote payload for parent + sort_order.
                remote = remote_by_ext.get(op.local.external_id)
                if remote is None:
                    # Shouldn't happen: UpdateDept only emitted when remote
                    # still lists the dept. Fall back to local values.
                    parent_ext = _lookup_parent_external_id(op.local, local_by_id)
                    sort_order = op.local.sort_order
                else:
                    parent_ext = remote.parent_external_id
                    sort_order = remote.sort_order
                result.upserts.append(UpsertOp(
                    external_id=op.local.external_id,
                    name=op.new_name,
                    parent_external_id=parent_ext,
                    sort_order=sort_order,
                    incoming_ts=ts,
                    is_new=False,
                    existing_dept_id=op.local.id,
                ))
            elif isinstance(op, MoveDept):
                # Leaf-tenant derivation: walk to the nearest ancestor with
                # is_tenant_root=1 and read its mounted_tenant_id.
                old_leaf = _derive_leaf_tenant_id(
                    op.local, local_by_id)
                new_leaf = _derive_leaf_tenant_id_for_parent_ext(
                    op.new_parent_external_id, local_by_ext, local_by_id)
                result.moves.append(MoveOp(
                    external_id=op.local.external_id,
                    dept_id=op.local.id,
                    new_parent_external_id=op.new_parent_external_id,
                    crosses_tenant=(old_leaf != new_leaf),
                    incoming_ts=ts,
                ))
            elif isinstance(op, ArchiveDept):
                result.archives.append(ArchiveOp(
                    external_id=op.local.external_id or '',
                    dept_id=op.local.id,
                    mounted_tenant_id=op.local.mounted_tenant_id,
                    incoming_ts=ts,
                ))

        return result


# ---------------------------------------------------------------------------
# Leaf-tenant derivation helpers
# ---------------------------------------------------------------------------


def _lookup_parent_external_id(
    dept: Department, local_by_id: dict[int, Department],
) -> Optional[str]:
    if dept.parent_id is None:
        return None
    parent = local_by_id.get(dept.parent_id)
    return parent.external_id if parent else None


def _derive_leaf_tenant_id(
    dept: Department, local_by_id: dict[int, Department],
) -> Optional[int]:
    """Walk up ``dept``'s ancestry until we find an ``is_tenant_root`` node.

    Returns the ``mounted_tenant_id`` of that node, or ``None`` when the
    ancestry never hits a mount point (user belongs to the Root tenant).
    """
    cursor: Optional[Department] = dept
    visited: set[int] = set()
    while cursor is not None:
        if cursor.id in visited:
            # Defensive: prevent cycles in pathological data.
            return None
        visited.add(cursor.id)
        if int(getattr(cursor, 'is_tenant_root', 0) or 0) == 1:
            return cursor.mounted_tenant_id
        if cursor.parent_id is None:
            return None
        cursor = local_by_id.get(cursor.parent_id)
    return None


def _derive_leaf_tenant_id_for_parent_ext(
    parent_external_id: Optional[str],
    local_by_ext: dict[str, Department],
    local_by_id: dict[int, Department],
) -> Optional[int]:
    """Derive the leaf tenant the dept will belong to after a move.

    ``parent_external_id`` is the **new** parent's external_id (may be
    ``None`` when the remote moves the dept to the top level under
    Root). The function reuses :func:`_derive_leaf_tenant_id` by
    pretending the new parent is the starting point.
    """
    if parent_external_id is None:
        return None
    new_parent = local_by_ext.get(parent_external_id)
    if new_parent is None:
        # Parent not yet upserted — callers guarantee creates run before
        # moves (F009 topological order), but during diff-time we have
        # only the pre-sync snapshot. Treat as Root leaf.
        return None
    return _derive_leaf_tenant_id(new_parent, local_by_id)
