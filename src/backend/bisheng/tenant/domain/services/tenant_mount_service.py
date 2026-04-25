"""F011 TenantMountService — Child Tenant lifecycle + resource migration.

Implements spec AC-02, AC-03, AC-04a/b/c/d, AC-07:

  - ``mount_child``: global-super marks a department as a Child Tenant
    mount point. Enforces INV-T1 (2-layer lock), records audit_log.
  - ``unmount_child``: removes a Child mount. v2.5.1 收窄到唯一路径
    （资源迁回 Root + Child 归档）。旧的 archive / manual 策略已删除——
    "冻结子公司不迁移资源" 的需求归到 §5.1.3 的 disable Child 动作。
  - ``migrate_resources_from_root``: AC-04d Root→Child resource sinking
    (INV-T10 — the one path that does NOT go through F018 transfer-owner).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from bisheng.common.errcode.tenant_tree import (
    TenantTreeMigrateConflictError,
    TenantTreeMigratePermissionError,
    TenantTreeMigrateSourceError,
    TenantTreeMountConflictError,
    TenantTreeNestingForbiddenError,
    TenantTreeRootDeptMountError,
)
import time

from sqlalchemy import update as sa_update

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.department import Department, DepartmentDao
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant, TenantDao
from bisheng.tenant.domain.constants import TenantAuditAction

# When a Child is unmounted we keep the row for audit (status=archived) but
# free up ``tenant_code`` so the same code can be remounted. Renaming with a
# deterministic, unique-by-timestamp suffix preserves the link from audit_log
# to the tenant id while side-stepping the UNIQUE index. Format chosen so the
# original code is trivially recoverable (split on ``ARCHIVED_CODE_SEPARATOR``).
ARCHIVED_CODE_SEPARATOR = '#archived#'


def archived_tenant_code(original_code: str) -> str:
    """Build an archive-suffixed tenant_code, e.g. ``keji#archived#1745601234``.

    Idempotent: passing an already-archived code is a no-op so retrying
    the unmount path doesn't double-suffix.
    """
    if ARCHIVED_CODE_SEPARATOR in original_code:
        return original_code
    return f'{original_code}{ARCHIVED_CODE_SEPARATOR}{int(time.time())}'


def display_tenant_code(stored_code: str) -> str:
    """Strip the archive suffix from ``stored_code`` for UI/audit display.

    Mirror of :func:`archived_tenant_code` — pass any tenant_code and get
    back the operator-facing string. Active rows are returned unchanged.
    """
    if not stored_code or ARCHIVED_CODE_SEPARATOR not in stored_code:
        return stored_code
    return stored_code.split(ARCHIVED_CODE_SEPARATOR, 1)[0]


def default_tenant_code(dept_id: int) -> str:
    """Default tenant_code derived from dept_id, e.g. ``t3``.

    Used when callers don't supply an explicit code at mount time. dept_id
    is the department PK so uniqueness is automatic; the leading ``t``
    keeps the value letter-initial to satisfy the schema regex. On unmount
    the row's code is rewritten via :func:`archived_tenant_code` so a
    future remount of the same dept regenerates the same value without
    colliding on the UNIQUE index.
    """
    return f't{dept_id}'


logger = logging.getLogger(__name__)

# Root-owned resources that may be sunk into a Child via AC-04d. The
# resource_type string doubles as the table name — adding a type here
# requires the table to share the ``id`` / ``tenant_id`` shape.
_MIGRATABLE_RESOURCE_TABLES: Set[str] = {
    'knowledge', 'flow', 'assistant', 'channel', 't_gpts_tools',
}

# Business tables migrated out of the Child on policy-A unmount. Subset of
# F001 ``TENANT_TABLES`` — every entry must carry an ``id`` / ``tenant_id``
# column and have a production ORM owned by this codebase today.
_UNMOUNT_MIGRATE_TABLES: List[str] = [
    'flow', 'flowversion',
    'assistant', 'assistantlink',
    'knowledge', 'knowledgefile', 'qaknowledge',
    'channel', 'channel_info_source', 'channel_article_read',
    't_gpts_tools', 't_gpts_tools_type',
    'chatmessage', 'message_session',
    'tag', 'taglink',
    'evaluation', 'dataset',
    'marktask', 'markrecord', 'markappuser',
    'invitecode',
    'linsight_sop', 'linsight_sop_record',
    'linsight_session_version', 'linsight_execute_task',
]


async def _require_super(operator) -> None:
    """Gate: raise 22010 if the operator is not a global super admin.

    Reads the pre-resolved ``is_global_super`` field on LoginUser, which
    ``init_login_user`` populates from ``_check_is_global_super`` (FGA
    tuple + RBAC AdminRole fallback). Kept ``async`` so existing call
    sites that ``await`` it stay unchanged.
    """
    if not getattr(operator, 'is_global_super', False):
        raise TenantTreeMigratePermissionError()


class TenantMountService:
    """Stateless service implementing the Child Tenant lifecycle."""

    # -----------------------------------------------------------------------
    # mount_child
    # -----------------------------------------------------------------------

    @classmethod
    async def mount_child(
        cls,
        dept_id: int,
        tenant_code: Optional[str],
        tenant_name: str,
        operator,
        auto_distribute: bool = True,
    ) -> Tenant:
        """Mark ``dept_id`` as a Child Tenant root (AC-02).

        F017 extension (AC-13): ``auto_distribute`` controls whether Root
        group-shared resources become visible to the new Child immediately.
        - True (default, matches pre-F017 behavior): write
          ``tenant:{new_child}#shared_to → tenant:{root}`` so every resource
          already tagged shared_with Root becomes viewer-reachable for
          members of the new Child.
        - False: skip the shared_to write; super admin must later open share
          per-resource in the UI. Used for "sensitive model" Children where
          auto-fan-out would leak legal-review or similar Root resources.

        The audit_log metadata always records the ``auto_distribute`` flag
        (and, on True, the list of distributed resource ids). F011 callers
        that do not care keep the default and observe the pre-F017 shape.
        """
        await _require_super(operator)
        dept = await DepartmentDao.aget_by_id(dept_id)
        if dept is None:
            raise TenantTreeMountConflictError()
        if dept.parent_id is None:
            # Root department — never a mount point (AC-03).
            raise TenantTreeRootDeptMountError()
        if getattr(dept, 'is_tenant_root', 0) == 1:
            raise TenantTreeMountConflictError()
        ancestor = await DepartmentDao.aget_ancestors_with_mount(dept_id)
        if ancestor is not None:
            # Any ancestor already a mount point → INV-T1 2-layer lock.
            raise TenantTreeNestingForbiddenError()

        # UI hides the tenant_code input; non-UI API callers may still pass
        # an explicit code, in which case the schema regex has already
        # validated it. ``default_tenant_code`` derives a unique fallback
        # from the dept_id when omitted. ``not tenant_code`` covers both
        # None and the empty string a misbehaving client might submit
        # (the pattern check skips empty values for Optional fields).
        if not tenant_code:
            tenant_code = default_tenant_code(dept_id)

        # Single-session transaction: INSERT tenant + UPDATE department happen
        # atomically. If the dept update fails (or anything in between raises)
        # the session exits without commit and SQLAlchemy rolls the INSERT
        # back, so we never leave a tenant_code-occupied orphan.
        # Also writes ``tenant.root_dept_id`` so the bidirectional link
        # (dept.mounted_tenant_id ↔ tenant.root_dept_id) is set in one shot —
        # downstream readers (e.g. TenantUserDialog member-picker scope) rely
        # on this column being populated.
        async with get_async_db_session() as session:
            new_tenant = Tenant(
                tenant_code=tenant_code,
                tenant_name=tenant_name,
                parent_tenant_id=ROOT_TENANT_ID,
                status='active',
                root_dept_id=dept_id,
            )
            session.add(new_tenant)
            await session.flush()  # populate new_tenant.id for the dept update
            await session.execute(
                sa_update(Department)
                .where(Department.id == dept_id)
                .values(is_tenant_root=1, mounted_tenant_id=new_tenant.id)
            )
            await session.commit()
            await session.refresh(new_tenant)

        # F017 hook: fan out the Root ``shared_to`` relation + snapshot the
        # resources that are now reachable. Failures are swallowed to keep
        # mount idempotent — the FGA write is retryable via failed_tuples
        # (F013 compensator) and the DB row is already committed.
        distributed_resources = await cls._on_child_mounted(
            new_tenant.id, auto_distribute=auto_distribute,
        )

        await _safe_audit(
            tenant_id=new_tenant.id,
            operator_id=getattr(operator, 'user_id', 0),
            operator_tenant_id=ROOT_TENANT_ID,
            action=TenantAuditAction.MOUNT.value,
            target_type='tenant',
            target_id=str(new_tenant.id),
            metadata={
                'dept_id': dept_id,
                'dept_path': getattr(dept, 'path', None),
                'tenant_code': tenant_code,
                # F017 AC-13: always record the auto_distribute flag + the
                # snapshot of distributed resource ids (empty when False).
                'auto_distribute': auto_distribute,
                'distributed_resources': distributed_resources,
            },
        )
        return new_tenant

    @classmethod
    async def _on_child_mounted(
        cls, new_child_id: int, auto_distribute: bool,
    ) -> List[Dict[str, Any]]:
        """F017 AC-02 / AC-13: on new Child mount, write the Tenant-level
        ``shared_to`` tuple and return a snapshot of shared Root resources.

        When ``auto_distribute=False`` we skip the FGA write and return an
        empty snapshot — the Child will see no Root-shared resources until
        the super admin opens each one from the UI.
        """
        if not auto_distribute:
            return []
        try:
            from bisheng.tenant.domain.services.resource_share_service import ResourceShareService
            await ResourceShareService.distribute_to_child(
                new_child_id, root_tenant_id=ROOT_TENANT_ID,
            )
        except Exception as e:  # pragma: no cover — compensator handles retry
            logger.warning(
                '[F017] distribute_to_child failed for child %s: %s',
                new_child_id, e,
            )

        # LLM uses resource-level shared_with (different mechanism from the
        # tenant-level shared_to written above — see ResourceShareService
        # docstring). distribute_to_child does NOT cover llm_server, so the
        # new Child would otherwise see no Root LLMs. Fan out per-resource
        # tuples here, only for this Child (already-mounted Children keep
        # their existing tuples untouched).
        #
        # Gated by tenant.share_default_to_children to honour the
        # "Root-only" intent: customers who turned the flag off in the
        # admin UI expect new Children NOT to inherit Root LLMs.
        try:
            from sqlalchemy import text as sa_text

            from bisheng.core.database import get_async_db_session
            from bisheng.core.openfga.manager import get_fga_client
            from bisheng.database.models.tenant import TenantDao

            root_tenant = await TenantDao.aget_by_id(ROOT_TENANT_ID)
            share_default = bool(getattr(
                root_tenant, 'share_default_to_children', True,
            )) if root_tenant else True
            fga = get_fga_client()
            if share_default and fga is not None:
                async with get_async_db_session() as session:
                    res = await session.exec(sa_text(
                        'SELECT id FROM llm_server WHERE tenant_id = :t'
                    ).bindparams(t=ROOT_TENANT_ID))
                    server_ids = [r[0] for r in res.all()]
                if server_ids:
                    writes = [{
                        'user': f'tenant:{new_child_id}',
                        'relation': 'shared_with',
                        'object': f'llm_server:{sid}',
                    } for sid in server_ids]
                    await fga.write_tuples(writes=writes)
        except Exception as e:  # pragma: no cover — compensator handles retry
            logger.warning(
                '[F029] llm_server fanout to child %s failed: %s',
                new_child_id, e,
            )

        try:
            return await cls._list_root_shared_resources()
        except Exception as e:  # pragma: no cover
            logger.warning('[F017] _list_root_shared_resources failed: %s', e)
            return []

    @classmethod
    async def _on_child_unmounted(cls, child_tenant_id: int) -> None:
        """F017 AC-07: tear down every Tenant-level tuple attached to the
        unmounted Child — both directions — so no dangling relation survives.

        Specifically clears:

        - ``tenant:{child}#shared_to → tenant:{root}``  (written by
          ``ResourceShareService.distribute_to_child`` on mount)
        - any ``tenant:{child}#admin`` / ``tenant:{child}#member`` tuples
          where the Child appears as object
        - any tuples where the Child appears as user (e.g. shared_to rows)

        Resource-level ``shared_with → tenant:{child}`` tuples are not
        deleted here: those are tied to individual Root resources, and the
        F017 share-toggle API owns per-resource cleanup. Leaving them in
        FGA is harmless once the Child no longer exists — the viewer chain
        dead-ends at the missing ``tenant:{child}#member`` userset.
        """
        try:
            from bisheng.tenant.domain.services.resource_share_service import ResourceShareService
            await ResourceShareService.revoke_from_child(
                child_tenant_id, root_tenant_id=ROOT_TENANT_ID,
            )
        except Exception as e:  # pragma: no cover — compensator handles retry
            logger.warning(
                '[F017] revoke_from_child failed for child %s: %s',
                child_tenant_id, e,
            )

        try:
            from bisheng.core.openfga.manager import aget_fga_client, get_fga_client

            fga = await aget_fga_client()
            if fga is None:
                fga = get_fga_client()
            if fga is None:
                return

            # Collect tuples where the Child appears as either side of a
            # tenant-level relation, then batch-delete them. We restrict to
            # ``object=tenant:{child}`` / ``user=tenant:{child}`` shapes so
            # we never touch resource-level rows by mistake.
            obj_tuples = await fga.read_tuples(object=f'tenant:{child_tenant_id}')
            user_tuples = await fga.read_tuples(user=f'tenant:{child_tenant_id}')
            seen: set = set()
            deletes: List[Dict[str, str]] = []
            for t in list(obj_tuples) + list(user_tuples):
                key = (t.get('user'), t.get('relation'), t.get('object'))
                if None in key or key in seen:
                    continue
                seen.add(key)
                deletes.append({'user': key[0], 'relation': key[1], 'object': key[2]})
            if deletes:
                await fga.write_tuples(deletes=deletes)
        except Exception as e:  # pragma: no cover
            logger.warning(
                '[F017] tenant-level tuple cleanup failed for child %s: %s',
                child_tenant_id, e,
            )

    # Cap on audit_log.metadata.distributed_resources — bounds both the
    # mount-time query payload and the JSON column size on audit rows.
    # A fleet with >500 shared Root resources gets a truncation marker;
    # the full list is recoverable by joining audit_log.create_time against
    # the shared resource tables if needed.
    _SHARED_RESOURCES_SNAPSHOT_CAP: int = 500

    @classmethod
    async def _list_root_shared_resources(cls) -> List[Dict[str, Any]]:
        """Return a capped snapshot ``[{'type': <5-type>, 'id': <str>}]`` of
        every Root row currently carrying ``is_shared=True``. Used as
        audit_log metadata on Child mount.

        Single UNION ALL query hits MySQL once instead of five sequential
        round-trips; each branch tags its rows with a type literal so we
        don't need N-way zipping in Python.
        """
        from sqlalchemy import text as sa_text

        from bisheng.core.database import get_async_db_session

        sql = sa_text(
            'SELECT * FROM ('
            "    SELECT 'knowledge_space' AS type, CAST(id AS CHAR) AS id FROM knowledge WHERE tenant_id = :t AND is_shared = 1"
            "    UNION ALL SELECT 'workflow',    CAST(id AS CHAR) FROM flow              WHERE tenant_id = :t AND is_shared = 1"
            "    UNION ALL SELECT 'assistant',   CAST(id AS CHAR) FROM assistant         WHERE tenant_id = :t AND is_shared = 1"
            "    UNION ALL SELECT 'channel',     CAST(id AS CHAR) FROM channel           WHERE tenant_id = :t AND is_shared = 1"
            "    UNION ALL SELECT 'tool',        CAST(id AS CHAR) FROM t_gpts_tools_type WHERE tenant_id = :t AND is_shared = 1"
            ') u LIMIT :lim'
        )

        snapshot: List[Dict[str, Any]] = []
        try:
            async with get_async_db_session() as session:
                res = await session.exec(sql.bindparams(
                    t=ROOT_TENANT_ID,
                    lim=cls._SHARED_RESOURCES_SNAPSHOT_CAP + 1,
                ))
                for row in res.all():
                    snapshot.append({'type': row[0], 'id': row[1]})
        except Exception as e:
            logger.warning('[F017] _list_root_shared_resources query failed: %s', e)
            return []

        # Truncation marker so operators know more rows exist beyond the cap.
        if len(snapshot) > cls._SHARED_RESOURCES_SNAPSHOT_CAP:
            snapshot = snapshot[:cls._SHARED_RESOURCES_SNAPSHOT_CAP]
            snapshot.append({'type': '_truncated', 'id': 'see shared resource tables'})
        return snapshot

    # -----------------------------------------------------------------------
    # unmount_child
    # -----------------------------------------------------------------------

    @classmethod
    async def unmount_child(
        cls,
        dept_id: int,
        operator,
    ) -> Dict[str, Any]:
        """Reverse a mount.

        v2.5.1 收窄到唯一路径：资源整体迁回 Root + Child 归档（PRD §5.2.2）。
        旧的 archive / manual 策略已删除——"冻结子公司不迁移资源"的需求归到
        §5.1.3 的 disable Child Tenant 动作，与 unmount 完全分开。

        Stale-flag idempotency: if a department carries ``is_tenant_root=1``
        but ``mounted_tenant_id IS NULL`` (legacy/half-written rows from
        early v2.5 builds), clear the dangling flag and return success
        rather than 22002. Resource migration / tenant archive are skipped —
        there is no Child tenant to migrate from.
        """
        await _require_super(operator)
        dept = await DepartmentDao.aget_by_id(dept_id)
        if dept is None:
            raise TenantTreeMountConflictError()

        child_tenant_id: Optional[int] = getattr(dept, 'mounted_tenant_id', None)
        if not child_tenant_id:
            if getattr(dept, 'is_tenant_root', 0) == 1:
                await DepartmentDao.aunset_mount(dept_id)
                await _safe_audit(
                    tenant_id=ROOT_TENANT_ID,
                    operator_id=getattr(operator, 'user_id', 0),
                    operator_tenant_id=ROOT_TENANT_ID,
                    action=TenantAuditAction.UNMOUNT.value,
                    target_type='department',
                    target_id=str(dept_id),
                    metadata={
                        'dept_id': dept_id,
                        'stale_flag_cleared': True,
                        'migrated_counts': {},
                    },
                )
                return {
                    'tenant_id': None,
                    'migrated_counts': {},
                    'stale_flag_cleared': True,
                }
            raise TenantTreeMountConflictError()

        # 1. 资源迁移：Child 名下所有 tenant_aware 业务表批量改为 Root
        migrated_counts = await cls._migrate_child_resources_to_root(
            child_tenant_id,
        )

        # 2 + 3 in one transaction: archive the Child + free up tenant_code
        # via #archived#<ts> suffix + clear dept mount flag. Pre-fix split
        # these into independent commits — if step 3 succeeded but step 2
        # didn't (or vice versa) the dept and tenant ended up in
        # inconsistent states. Now they commit or roll back together.
        # The code-renaming is what lets ``mount_child`` reuse the original
        # code on a future remount without 1062 — UNIQUE on tenant_code stays
        # intact while the audit row is preserved with id unchanged.
        existing_tenant = await TenantDao.aget_by_id(child_tenant_id)
        new_archived_code = (
            archived_tenant_code(existing_tenant.tenant_code)
            if existing_tenant is not None
            else None
        )
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                if new_archived_code is not None:
                    await session.execute(
                        sa_update(Tenant)
                        .where(Tenant.id == child_tenant_id)
                        .values(
                            status='archived',
                            tenant_code=new_archived_code,
                        )
                    )
                await session.execute(
                    sa_update(Department)
                    .where(Department.id == dept_id)
                    .values(is_tenant_root=0, mounted_tenant_id=None)
                )
                await session.commit()

        # F017 hook: revoke the ``tenant:{child}#shared_to → tenant:{root}``
        # tuple + the Child-scoped tenant-level tuples before we write the
        # audit row. Failures are swallowed — a dangling tuple is observable
        # later via the F013 compensator / housekeeping.
        await cls._on_child_unmounted(child_tenant_id)

        await _safe_audit(
            tenant_id=child_tenant_id,
            operator_id=getattr(operator, 'user_id', 0),
            operator_tenant_id=ROOT_TENANT_ID,
            action=TenantAuditAction.UNMOUNT.value,
            target_type='tenant',
            target_id=str(child_tenant_id),
            metadata={
                'dept_id': dept_id,
                'migrated_counts': migrated_counts,
            },
        )
        return {
            'tenant_id': child_tenant_id,
            'migrated_counts': migrated_counts,
        }

    @classmethod
    async def _migrate_child_resources_to_root(
        cls, child_tenant_id: int,
    ) -> Dict[str, int]:
        """Move every tenant-aware row from Child → Root via TenantDao.

        Thin delegate over ``TenantDao.abulk_update_tenant_id`` so the
        service layer does not own raw SQL — kept only as a semantic
        wrapper (fixed table whitelist, fixed from=child / to=Root).

        Skips tables that are not present in the current deployment's
        schema (deployments that haven't run later alembic migrations may
        be missing ``dataset`` / ``linsight_*`` etc).
        """
        existing = await cls._filter_existing_tables(_UNMOUNT_MIGRATE_TABLES)
        return await TenantDao.abulk_update_tenant_id(
            tables=existing,
            from_tenant_id=child_tenant_id,
            to_tenant_id=ROOT_TENANT_ID,
        )

    @classmethod
    async def _filter_existing_tables(cls, candidate: List[str]) -> List[str]:
        """Return only the tables that currently exist in the live schema.

        Queries ``information_schema.tables`` directly — works on MySQL and
        PostgreSQL without needing a sync inspector. Some 114-style dev
        deployments are missing tables from later alembic migrations
        (``dataset``, ``linsight_*`` etc); skipping silently keeps the
        unmount transaction whole.
        """
        from sqlalchemy import text as sa_text

        from bisheng.core.database import get_async_db_session

        async with get_async_db_session() as session:
            res = await session.execute(
                sa_text(
                    'SELECT table_name FROM information_schema.tables '
                    'WHERE table_schema = DATABASE()'
                )
            )
            present = {row[0] for row in res.fetchall()}
        kept = [t for t in candidate if t in present]
        missing = [t for t in candidate if t not in present]
        if missing:
            logger.warning(
                'unmount migrate skipping missing tables: %s',
                missing,
            )
        return kept

    # -----------------------------------------------------------------------
    # migrate_resources_from_root (AC-04d)
    # -----------------------------------------------------------------------

    @classmethod
    async def migrate_resources_from_root(
        cls,
        child_id: int,
        resource_type: str,
        resource_ids: List[int],
        operator,
        new_owner_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Sink Root-owned resources into a Child Tenant.

        Enforces:
          - super-admin only (22010).
          - each resource.tenant_id == 1 (22011 for the rest, not blocking).
          - resource_type must be in the ``_MIGRATABLE_RESOURCE_TABLES``
            allowlist (unknown types → TenantTreeMountConflictError).

        Returns ``{migrated: N, failed: [{resource_id, reason}, ...]}``.
        """
        await _require_super(operator)
        if resource_type not in _MIGRATABLE_RESOURCE_TABLES:
            # 22006 distinguishes "unknown resource_type" from 22002 "mount conflict".
            raise TenantTreeMigrateConflictError()
        if not resource_ids:
            return {'migrated': 0, 'failed': []}
        table = resource_type

        tenant_ids_by_resource = await cls._fetch_resource_tenant_ids(
            table, resource_ids,
        )

        passable: List[int] = []
        failed: List[Dict[str, Any]] = []
        for rid in resource_ids:
            current = tenant_ids_by_resource.get(rid)
            if current == ROOT_TENANT_ID:
                passable.append(rid)
            else:
                failed.append({
                    'resource_id': rid,
                    'reason': (
                        f'{TenantTreeMigrateSourceError.Code}: '
                        f'expected tenant_id=1 (Root), got {current!r}'
                    ),
                })

        if passable:
            await cls._update_resource_tenant_id(table, passable, child_id)

        await _safe_audit(
            tenant_id=child_id,
            operator_id=getattr(operator, 'user_id', 0),
            operator_tenant_id=ROOT_TENANT_ID,
            action=TenantAuditAction.RESOURCE_MIGRATE.value,
            target_type='resource_batch',
            target_id=resource_type,
            metadata={
                'from_tenant_id': ROOT_TENANT_ID,
                'to_tenant_id': child_id,
                'resource_type': resource_type,
                'count': len(passable),
                'resource_ids': passable,
                'failed_count': len(failed),
                'new_owner_user_id': new_owner_user_id,
            },
        )
        return {'migrated': len(passable), 'failed': failed}

    @classmethod
    async def _fetch_resource_tenant_ids(
        cls, table: str, resource_ids: List[int],
    ) -> Dict[int, int]:
        """Delegate to ``TenantDao.afetch_resource_tenant_ids``."""
        return await TenantDao.afetch_resource_tenant_ids(table, resource_ids)

    @classmethod
    async def _update_resource_tenant_id(
        cls, table: str, resource_ids: List[int], new_tenant_id: int,
    ) -> None:
        """Delegate to ``TenantDao.aupdate_resource_tenant_ids``."""
        await TenantDao.aupdate_resource_tenant_ids(
            table, resource_ids, new_tenant_id,
        )


# ---------------------------------------------------------------------------
# Best-effort audit helper: mount/unmount/migrate must write audit_log per
# AC-07, but the main transaction should not be rolled back if audit insert
# itself fails. spec §5.4 calls this "fail-open with logger.error".
# ---------------------------------------------------------------------------

async def _safe_audit(**kwargs: Any) -> None:
    try:
        await AuditLogDao.ainsert_v2(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            'audit_log insert failed for action=%s: %s',
            kwargs.get('action'), exc,
        )
