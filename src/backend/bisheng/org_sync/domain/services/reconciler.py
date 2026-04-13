"""Reconciler — pure-logic diff engine for org sync.

Compares remote DTOs against local database records and produces
typed operation lists. No IO, no side effects — fully unit-testable.
"""

from dataclasses import dataclass, field
from typing import Optional

from bisheng.database.models.department import Department, UserDepartment
from bisheng.org_sync.domain.schemas.remote_dto import RemoteDepartmentDTO, RemoteMemberDTO


# ---------------------------------------------------------------------------
# Department Operations
# ---------------------------------------------------------------------------

@dataclass
class CreateDept:
    remote: RemoteDepartmentDTO


@dataclass
class UpdateDept:
    local: Department
    new_name: str
    change_source: bool = False  # True if source was 'local', force-overwritten


@dataclass
class MoveDept:
    local: Department
    new_parent_external_id: Optional[str]


@dataclass
class ArchiveDept:
    local: Department


DeptOperation = CreateDept | UpdateDept | MoveDept | ArchiveDept


# ---------------------------------------------------------------------------
# Member Operations
# ---------------------------------------------------------------------------

@dataclass
class CreateMember:
    remote: RemoteMemberDTO


@dataclass
class UpdateMember:
    user_id: int
    new_name: Optional[str] = None
    new_email: Optional[str] = None
    new_phone: Optional[str] = None
    change_source: bool = False


@dataclass
class TransferMember:
    user_id: int
    new_primary_dept_external_id: str
    old_primary_dept_id: Optional[int] = None
    add_secondary_external_ids: list[str] = field(default_factory=list)
    remove_secondary_dept_ids: list[int] = field(default_factory=list)


@dataclass
class DisableMember:
    user_id: int
    dept_ids: list[int] = field(default_factory=list)  # departments to clean up


@dataclass
class ReactivateMember:
    user_id: int
    remote: RemoteMemberDTO


MemberOperation = CreateMember | UpdateMember | TransferMember | DisableMember | ReactivateMember


# ---------------------------------------------------------------------------
# Department Reconciliation
# ---------------------------------------------------------------------------

def reconcile_departments(
    remote_depts: list[RemoteDepartmentDTO],
    local_depts: list[Department],
    source: str,
) -> list[DeptOperation]:
    """Compare remote departments against local and produce operations.

    Args:
        remote_depts: Departments fetched from the provider.
        local_depts: Active local departments (all sources within tenant).
        source: Provider source string (e.g. 'feishu').

    Returns:
        Topologically sorted list of DeptOperations
        (creates: parent-first, archives: child-first).
    """
    # Build lookup maps
    remote_map: dict[str, RemoteDepartmentDTO] = {
        d.external_id: d for d in remote_depts
    }

    # Local departments keyed by external_id (only those with an external_id)
    local_by_ext: dict[str, Department] = {}
    for d in local_depts:
        if d.external_id:
            local_by_ext[d.external_id] = d

    creates: list[CreateDept] = []
    updates: list[UpdateDept] = []
    moves: list[MoveDept] = []
    archives: list[ArchiveDept] = []

    # Pass 1: detect creates, updates, moves from remote data
    for ext_id, remote in remote_map.items():
        local = local_by_ext.get(ext_id)
        if local is None:
            creates.append(CreateDept(remote=remote))
        else:
            # Name change
            if remote.name != local.name:
                change_src = (local.source == 'local')
                updates.append(UpdateDept(
                    local=local,
                    new_name=remote.name,
                    change_source=change_src,
                ))
            elif local.source == 'local':
                # Source mismatch but no name change — still adopt
                updates.append(UpdateDept(
                    local=local,
                    new_name=remote.name,
                    change_source=True,
                ))

            # Parent change
            current_parent_ext = _get_parent_external_id(local, local_depts)
            if remote.parent_external_id != current_parent_ext:
                moves.append(MoveDept(
                    local=local,
                    new_parent_external_id=remote.parent_external_id,
                ))

    # Pass 2: detect archives (local exists with matching source, but not in remote)
    for ext_id, local in local_by_ext.items():
        if local.source == source and ext_id not in remote_map:
            archives.append(ArchiveDept(local=local))

    # Also archive child departments of archived departments
    archived_ids = {a.local.id for a in archives}
    for dept in local_depts:
        if dept.id not in archived_ids and dept.status == 'active':
            if _is_descendant_of_any(dept, archived_ids, local_depts):
                archives.append(ArchiveDept(local=dept))
                archived_ids.add(dept.id)

    # Topological sort: creates parent-first
    creates = _topo_sort_creates(creates, remote_map)

    # Archives: child-first (reverse of parent-first order by path depth)
    archives.sort(key=lambda a: a.local.path.count('/'), reverse=True)

    # Combine in execution order: creates → updates → moves → archives
    result: list[DeptOperation] = []
    result.extend(creates)
    result.extend(updates)
    result.extend(moves)
    result.extend(archives)
    return result


def _get_parent_external_id(
    dept: Department, all_depts: list[Department],
) -> Optional[str]:
    """Get the external_id of a department's parent."""
    if dept.parent_id is None:
        return None
    for d in all_depts:
        if d.id == dept.parent_id:
            return d.external_id
    return None


def _is_descendant_of_any(
    dept: Department, ancestor_ids: set[int], all_depts: list[Department],
) -> bool:
    """Check if dept is a descendant of any department in ancestor_ids."""
    parent_map = {d.id: d.parent_id for d in all_depts}
    current = dept.parent_id
    visited: set[int] = set()
    while current is not None:
        if current in ancestor_ids:
            return True
        if current in visited:
            break  # cycle detected
        visited.add(current)
        current = parent_map.get(current)
    return False


def _topo_sort_creates(
    creates: list[CreateDept],
    remote_map: dict[str, RemoteDepartmentDTO],
) -> list[CreateDept]:
    """Sort create operations so parents come before children.

    Uses Kahn's algorithm. Detects cycles and drops affected nodes.
    """
    if not creates:
        return []

    ext_ids = {c.remote.external_id for c in creates}
    create_map = {c.remote.external_id: c for c in creates}

    # Build in-degree (dependency = parent must be created first)
    in_degree: dict[str, int] = {eid: 0 for eid in ext_ids}
    children: dict[str, list[str]] = {eid: [] for eid in ext_ids}

    for c in creates:
        parent_ext = c.remote.parent_external_id
        if parent_ext and parent_ext in ext_ids:
            in_degree[c.remote.external_id] += 1
            children[parent_ext].append(c.remote.external_id)

    # Kahn's algorithm
    queue = [eid for eid, deg in in_degree.items() if deg == 0]
    sorted_result: list[CreateDept] = []
    while queue:
        eid = queue.pop(0)
        sorted_result.append(create_map[eid])
        for child_eid in children.get(eid, []):
            in_degree[child_eid] -= 1
            if in_degree[child_eid] == 0:
                queue.append(child_eid)

    # If some nodes remain (cycle), skip them
    return sorted_result


# ---------------------------------------------------------------------------
# Member Reconciliation
# ---------------------------------------------------------------------------

def reconcile_members(
    remote_members: list[RemoteMemberDTO],
    local_users: list,  # List[User] — typed loosely to avoid circular import
    local_user_depts: dict[int, list[UserDepartment]],
    ext_to_local_dept: dict[str, int],
    source: str,
) -> list[MemberOperation]:
    """Compare remote members against local users and produce operations.

    Args:
        remote_members: Members fetched from the provider.
        local_users: Local users (filtered by source + tenant).
        local_user_depts: user_id → list of UserDepartment records.
        ext_to_local_dept: external_id → local department.id mapping.
        source: Provider source string.

    Returns:
        List of MemberOperations in execution order.
    """
    remote_map: dict[str, RemoteMemberDTO] = {
        m.external_id: m for m in remote_members
    }

    local_by_ext: dict[str, object] = {}  # external_id → User
    for u in local_users:
        if u.external_id:
            local_by_ext[u.external_id] = u

    creates: list[CreateMember] = []
    updates: list[UpdateMember] = []
    transfers: list[TransferMember] = []
    disables: list[DisableMember] = []
    reactivates: list[ReactivateMember] = []

    # Pass 1: process remote members
    for ext_id, remote in remote_map.items():
        local = local_by_ext.get(ext_id)

        if local is None:
            if remote.status == 'active':
                creates.append(CreateMember(remote=remote))
            continue

        # Reactivate if previously disabled
        if getattr(local, 'delete', 0) == 1 and remote.status == 'active':
            reactivates.append(ReactivateMember(
                user_id=local.user_id,
                remote=remote,
            ))
            continue

        # Disable if remote says disabled
        if remote.status == 'disabled':
            user_depts = local_user_depts.get(local.user_id, [])
            disables.append(DisableMember(
                user_id=local.user_id,
                dept_ids=[ud.department_id for ud in user_depts],
            ))
            continue

        # Check info changes
        change_source = (getattr(local, 'source', '') == 'local')
        needs_update = False
        new_name = None
        new_email = None
        new_phone = None

        if remote.name and remote.name != getattr(local, 'user_name', ''):
            new_name = remote.name
            needs_update = True
        if remote.email is not None and remote.email != getattr(local, 'email', ''):
            new_email = remote.email
            needs_update = True
        if remote.phone is not None and remote.phone != getattr(local, 'phone_number', ''):
            new_phone = remote.phone
            needs_update = True

        if needs_update or change_source:
            updates.append(UpdateMember(
                user_id=local.user_id,
                new_name=new_name,
                new_email=new_email,
                new_phone=new_phone,
                change_source=change_source,
            ))

        # Check department changes
        user_depts = local_user_depts.get(local.user_id, [])
        _check_dept_changes(
            local, remote, user_depts, ext_to_local_dept, transfers,
        )

    # Pass 2: detect disables (local exists with matching source, not in remote)
    for ext_id, local in local_by_ext.items():
        if (
            getattr(local, 'source', '') == source
            and ext_id not in remote_map
            and getattr(local, 'delete', 0) == 0
        ):
            user_depts = local_user_depts.get(local.user_id, [])
            disables.append(DisableMember(
                user_id=local.user_id,
                dept_ids=[ud.department_id for ud in user_depts],
            ))

    result: list[MemberOperation] = []
    result.extend(creates)
    result.extend(updates)
    result.extend(transfers)
    result.extend(disables)
    result.extend(reactivates)
    return result


def _check_dept_changes(
    local_user,
    remote: RemoteMemberDTO,
    user_depts: list[UserDepartment],
    ext_to_local_dept: dict[str, int],
    transfers: list[TransferMember],
) -> None:
    """Detect primary/secondary department changes for an existing user."""
    current_primary_dept_id: Optional[int] = None
    current_secondary_dept_ids: set[int] = set()

    for ud in user_depts:
        if ud.is_primary == 1:
            current_primary_dept_id = ud.department_id
        else:
            current_secondary_dept_ids.add(ud.department_id)

    # Desired state from remote
    new_primary_dept_id = ext_to_local_dept.get(remote.primary_dept_external_id)
    new_secondary_dept_ids: set[int] = set()
    add_secondary_ext: list[str] = []
    for ext_id in remote.secondary_dept_external_ids:
        local_id = ext_to_local_dept.get(ext_id)
        if local_id is not None:
            new_secondary_dept_ids.add(local_id)

    primary_changed = (
        new_primary_dept_id is not None
        and new_primary_dept_id != current_primary_dept_id
    )
    to_add_secondary = new_secondary_dept_ids - current_secondary_dept_ids
    to_remove_secondary = current_secondary_dept_ids - new_secondary_dept_ids

    if primary_changed or to_add_secondary or to_remove_secondary:
        # Build add_secondary_external_ids from to_add_secondary
        dept_id_to_ext = {v: k for k, v in ext_to_local_dept.items()}
        add_ext = [dept_id_to_ext[did] for did in to_add_secondary if did in dept_id_to_ext]

        transfers.append(TransferMember(
            user_id=local_user.user_id,
            new_primary_dept_external_id=remote.primary_dept_external_id,
            old_primary_dept_id=current_primary_dept_id if primary_changed else None,
            add_secondary_external_ids=add_ext,
            remove_secondary_dept_ids=list(to_remove_secondary),
        ))
