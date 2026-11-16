"""Locked path maintenance for SSO without changing tenant/mount identities."""

from sqlmodel import select

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department


class SyncedDepartmentTreeRepository:
    @staticmethod
    def _branch(row, allowed_tenants, mounted):
        allowed_tenants = set(allowed_tenants)
        if row.is_tenant_root:
            if mounted or not row.mounted_tenant_id:
                raise PermissionInvalidResourceError(msg="Department subtree has invalid or nested mounts")
            mounted = int(row.mounted_tenant_id)
            allowed_tenants.add(mounted)
        elif row.mounted_tenant_id is not None:
            raise PermissionInvalidResourceError(msg="Department subtree has a dangling mount binding")
        if row.tenant_id not in allowed_tenants:
            raise PermissionInvalidResourceError(msg="Department subtree crosses an unexplained tenant boundary")
        return frozenset(allowed_tenants), mounted

    async def rewrite_paths(self, session, department):
        """Only called for a proposed topology/path change, never a healthy rename.

        Caller locks the source row. Resolve the parent by primary key in this
        UOW; batch/cross-request parent_path snapshots are only hints. Follow
        real parent edges for legality and descendants, not stale path prefixes.
        """
        with bypass_tenant_filter():
            ancestors, seen, identity = [], {int(department.id)}, department.parent_id
            while identity is not None:
                if identity in seen or len(ancestors) >= 100:
                    raise PermissionInvalidResourceError(msg="Department ancestry cycle or limit")
                seen.add(identity)
                row = (
                    await session.exec(
                        select(Department)
                        .where(Department.id == identity)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).first()
                if row is None or row.status != "active" or row.is_deleted:
                    raise PermissionInvalidResourceError(msg="Synced department parent is missing or inactive")
                ancestors.append(row)
                identity = row.parent_id

            allowed = frozenset({ancestors[-1].tenant_id if ancestors else department.tenant_id})
            mounted, parent_path = None, "/"
            for ancestor in reversed(ancestors):
                allowed, mounted = self._branch(ancestor, allowed, mounted)
                parent_path += f"{ancestor.id}/"
                if ancestor.path != parent_path:
                    raise PermissionInvalidResourceError(msg="Synced department parent path is inconsistent")
            allowed, mounted = self._branch(department, allowed, mounted)
            path = f"{parent_path}{department.id}/"
            if department.path == path:
                return
            department.path = path
            session.add(department)
            frontier = {int(department.id): (path, allowed, mounted)}
            visited = {int(department.id)}
            for _ in range(100):
                if not frontier:
                    return
                following, identities = {}, sorted(frontier)
                for start in range(0, len(identities), 500):
                    rows = (
                        await session.exec(
                            select(Department)
                            .where(Department.parent_id.in_(identities[start : start + 500]))
                            .order_by(Department.id)
                            .with_for_update()
                            .execution_options(populate_existing=True)
                        )
                    ).all()
                    for child in rows:
                        child_id = int(child.id)
                        if child_id in visited or len(visited) >= 50000:
                            raise PermissionInvalidResourceError(msg="Department subtree cycle or limit")
                        old_path, allowed_tenants, parent_mount = frontier[int(child.parent_id)]
                        child_tenants, child_mount = self._branch(child, allowed_tenants, parent_mount)
                        visited.add(child_id)
                        child.path = f"{old_path}{child_id}/"
                        session.add(child)
                        following[child_id] = (child.path, child_tenants, child_mount)
                frontier = following
        raise PermissionInvalidResourceError(msg="Department subtree depth exceeds 100")
