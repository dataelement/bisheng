"""Department and UserDepartment ORM models + DAO classes.

Part of F002-department-tree.
"""

import logging
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
    update,
)
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session, get_sync_db_session

logger = logging.getLogger(__name__)


def _normalize_id_scalar_rows(rows) -> List[int]:
    """Normalize SQLAlchemy/SQLModel scalar select rows to plain int ids.

    Depending on driver/version, ``select(Department.id)`` rows may be bare ints,
    ``Row((id,))``, or tuples — callers comparing to ``int(department_id)`` must
    not receive tuple elements inside sets (``5 in {(5,)}`` is False).
    """
    out: List[int] = []
    for row in rows or []:
        if isinstance(row, (list, tuple)):
            out.append(int(row[0]))
        else:
            out.append(int(row))
    return out


class Department(SQLModelSerializable, table=True):
    __tablename__ = 'department'

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    dept_id: str = Field(
        sa_column=Column(
            String(64), nullable=False, unique=True,
            comment='Business key, e.g. BS@a3f7e',
        ),
    )
    name: str = Field(
        sa_column=Column(String(128), nullable=False, comment='Department name'),
    )
    parent_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, nullable=True, index=True,
            comment='Parent department ID, NULL=root',
        ),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(
            Integer, nullable=False,
            server_default=text('1'), index=True,
            comment='Tenant ID',
        ),
    )
    path: str = Field(
        default='',
        sa_column=Column(
            String(512), nullable=False,
            server_default=text("''"), index=True,
            comment='Materialized path /1/2/3/',
        ),
    )
    sort_order: int = Field(
        default=0,
        sa_column=Column(
            Integer, nullable=False,
            server_default=text('0'),
            comment='Sort order among siblings',
        ),
    )
    source: str = Field(
        default='local',
        sa_column=Column(
            String(32), nullable=False,
            server_default=text("'local'"),
            comment='Source: local/feishu/wecom/dingtalk',
        ),
    )
    external_id: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String(128), nullable=True,
            comment='External department ID for sync',
        ),
    )
    status: str = Field(
        default='active',
        sa_column=Column(
            String(16), nullable=False,
            server_default=text("'active'"), index=True,
            comment='Status: active/archived',
        ),
    )
    # v2.5.1 F011: tenant mount point flag + linked tenant FK.
    # Only 1=mount point; mounted_tenant_id resolves to the Child Tenant
    # whose root department is this node. No DB-level FK to avoid circular
    # dependency with tenant table — consistency enforced at service layer.
    is_tenant_root: int = Field(
        default=0,
        sa_column=Column(
            Integer, nullable=False, server_default=text('0'),
            comment='1=Tenant mount point (Child Tenant root dept); v2.5.1 F011',
        ),
    )
    mounted_tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, nullable=True, index=True,
            comment='FK→tenant.id when is_tenant_root=1 (v2.5.1 F011)',
        ),
    )
    # v2.5.1 F014: distinguishes "authoritatively removed by the SSO/HR source
    # of truth" from F009's reversible archive. Only consumed by
    # OrgSyncTsGuard (INV-T12) and F015 reconciliation — existing queries keep
    # using ``status='active'`` for visibility, so this flag never affects
    # tenant-tree visibility.
    is_deleted: int = Field(
        default=0,
        sa_column=Column(
            SmallInteger, nullable=False,
            server_default=text('0'),
            comment='F014: 1=removed by SSO authoritative source',
        ),
    )
    # v2.5.1 F014/F015 INV-T12: per-external_id high-water mark so that
    # Gateway realtime sync and Celery reconciliation converge on
    # "ts max wins; same ts with upsert vs remove → remove wins".
    last_sync_ts: int = Field(
        default=0,
        sa_column=Column(
            BigInteger, nullable=False,
            server_default=text('0'), index=True,
            comment='F014/F015 INV-T12: latest Gateway/Celery sync ts',
        ),
    )
    default_role_ids: Optional[list] = Field(
        default=None,
        sa_column=Column(
            JSON, nullable=True,
            comment='Default role IDs for department members',
        ),
    )
    create_user: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, comment='Creator user ID'),
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False,
            server_default=text('CURRENT_TIMESTAMP'),
        ),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False,
            server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'),
        ),
    )

    __table_args__ = (
        UniqueConstraint('source', 'external_id', name='uk_source_external_id'),
    )


class UserDepartment(SQLModelSerializable, table=True):
    __tablename__ = 'user_department'

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey('user.user_id', ondelete='CASCADE'),
            nullable=False,
            index=True,
            comment='User ID',
        ),
    )
    department_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey('department.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
            comment='Department ID',
        ),
    )
    is_primary: int = Field(
        default=1,
        sa_column=Column(
            SmallInteger, nullable=False,
            server_default=text('1'),
            comment='1=primary department, 0=secondary',
        ),
    )
    source: str = Field(
        default='local',
        sa_column=Column(
            String(32), nullable=False,
            server_default=text("'local'"),
            comment='Source: local/feishu/wecom/dingtalk',
        ),
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False,
            server_default=text('CURRENT_TIMESTAMP'),
        ),
    )

    __table_args__ = (
        UniqueConstraint('user_id', 'department_id', name='uk_user_dept'),
    )


# ---------------------------------------------------------------------------
# DAO: DepartmentDao
# ---------------------------------------------------------------------------

class DepartmentDao:

    @classmethod
    def get_by_id(cls, dept_id: int) -> Optional[Department]:
        with get_sync_db_session() as session:
            return session.exec(
                select(Department).where(Department.id == dept_id)
            ).first()

    @classmethod
    async def aget_by_id(cls, dept_id: int) -> Optional[Department]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(Department.id == dept_id)
            )
            return result.first()

    @classmethod
    def get_by_dept_id(cls, dept_id: str) -> Optional[Department]:
        with get_sync_db_session() as session:
            return session.exec(
                select(Department).where(Department.dept_id == dept_id)
            ).first()

    @classmethod
    async def aget_by_ids(cls, dept_ids: List[int]) -> List[Department]:
        if not dept_ids:
            return []
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(Department.id.in_(dept_ids))
            )
            return result.all()

    @classmethod
    def get_by_ids(cls, dept_ids: List[int]) -> List[Department]:
        if not dept_ids:
            return []
        with get_sync_db_session() as session:
            return session.exec(
                select(Department).where(Department.id.in_(dept_ids))
            ).all()

    @classmethod
    async def aget_by_dept_id(cls, dept_id: str) -> Optional[Department]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(Department.dept_id == dept_id)
            )
            return result.first()

    @classmethod
    def create(cls, dept: Department) -> Department:
        with get_sync_db_session() as session:
            session.add(dept)
            session.flush()
            session.refresh(dept)
            return dept

    @classmethod
    async def acreate(cls, dept: Department) -> Department:
        # flush() assigns the autoincrement id but doesn't persist; without
        # an explicit commit the session's implicit rollback on close would
        # erase the insert. Callers (e.g. OrgSyncService._create_dept) then
        # do a follow-up UPDATE that fails with "0 rows matched" because
        # the row it was trying to update was never actually written.
        async with get_async_db_session() as session:
            session.add(dept)
            await session.commit()
            await session.refresh(dept)
            return dept

    @classmethod
    def update(cls, dept: Department) -> Department:
        with get_sync_db_session() as session:
            session.add(dept)
            session.commit()
            session.refresh(dept)
            return dept

    @classmethod
    async def aupdate(cls, dept: Department) -> Department:
        async with get_async_db_session() as session:
            session.add(dept)
            await session.commit()
            await session.refresh(dept)
            return dept

    @classmethod
    def get_children(cls, parent_id: int) -> List[Department]:
        with get_sync_db_session() as session:
            return session.exec(
                select(Department).where(
                    Department.parent_id == parent_id,
                    Department.status == 'active',
                )
            ).all()

    @classmethod
    async def aget_children(cls, parent_id: int) -> List[Department]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(
                    Department.parent_id == parent_id,
                    Department.status == 'active',
                )
            )
            return result.all()

    @classmethod
    def get_subtree(cls, path_prefix: str) -> List[Department]:
        with get_sync_db_session() as session:
            return session.exec(
                select(Department).where(
                    Department.path.like(f'{path_prefix}%'),
                    Department.status == 'active',
                )
            ).all()

    @classmethod
    async def aget_subtree(cls, path_prefix: str) -> List[Department]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(
                    Department.path.like(f'{path_prefix}%'),
                    Department.status == 'active',
                )
            )
            return result.all()

    @classmethod
    def get_subtree_ids(cls, path_prefix: str) -> List[int]:
        with get_sync_db_session() as session:
            raw = session.exec(
                select(Department.id).where(
                    Department.path.like(f'{path_prefix}%'),
                    Department.status == 'active',
                )
            ).all()
            return _normalize_id_scalar_rows(raw)

    @classmethod
    async def aget_subtree_ids(cls, path_prefix: str) -> List[int]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department.id).where(
                    Department.path.like(f'{path_prefix}%'),
                    Department.status == 'active',
                )
            )
            return _normalize_id_scalar_rows(result.all())

    @classmethod
    def get_all_active(cls) -> List[Department]:
        with get_sync_db_session() as session:
            return session.exec(
                select(Department).where(Department.status == 'active')
            ).all()

    @classmethod
    async def aget_all_active(cls) -> List[Department]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(Department.status == 'active')
            )
            return result.all()

    @classmethod
    async def aget_active_by_tenant(cls, tenant_id: int) -> List[Department]:
        """Get all active departments for a specific tenant."""
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(
                    Department.tenant_id == tenant_id,
                    Department.status == 'active',
                )
            )
            return result.all()

    @classmethod
    async def aget_by_external_id(
        cls, external_id: str, tenant_id: int,
    ) -> Optional[Department]:
        """Get department by external_id within a tenant (for org sync)."""
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(
                    Department.external_id == external_id,
                    Department.tenant_id == tenant_id,
                )
            )
            return result.first()

    @classmethod
    def update_paths_batch(cls, old_prefix: str, new_prefix: str) -> None:
        with get_sync_db_session() as session:
            session.execute(
                update(Department)
                .where(Department.path.like(f'{old_prefix}%'))
                .values(path=func.replace(Department.path, old_prefix, new_prefix))
            )
            session.commit()

    @classmethod
    async def aupdate_paths_batch(cls, old_prefix: str, new_prefix: str) -> None:
        async with get_async_db_session() as session:
            await session.execute(
                update(Department)
                .where(Department.path.like(f'{old_prefix}%'))
                .values(path=func.replace(Department.path, old_prefix, new_prefix))
            )
            await session.commit()

    @classmethod
    def get_root_by_tenant(cls, tenant_id: int) -> Optional[Department]:
        """Get the root department for a specific tenant.

        Uses bypass_tenant_filter() at call site since this queries
        a specific tenant_id explicitly.
        """
        with get_sync_db_session() as session:
            return session.exec(
                select(Department).where(
                    Department.parent_id.is_(None),
                    Department.tenant_id == tenant_id,
                    Department.status == 'active',
                )
            ).first()

    @classmethod
    async def aget_root_by_tenant(cls, tenant_id: int) -> Optional[Department]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(
                    Department.parent_id.is_(None),
                    Department.tenant_id == tenant_id,
                    Department.status == 'active',
                )
            )
            return result.first()

    @classmethod
    def check_name_duplicate(
        cls, parent_id: int, name: str, exclude_id: Optional[int] = None,
    ) -> bool:
        with get_sync_db_session() as session:
            stmt = select(Department).where(
                Department.parent_id == parent_id,
                Department.name == name,
                Department.status == 'active',
            )
            if exclude_id is not None:
                stmt = stmt.where(Department.id != exclude_id)
            return session.exec(stmt).first() is not None

    @classmethod
    async def acheck_name_duplicate(
        cls, parent_id: int, name: str, exclude_id: Optional[int] = None,
    ) -> bool:
        async with get_async_db_session() as session:
            stmt = select(Department).where(
                Department.parent_id == parent_id,
                Department.name == name,
                Department.status == 'active',
            )
            if exclude_id is not None:
                stmt = stmt.where(Department.id != exclude_id)
            result = await session.exec(stmt)
            return result.first() is not None

    # -----------------------------------------------------------------------
    # v2.5.1 F011: tenant mount point DAO (spec §5.3).
    # -----------------------------------------------------------------------

    @classmethod
    async def aget_mount_point(cls, dept_id: int) -> Optional[Department]:
        """Return the department only if it is flagged as a tenant mount point.

        Used by F011 mount conflict checks and F012 JWT leaf derivation.
        """
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(
                    Department.id == dept_id,
                    Department.is_tenant_root == 1,
                )
            )
            return result.first()

    @classmethod
    async def aget_ancestors_with_mount(
        cls, dept_id: int,
    ) -> Optional[Department]:
        """Return the nearest ancestor (or self) that is a tenant mount point.

        Walks the materialized ``path`` column. Used by:
          - F011 mount: reject if any ancestor is already a mount point
                        (enforces INV-T1: 2-layer lock).
          - F012 TenantResolver: derive a user's leaf tenant from their
                                 primary department path.

        Returns None if no ancestor (nor self) carries ``is_tenant_root=1``.
        """
        dept = await cls.aget_by_id(dept_id)
        if dept is None:
            return None
        # path is like "/1/2/3/"; split and keep non-empty numeric ids.
        candidate_ids: List[int] = []
        malformed_parts: List[str] = []
        if dept.path:
            for part in dept.path.split('/'):
                if not part:
                    continue
                if part.isdigit():
                    candidate_ids.append(int(part))
                else:
                    malformed_parts.append(part)
        if malformed_parts:
            # F002 materialized path should always be "/\\d+/\\d+/..."; a
            # non-numeric segment means the path column got corrupted or
            # the format contract was broken by another migration. Surface
            # it via a WARNING so ops can investigate instead of silently
            # returning "no mount ancestor".
            logger.warning(
                'Malformed department path on dept_id=%s: %r (non-numeric: %s)',
                dept_id, dept.path, malformed_parts,
            )
        # Include self: "self is a mount point" also counts.
        if dept_id not in candidate_ids:
            candidate_ids.append(dept_id)
        if not candidate_ids:
            return None
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department)
                .where(
                    Department.id.in_(candidate_ids),
                    Department.is_tenant_root == 1,
                )
                .order_by(func.length(Department.path).desc())
                .limit(1)
            )
            return result.first()

    @classmethod
    async def aset_mount(
        cls, dept_id: int, tenant_id: int,
    ) -> None:
        """Mark ``dept_id`` as a tenant mount point pointing to ``tenant_id``."""
        async with get_async_db_session() as session:
            await session.execute(
                update(Department)
                .where(Department.id == dept_id)
                .values(is_tenant_root=1, mounted_tenant_id=tenant_id)
            )
            await session.commit()

    @classmethod
    async def aunset_mount(cls, dept_id: int) -> None:
        """Clear mount flag + linked tenant on ``dept_id`` (unmount path)."""
        async with get_async_db_session() as session:
            await session.execute(
                update(Department)
                .where(Department.id == dept_id)
                .values(is_tenant_root=0, mounted_tenant_id=None)
            )
            await session.commit()

    @classmethod
    async def aget_user_admin_departments(cls, user_id: int) -> List[Department]:
        """Get departments where user is admin via OpenFGA.

        Uses FGAClient.list_objects() which respects admin inheritance from parent.
        Returns empty list if FGA is unavailable.
        """
        from bisheng.core.openfga.manager import aget_fga_client

        fga = await aget_fga_client()
        if fga is None:
            return []
        try:
            raw = await fga.list_objects(
                user=f'user:{user_id}', relation='admin', type='department',
            )
        except Exception:
            logger.warning(
                'FGA list_objects failed for user %d department admin', user_id,
            )
            return []
        dept_ids = [int(obj.split(':', 1)[1]) for obj in raw if ':' in obj]
        if not dept_ids:
            return []
        return await cls.aget_by_ids(dept_ids)

    # -----------------------------------------------------------------------
    # v2.5.1 F014: SSO realtime sync DAO (spec §5.1/§5.2, INV-T12).
    # -----------------------------------------------------------------------

    @classmethod
    async def aget_by_source_external_id(
        cls, source: str, external_id: str,
    ) -> Optional[Department]:
        """Get department by (source, external_id) — includes ``is_deleted=1``
        rows so that :class:`OrgSyncTsGuard` can observe the prior remove and
        honor INV-T12 (same ts with upsert vs remove → remove wins)."""
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(
                    Department.source == source,
                    Department.external_id == external_id,
                )
            )
            return result.first()

    @classmethod
    async def aupsert_by_external_id(
        cls,
        *,
        source: str,
        external_id: str,
        name: str,
        parent_id: Optional[int],
        path: str,
        sort_order: int,
        last_sync_ts: int,
        tenant_id: int = 1,
    ) -> Department:
        """Idempotent upsert keyed by (source, external_id) for F014
        ``/internal/sso/login-sync`` + ``/departments/sync`` flows.

        **Never touches** ``is_tenant_root`` / ``mounted_tenant_id`` — those
        are bisheng-internal state and SSO sync must stay robust against
        accidental remount (PRD §5.2.5). On resurrect (previously
        ``is_deleted=1``), clears the flag and restores ``status='active'``
        so the department becomes visible again.
        """
        existing = await cls.aget_by_source_external_id(source, external_id)
        async with get_async_db_session() as session:
            if existing is None:
                dept = Department(
                    dept_id=f'{source.upper()}@{external_id}',
                    name=name,
                    parent_id=parent_id,
                    tenant_id=tenant_id,
                    path=path,
                    sort_order=sort_order,
                    source=source,
                    external_id=external_id,
                    status='active',
                    is_deleted=0,
                    last_sync_ts=last_sync_ts,
                )
                session.add(dept)
                await session.commit()
                await session.refresh(dept)
                return dept
            await session.execute(
                update(Department)
                .where(Department.id == existing.id)
                .values(
                    name=name,
                    parent_id=parent_id,
                    path=path,
                    sort_order=sort_order,
                    status='active',
                    is_deleted=0,
                    last_sync_ts=last_sync_ts,
                )
            )
            await session.commit()
        refreshed = await cls.aget_by_id(existing.id)
        return refreshed if refreshed is not None else existing

    @classmethod
    async def aarchive_by_external_id(
        cls, source: str, external_id: str, last_sync_ts: int,
    ) -> Optional[Department]:
        """Soft-delete a department by (source, external_id) for F014 remove
        flow. Sets ``status='archived'``, ``is_deleted=1`` and bumps
        ``last_sync_ts`` atomically. Returns the pre-update row (so callers
        can inspect ``mounted_tenant_id`` for orphan handling) or None if
        the department does not exist.
        """
        existing = await cls.aget_by_source_external_id(source, external_id)
        if existing is None:
            return None
        async with get_async_db_session() as session:
            await session.execute(
                update(Department)
                .where(Department.id == existing.id)
                .values(
                    status='archived',
                    is_deleted=1,
                    last_sync_ts=last_sync_ts,
                )
            )
            await session.commit()
        return existing

    @classmethod
    async def aget_active_by_source_path_name(
        cls, source: str, path: str, name: str,
        exclude_id: Optional[int] = None,
    ) -> List[Department]:
        """F015 relink helper: active depts matching (source, path, name).

        Used by :class:`DepartmentRelinkService` to discover candidates
        for the ``path_plus_name`` strategy after an SSO system
        migration. ``exclude_id`` lets callers drop the old dept from
        the candidate pool so it never matches itself.
        """
        async with get_async_db_session() as session:
            stmt = select(Department).where(
                Department.source == source,
                Department.path == path,
                Department.name == name,
                Department.status == 'active',
            )
            if exclude_id is not None:
                stmt = stmt.where(Department.id != exclude_id)
            result = await session.exec(stmt)
            return result.all()

    @classmethod
    async def aupdate_external_id(
        cls, dept_id: int, new_external_id: str,
    ) -> bool:
        """F015 relink helper: rewrite a dept's external_id in place.

        Returns True when exactly one row was updated. The caller is
        responsible for writing the audit_log entry around the rewrite.
        """
        async with get_async_db_session() as session:
            stmt = (
                update(Department)
                .where(Department.id == dept_id)
                .values(external_id=new_external_id)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0


# ---------------------------------------------------------------------------
# DAO: UserDepartmentDao
# ---------------------------------------------------------------------------

class UserDepartmentDao:

    @classmethod
    def add_member(
        cls, user_id: int, department_id: int,
        is_primary: int = 1, source: str = 'local',
    ) -> UserDepartment:
        with get_sync_db_session() as session:
            ud = UserDepartment(
                user_id=user_id,
                department_id=department_id,
                is_primary=is_primary,
                source=source,
            )
            session.add(ud)
            session.commit()
            session.refresh(ud)
            return ud

    @classmethod
    async def aadd_member(
        cls, user_id: int, department_id: int,
        is_primary: int = 1, source: str = 'local',
    ) -> UserDepartment:
        async with get_async_db_session() as session:
            ud = UserDepartment(
                user_id=user_id,
                department_id=department_id,
                is_primary=is_primary,
                source=source,
            )
            session.add(ud)
            await session.commit()
            await session.refresh(ud)
            return ud

    @classmethod
    def batch_add_members(cls, entries: List[dict]) -> None:
        with get_sync_db_session() as session:
            for entry in entries:
                session.add(UserDepartment(**entry))
            session.commit()

    @classmethod
    async def abatch_add_members(cls, entries: List[dict]) -> None:
        async with get_async_db_session() as session:
            for entry in entries:
                session.add(UserDepartment(**entry))
            await session.commit()

    @classmethod
    def remove_member(cls, user_id: int, department_id: int) -> None:
        with get_sync_db_session() as session:
            ud = session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                    UserDepartment.department_id == department_id,
                )
            ).first()
            if ud:
                session.delete(ud)
                session.commit()

    @classmethod
    async def aremove_member(cls, user_id: int, department_id: int) -> None:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                    UserDepartment.department_id == department_id,
                )
            )
            ud = result.first()
            if ud:
                await session.delete(ud)
                await session.commit()

    @classmethod
    def get_members(
        cls, department_id: int, page: int = 1, limit: int = 20,
        keyword: str = '',
    ) -> Tuple[List, int]:
        """Return (rows, total) for department members with pagination.

        Each row is a UserDepartment joined with user info.
        """
        from bisheng.database.models.user import User

        with get_sync_db_session() as session:
            base = (
                select(
                    UserDepartment.user_id,
                    User.user_name,
                    UserDepartment.department_id,
                    UserDepartment.is_primary,
                    UserDepartment.source,
                    UserDepartment.create_time,
                )
                .join(User, User.user_id == UserDepartment.user_id)
                .where(
                    UserDepartment.department_id == department_id,
                    User.delete == 0,
                )
            )
            if keyword:
                base = base.where(User.user_name.like(f'%{keyword}%'))

            total = session.exec(
                select(func.count()).select_from(base.subquery())
            ).one()

            rows = session.exec(
                base.offset((page - 1) * limit).limit(limit)
            ).all()
            return rows, total

    @classmethod
    async def aget_members(
        cls, department_id: int, page: int = 1, limit: int = 20,
        keyword: str = '',
    ) -> Tuple[List, int]:
        from bisheng.database.models.user import User

        async with get_async_db_session() as session:
            base = (
                select(
                    UserDepartment.user_id,
                    User.user_name,
                    UserDepartment.department_id,
                    UserDepartment.is_primary,
                    UserDepartment.source,
                    UserDepartment.create_time,
                )
                .join(User, User.user_id == UserDepartment.user_id)
                .where(
                    UserDepartment.department_id == department_id,
                    User.delete == 0,
                )
            )
            if keyword:
                base = base.where(User.user_name.like(f'%{keyword}%'))

            total_result = await session.exec(
                select(func.count()).select_from(base.subquery())
            )
            total = total_result.one()

            result = await session.exec(
                base.offset((page - 1) * limit).limit(limit)
            )
            rows = result.all()
            return rows, total

    @classmethod
    def get_member_count(cls, department_id: int) -> int:
        with get_sync_db_session() as session:
            return session.exec(
                select(func.count(UserDepartment.id)).where(
                    UserDepartment.department_id == department_id,
                )
            ).one()

    @classmethod
    async def aget_member_count(cls, department_id: int) -> int:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(func.count(UserDepartment.id)).where(
                    UserDepartment.department_id == department_id,
                )
            )
            return result.one()

    @classmethod
    def get_user_departments(cls, user_id: int) -> List[UserDepartment]:
        with get_sync_db_session() as session:
            return session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                )
            ).all()

    @classmethod
    async def aget_user_departments(cls, user_id: int) -> List[UserDepartment]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                )
            )
            return result.all()

    @classmethod
    def get_user_primary_department(cls, user_id: int) -> Optional[UserDepartment]:
        with get_sync_db_session() as session:
            return session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                    UserDepartment.is_primary == 1,
                )
            ).first()

    @classmethod
    async def aget_user_primary_department(
        cls, user_id: int,
    ) -> Optional[UserDepartment]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                    UserDepartment.is_primary == 1,
                )
            )
            return result.first()

    @classmethod
    async def aget_by_user_ids(cls, user_ids: List[int]) -> List[UserDepartment]:
        """Batch load UserDepartment records for multiple users."""
        if not user_ids:
            return []
        async with get_async_db_session() as session:
            result = await session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id.in_(user_ids),
                )
            )
            return result.all()

    @classmethod
    def get_by_user_ids(cls, user_ids: List[int]) -> List[UserDepartment]:
        """Batch load UserDepartment records for multiple users (sync)."""
        if not user_ids:
            return []
        with get_sync_db_session() as session:
            return session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id.in_(user_ids),
                )
            ).all()

    # -----------------------------------------------------------------------
    # v2.5.1 F014: membership lookups + primary flag management used by
    # ``LoginSyncService`` — kept at the DAO layer so other sync paths
    # (F015 reconcile, admin UI) can reuse them without reaching into
    # service-level helpers.
    # -----------------------------------------------------------------------

    @classmethod
    async def aget_membership(
        cls, user_id: int, department_id: int,
    ) -> Optional[UserDepartment]:
        """Return the exact (user_id, department_id) membership row or None."""
        async with get_async_db_session() as session:
            result = await session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                    UserDepartment.department_id == department_id,
                )
            )
            return result.first()

    @classmethod
    async def aget_memberships_in_depts(
        cls, user_id: int, department_ids: List[int],
    ) -> List[UserDepartment]:
        """Batch lookup — returns every existing (user_id, dept_id) row whose
        dept_id is in the given list. Lets callers resolve the N+1 pattern
        around secondary-department assignment in a single query."""
        if not department_ids:
            return []
        async with get_async_db_session() as session:
            result = await session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                    UserDepartment.department_id.in_(department_ids),
                )
            )
            return result.all()

    @classmethod
    async def aget_user_ids_by_department(
        cls, department_id: int, is_primary: Optional[bool] = None,
    ) -> List[int]:
        """F015: list user ids assigned to a department.

        ``is_primary=True`` returns only primary-department members,
        which is what the reconcile service needs to trigger
        ``UserTenantSyncService.sync_user`` on cross-tenant moves
        (INV-T2). Passing ``None`` returns primary + secondary members
        alike.
        """
        async with get_async_db_session() as session:
            stmt = select(UserDepartment).where(
                UserDepartment.department_id == department_id,
            )
            if is_primary is True:
                stmt = stmt.where(UserDepartment.is_primary == 1)
            elif is_primary is False:
                stmt = stmt.where(UserDepartment.is_primary == 0)
            result = await session.exec(stmt)
            return [row.user_id for row in result.all()]

    @classmethod
    async def aset_primary_flag(
        cls, user_id: int, department_id: int, is_primary: int,
    ) -> None:
        """Flip the ``is_primary`` flag on an existing membership row."""
        async with get_async_db_session() as session:
            await session.execute(
                update(UserDepartment)
                .where(
                    UserDepartment.user_id == user_id,
                    UserDepartment.department_id == department_id,
                )
                .values(is_primary=is_primary)
            )
            await session.commit()

    @classmethod
    def check_member_exists(cls, user_id: int, department_id: int) -> bool:
        with get_sync_db_session() as session:
            return session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                    UserDepartment.department_id == department_id,
                )
            ).first() is not None

    @classmethod
    async def acheck_member_exists(
        cls, user_id: int, department_id: int,
    ) -> bool:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                    UserDepartment.department_id == department_id,
                )
            )
            return result.first() is not None


# Register ``department_admin_grant`` on SQLModel metadata for migrations / create_all.
import bisheng.database.models.department_admin_grant  # noqa: F401, E402
