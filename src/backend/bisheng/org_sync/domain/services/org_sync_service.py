"""OrgSyncService — sync orchestrator.

Implements the 16-step flow described in spec §7:
  load config → acquire lock → create log → authenticate → fetch →
  reconcile → apply → update log → release lock.

Bypasses DepartmentService permission checks (AD-11) by directly
operating DAO + DepartmentChangeHandler for system-level sync.
"""

import secrets
import time
import uuid
from datetime import datetime
from typing import Optional

from loguru import logger

from bisheng.common.errcode.org_sync import (
    OrgSyncAlreadyRunningError,
    OrgSyncConfigDisabledError,
    OrgSyncConfigNotFoundError,
)
from bisheng.database.constants import (
    DefaultRole,
    USER_DISABLE_SOURCE_ORG_SYNC,
)
from bisheng.database.models.group import DefaultGroup, GroupDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.database.models.department import (
    Department,
    DepartmentDao,
    UserDepartment,
    UserDepartmentDao,
)
from bisheng.database.models.tenant import UserTenant, UserTenantDao
from bisheng.department.domain.services.department_archive_cleanup_service import (
    DepartmentArchiveCleanupService,
)
from bisheng.department.domain.services.department_change_handler import DepartmentChangeHandler
from bisheng.department.domain.services.department_sync_rbac_service import (
    DepartmentSyncRBACService,
)
from bisheng.permission.domain.services.legacy_rbac_sync_service import LegacyRBACSyncService
from bisheng.tenant.domain.constants import DeletionSource
from bisheng.tenant.domain.services.department_deletion_handler import (
    DepartmentDeletionHandler,
)
from bisheng.user_group.domain.services.group_change_handler import GroupChangeHandler
from bisheng.org_sync.domain.models.org_sync import (
    OrgSyncConfig,
    OrgSyncConfigDao,
    OrgSyncLog,
    OrgSyncLogDao,
    decrypt_auth_config,
)
from bisheng.org_sync.domain.providers.base import get_provider
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
from bisheng.user.domain.models.user import User, UserDao

REDIS_LOCK_KEY_PREFIX = 'bisheng:lock:org_sync:'
REDIS_LOCK_TTL = 1800  # 30 minutes


class OrgSyncService:

    @classmethod
    async def execute_sync(
        cls,
        config_id: int,
        trigger_type: str,
        trigger_user: Optional[int] = None,
    ) -> int:
        """Main orchestration flow. Returns log_id."""
        # Step 1: Load config
        config = await OrgSyncConfigDao.aget_by_id(config_id)
        if not config:
            raise OrgSyncConfigNotFoundError()

        if config.status == 'disabled':
            raise OrgSyncConfigDisabledError()

        # Step 2: Acquire mutex (DB CAS + Redis lock)
        acquired = await OrgSyncConfigDao.aset_sync_status(
            config_id, 'idle', 'running',
        )
        if not acquired:
            raise OrgSyncAlreadyRunningError()

        redis_lock = await cls._acquire_redis_lock(config_id)

        log: Optional[OrgSyncLog] = None
        errors: list[dict] = []
        stats = {
            'dept_created': 0, 'dept_updated': 0, 'dept_archived': 0,
            'member_created': 0, 'member_updated': 0, 'member_disabled': 0,
            'member_reactivated': 0,
        }

        try:
            # Step 3: Create log entry
            log = OrgSyncLog(
                tenant_id=config.tenant_id,
                config_id=config_id,
                trigger_type=trigger_type,
                trigger_user=trigger_user,
                status='running',
                start_time=datetime.now(),
            )
            log = await OrgSyncLogDao.acreate(log)

            # Step 4: Decrypt auth_config and instantiate provider.
            # The underscore-prefixed _config_id is a provider-internal hint
            # (e.g. WeCom uses it to partition its Redis token cache per
            # config). Never encrypted, never persisted — it's reattached here
            # on each call and stripped again on update (see sync_config.py).
            auth_config = decrypt_auth_config(config.auth_config)
            auth_config['_config_id'] = config.id
            provider = get_provider(config.provider, auth_config)

            # Step 5: Authenticate
            await provider.authenticate()

            # Step 6: Fetch remote departments
            scope = config.sync_scope
            root_dept_ids = scope.get('root_dept_ids') if scope else None
            remote_depts = await provider.fetch_departments(root_dept_ids)

            # Step 7: Load local departments
            local_depts = await DepartmentDao.aget_active_by_tenant(config.tenant_id)

            # Step 8: Reconcile departments
            dept_ops = reconcile_departments(
                remote_depts, local_depts, config.provider,
            )

            # Step 9: Apply department operations
            ext_to_local = await cls._apply_dept_ops(
                dept_ops, config, stats, errors, local_depts,
            )

            # Step 10: Fetch remote members
            dept_ext_ids = [d.external_id for d in remote_depts]
            remote_members = await provider.fetch_members(dept_ext_ids)

            # Step 11: Load local users + batch load user departments
            local_users = await UserDao.aget_by_source_or_local_external_ids(
                config.provider,
                config.tenant_id,
                [m.external_id for m in remote_members],
            )
            user_ids = [u.user_id for u in local_users]
            all_user_depts = await UserDepartmentDao.aget_by_user_ids(user_ids)
            local_user_depts: dict[int, list[UserDepartment]] = {}
            for ud in all_user_depts:
                local_user_depts.setdefault(ud.user_id, []).append(ud)

            # Step 12: Reconcile members
            member_ops = reconcile_members(
                remote_members, local_users, local_user_depts,
                ext_to_local, config.provider,
            )

            # Step 13: Apply member operations
            await cls._apply_member_ops(
                member_ops, config, stats, errors, ext_to_local,
            )

        except Exception as e:
            logger.exception(f'Sync failed for config {config_id}: {e}')
            errors.append({
                'entity_type': 'system',
                'external_id': '',
                'error_msg': str(e),
            })

        finally:
            # Step 14: Update log (if created)
            if log:
                final_status = 'success'
                if errors:
                    final_status = 'partial' if any(
                        stats[k] > 0 for k in stats
                    ) else 'failed'

                log.status = final_status
                log.dept_created = stats['dept_created']
                log.dept_updated = stats['dept_updated']
                log.dept_archived = stats['dept_archived']
                log.member_created = stats['member_created']
                log.member_updated = stats['member_updated']
                log.member_disabled = stats['member_disabled']
                log.member_reactivated = stats['member_reactivated']
                log.error_details = errors or None
                log.end_time = datetime.now()
                try:
                    await OrgSyncLogDao.aupdate(log)
                except Exception:
                    logger.exception('Failed to update sync log')

            # Step 15: Update config
            try:
                config.last_sync_at = datetime.now()
                config.last_sync_result = log.status if log else 'failed'
                await OrgSyncConfigDao.aupdate(config)
            except Exception:
                logger.exception('Failed to update sync config')

            # Step 16: Release lock (always, even on failure)
            await OrgSyncConfigDao.aset_sync_status(config_id, 'running', 'idle')
            await cls._release_redis_lock(config_id, redis_lock)

        return log.id if log else 0

    # ------------------------------------------------------------------
    # Department operations
    # ------------------------------------------------------------------

    @classmethod
    async def _apply_dept_ops(
        cls,
        ops: list,
        config: OrgSyncConfig,
        stats: dict,
        errors: list[dict],
        local_depts: list,
    ) -> dict[str, int]:
        """Execute department operations. Returns ext_id → local dept.id map."""
        ext_to_local: dict[str, int] = {}
        for d in local_depts:
            if d.external_id:
                ext_to_local[d.external_id] = d.id

        for op in ops:
            try:
                if isinstance(op, CreateDept):
                    await cls._create_dept(op, config, ext_to_local)
                    stats['dept_created'] += 1
                elif isinstance(op, UpdateDept):
                    await cls._update_dept(op, config)
                    stats['dept_updated'] += 1
                elif isinstance(op, MoveDept):
                    await cls._move_dept(op, ext_to_local)
                    stats['dept_updated'] += 1
                elif isinstance(op, ArchiveDept):
                    await cls._archive_dept(op)
                    stats['dept_archived'] += 1
            except Exception as e:
                ext_id = ''
                if isinstance(op, CreateDept):
                    ext_id = op.remote.external_id
                elif hasattr(op, 'local'):
                    ext_id = op.local.external_id or ''
                logger.warning(f'Dept op failed ({type(op).__name__}): {e}')
                errors.append({
                    'entity_type': 'department',
                    'external_id': ext_id,
                    'error_msg': str(e),
                })

        return ext_to_local

    @classmethod
    async def _create_dept(
        cls, op: CreateDept, config: OrgSyncConfig,
        ext_to_local: dict[str, int],
    ) -> None:
        # A "remote root" — a department whose parent is outside the sync
        # scope — shouldn't be created as a child of the local tenant root;
        # it IS the tenant root's counterpart upstream. Adopt the local
        # tenant root (stamp its external_id + source + name) so the tree
        # merges cleanly instead of nesting the whole org one level deeper.
        if op.remote.parent_external_id is None:
            local_root = await DepartmentDao.aget_root_by_tenant(config.tenant_id)
            if local_root and not local_root.external_id:
                local_root.external_id = op.remote.external_id
                local_root.source = config.provider
                local_root.name = op.remote.name
                await DepartmentDao.aupdate(local_root)
                ext_to_local[op.remote.external_id] = local_root.id
                return
            # Fallthrough: local root already adopted by someone else, or no
            # local root (shouldn't happen). Create as a sibling-of-root child
            # so we don't silently lose the remote row.

        # Resolve parent
        parent_id: Optional[int] = None
        if op.remote.parent_external_id:
            parent_id = ext_to_local.get(op.remote.parent_external_id)
            if parent_id is None:
                parent = await DepartmentDao.aget_by_external_id(
                    op.remote.parent_external_id, config.tenant_id,
                )
                if parent:
                    parent_id = parent.id
        else:
            # Fallback (see above) — attach under tenant root.
            root = await DepartmentDao.aget_root_by_tenant(config.tenant_id)
            if root:
                parent_id = root.id

        # Build path
        path = '/'
        if parent_id:
            parent_dept = await DepartmentDao.aget_by_id(parent_id)
            if parent_dept:
                path = parent_dept.path

        # Generate business key
        dept_id = f'BS@{uuid.uuid4().hex[:5]}'

        dept = Department(
            dept_id=dept_id,
            name=op.remote.name,
            parent_id=parent_id,
            tenant_id=config.tenant_id,
            path=path,  # temporary, will be updated
            sort_order=op.remote.sort_order,
            source=config.provider,
            external_id=op.remote.external_id,
        )
        dept = await DepartmentDao.acreate(dept)

        # Fix path with actual ID
        dept.path = f'{path}{dept.id}/'
        await DepartmentDao.aupdate(dept)

        # Update mapping
        ext_to_local[op.remote.external_id] = dept.id

        # OpenFGA tuple via ChangeHandler
        if parent_id:
            tuple_ops = DepartmentChangeHandler.on_created(dept.id, parent_id)
            await DepartmentChangeHandler.execute_async(tuple_ops)

    @classmethod
    async def _update_dept(cls, op: UpdateDept, config: OrgSyncConfig) -> None:
        op.local.name = op.new_name
        if op.change_source:
            op.local.source = config.provider
        await DepartmentDao.aupdate(op.local)

    @classmethod
    async def _move_dept(
        cls, op: MoveDept, ext_to_local: dict[str, int],
    ) -> None:
        old_parent_id = op.local.parent_id
        new_parent_id = ext_to_local.get(op.new_parent_external_id) if op.new_parent_external_id else None

        if new_parent_id is None or new_parent_id == old_parent_id:
            return

        # Update parent_id
        op.local.parent_id = new_parent_id

        # Rebuild path
        new_parent = await DepartmentDao.aget_by_id(new_parent_id)
        old_path = op.local.path
        new_prefix = f'{new_parent.path}{op.local.id}/' if new_parent else f'/{op.local.id}/'
        op.local.path = new_prefix
        await DepartmentDao.aupdate(op.local)

        # Update all descendant paths
        if old_path and old_path != new_prefix:
            await DepartmentDao.aupdate_paths_batch(old_path, new_prefix)

        # OpenFGA tuples
        if old_parent_id:
            tuple_ops = DepartmentChangeHandler.on_moved(
                op.local.id, old_parent_id, new_parent_id,
            )
            await DepartmentChangeHandler.execute_async(tuple_ops)

    @classmethod
    async def _archive_dept(cls, op: ArchiveDept) -> None:
        op.local.status = 'archived'
        op.local.is_deleted = 1
        op.local.last_sync_ts = int(time.time())
        await DepartmentDao.aupdate(op.local)

        # OpenFGA cleanup
        if op.local.parent_id:
            tuple_ops = DepartmentChangeHandler.on_archived(
                op.local.id, op.local.parent_id,
            )
            await DepartmentChangeHandler.execute_async(tuple_ops)
        try:
            await DepartmentDeletionHandler.on_deleted(
                op.local.id, DeletionSource.CELERY_RECONCILE,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f'DepartmentDeletionHandler.on_deleted failed for '
                f'dept {op.local.id}: {exc}',
            )
        if op.local.id is not None:
            await DepartmentArchiveCleanupService.arun_for_archived_department(
                int(op.local.id), reason='org_sync_archive',
            )

    # ------------------------------------------------------------------
    # Member operations
    # ------------------------------------------------------------------

    @classmethod
    async def _apply_member_ops(
        cls,
        ops: list,
        config: OrgSyncConfig,
        stats: dict,
        errors: list[dict],
        ext_to_local_dept: dict[str, int],
    ) -> None:
        for op in ops:
            try:
                if isinstance(op, CreateMember):
                    await cls._create_member(op, config, ext_to_local_dept)
                    stats['member_created'] += 1
                elif isinstance(op, UpdateMember):
                    await cls._update_member(op, config)
                    stats['member_updated'] += 1
                elif isinstance(op, TransferMember):
                    await cls._transfer_member(op, config, ext_to_local_dept)
                    stats['member_updated'] += 1
                elif isinstance(op, DisableMember):
                    await cls._disable_member(op)
                    stats['member_disabled'] += 1
                elif isinstance(op, ReactivateMember):
                    await cls._reactivate_member(op, config, ext_to_local_dept)
                    stats['member_reactivated'] += 1
            except Exception as e:
                ext_id = ''
                if isinstance(op, CreateMember):
                    ext_id = op.remote.external_id
                elif isinstance(op, ReactivateMember):
                    ext_id = op.remote.external_id
                logger.warning(f'Member op failed ({type(op).__name__}): {e}')
                errors.append({
                    'entity_type': 'member',
                    'external_id': ext_id,
                    'error_msg': str(e),
                })

    @classmethod
    async def _create_member(
        cls, op: CreateMember, config: OrgSyncConfig,
        ext_to_local_dept: dict[str, int],
    ) -> None:
        # Create User with random password (AD-07)
        password_hash = secrets.token_hex(32)
        user = User(
            user_name=op.remote.name,
            email=op.remote.email,
            phone_number=op.remote.phone,
            source=config.provider,
            external_id=op.remote.external_id,
            password=password_hash,
        )
        user = await UserDao.add_user_and_default_role(user)
        member_group_ids = await cls._ensure_default_user_group_membership(
            user.user_id,
        )
        await LegacyRBACSyncService.sync_user_auth_created(
            user.user_id,
            [DefaultRole],
            member_group_ids=member_group_ids,
        )

        # Create UserTenant
        ut = UserTenant(user_id=user.user_id, tenant_id=config.tenant_id)
        await UserTenantDao.acreate(ut)

        # Create UserDepartment entries
        all_dept_ids: list[int] = []
        primary_dept_id = ext_to_local_dept.get(op.remote.primary_dept_external_id)
        if primary_dept_id:
            await UserDepartmentDao.aadd_member(
                user.user_id, primary_dept_id, is_primary=1, source=config.provider,
            )
            all_dept_ids.append(primary_dept_id)

        for ext_id in op.remote.secondary_dept_external_ids:
            dept_id = ext_to_local_dept.get(ext_id)
            if dept_id and dept_id != primary_dept_id:
                await UserDepartmentDao.aadd_member(
                    user.user_id, dept_id, is_primary=0, source=config.provider,
                )
                all_dept_ids.append(dept_id)

        # OpenFGA member tuples
        for dept_id in all_dept_ids:
            tuple_ops = DepartmentChangeHandler.on_members_added(
                dept_id, [user.user_id],
            )
            await DepartmentChangeHandler.execute_async(tuple_ops)
        for dept_id in all_dept_ids:
            await DepartmentSyncRBACService.aapply_department_default_roles_for_user(
                int(user.user_id), int(dept_id),
            )

    @classmethod
    async def _ensure_default_user_group_membership(cls, user_id: int) -> list[int]:
        """Mirror normal user creation: add synced users to the default group.

        Some deployments still use the legacy default user group as the
        management surface for automatically-created accounts. Treat it as
        best-effort because fresh v2.5 installs may not have group id 2.
        """
        try:
            group = await GroupDao.aget_by_id(DefaultGroup)
            if group is None:
                return []
            existing = await UserGroupDao.acheck_members_exist(
                DefaultGroup, [user_id],
            )
            existing_ids = {
                int(row[0]) if isinstance(row, (tuple, list)) else int(row)
                for row in existing
            }
            if user_id not in existing_ids:
                await UserGroupDao.aadd_members_batch(DefaultGroup, [user_id])
                tuple_ops = GroupChangeHandler.on_members_added(
                    DefaultGroup, [user_id],
                )
                await GroupChangeHandler.execute_async(tuple_ops)
            return [DefaultGroup]
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f'Failed to attach synced user {user_id} '
                f'to default group: {exc}',
            )
            return []

    @classmethod
    async def _update_member(
        cls, op: UpdateMember, config: OrgSyncConfig,
    ) -> None:
        user = await UserDao.aget_user(op.user_id)
        if not user:
            return
        if op.new_name:
            user.user_name = op.new_name
        if op.new_email is not None:
            user.email = op.new_email
        if op.new_phone is not None:
            user.phone_number = op.new_phone
        if op.change_source:
            user.source = config.provider
        await UserDao.aupdate_user(user)

    @classmethod
    async def _transfer_member(
        cls, op: TransferMember, config: OrgSyncConfig,
        ext_to_local_dept: dict[str, int],
    ) -> None:
        new_primary_id = ext_to_local_dept.get(
            op.new_primary_dept_external_id,
        ) if op.new_primary_dept_external_id else None

        for dept_id in op.remove_secondary_dept_ids:
            if op.old_primary_dept_id and int(dept_id) == int(op.old_primary_dept_id):
                continue
            await DepartmentSyncRBACService.arevoke_user_roles_in_department(
                op.user_id, int(dept_id),
            )

        if op.touch_primary and new_primary_id and op.old_primary_dept_id is not None:
            await DepartmentSyncRBACService.arevoke_user_roles_in_department(
                op.user_id, int(op.old_primary_dept_id),
            )

        if op.touch_primary and new_primary_id and op.old_primary_dept_id is not None:
            await UserDepartmentDao.aremove_member(op.user_id, op.old_primary_dept_id)
            tuple_ops = DepartmentChangeHandler.on_member_removed(
                op.old_primary_dept_id, op.user_id,
            )
            await DepartmentChangeHandler.execute_async(tuple_ops)

            await UserDepartmentDao.aadd_member(
                op.user_id, new_primary_id, is_primary=1, source=config.provider,
            )
            tuple_ops = DepartmentChangeHandler.on_members_added(
                new_primary_id, [op.user_id],
            )
            await DepartmentChangeHandler.execute_async(tuple_ops)
            await DepartmentSyncRBACService.aapply_department_default_roles_for_user(
                op.user_id, int(new_primary_id),
            )
        elif op.touch_primary and new_primary_id and op.old_primary_dept_id is None:
            existing = await UserDepartmentDao.aget_membership(
                op.user_id, int(new_primary_id),
            )
            if existing is not None:
                await UserDepartmentDao.aset_primary_flag(
                    op.user_id, int(new_primary_id), is_primary=1,
                )
            else:
                await UserDepartmentDao.aadd_member(
                    op.user_id, new_primary_id, is_primary=1, source=config.provider,
                )
            tuple_ops = DepartmentChangeHandler.on_members_added(
                new_primary_id, [op.user_id],
            )
            await DepartmentChangeHandler.execute_async(tuple_ops)
            await DepartmentSyncRBACService.aapply_department_default_roles_for_user(
                op.user_id, int(new_primary_id),
            )

        for ext_id in op.add_secondary_external_ids:
            dept_id = ext_to_local_dept.get(ext_id)
            if not dept_id:
                continue
            await UserDepartmentDao.aadd_member(
                op.user_id, dept_id, is_primary=0, source=config.provider,
            )
            tuple_ops = DepartmentChangeHandler.on_members_added(
                dept_id, [op.user_id],
            )
            await DepartmentChangeHandler.execute_async(tuple_ops)
            await DepartmentSyncRBACService.aapply_department_default_roles_for_user(
                op.user_id, int(dept_id),
            )

        for dept_id in op.remove_secondary_dept_ids:
            await UserDepartmentDao.aremove_member(op.user_id, dept_id)
            tuple_ops = DepartmentChangeHandler.on_member_removed(
                int(dept_id), op.user_id,
            )
            await DepartmentChangeHandler.execute_async(tuple_ops)

    @classmethod
    async def _disable_member(cls, op: DisableMember) -> None:
        user = await UserDao.aget_user(op.user_id)
        if not user:
            return
        user.delete = 1
        user.disable_source = USER_DISABLE_SOURCE_ORG_SYNC
        await UserDao.aupdate_user(user)
        from bisheng.user.domain.services.user import UserService
        await UserService.ainvalidate_jwt_after_account_disabled(op.user_id)

        # Clean up all department memberships + OpenFGA tuples
        for dept_id in op.dept_ids:
            await UserDepartmentDao.aremove_member(op.user_id, dept_id)
            tuple_ops = DepartmentChangeHandler.on_member_removed(dept_id, op.user_id)
            await DepartmentChangeHandler.execute_async(tuple_ops)

    @classmethod
    async def _reactivate_member(
        cls, op: ReactivateMember, config: OrgSyncConfig,
        ext_to_local_dept: dict[str, int],
    ) -> None:
        user = await UserDao.aget_user(op.user_id)
        if not user:
            return
        user.delete = 0
        user.source = config.provider
        user.disable_source = None
        await UserDao.aupdate_user(user)

        # Rebuild department memberships
        all_dept_ids: list[int] = []
        primary_dept_id = ext_to_local_dept.get(op.remote.primary_dept_external_id)
        if primary_dept_id:
            await UserDepartmentDao.aadd_member(
                op.user_id, primary_dept_id, is_primary=1, source=config.provider,
            )
            all_dept_ids.append(primary_dept_id)

        for ext_id in op.remote.secondary_dept_external_ids:
            dept_id = ext_to_local_dept.get(ext_id)
            if dept_id and dept_id != primary_dept_id:
                await UserDepartmentDao.aadd_member(
                    op.user_id, dept_id, is_primary=0, source=config.provider,
                )
                all_dept_ids.append(dept_id)

        for dept_id in all_dept_ids:
            tuple_ops = DepartmentChangeHandler.on_members_added(
                dept_id, [op.user_id],
            )
            await DepartmentChangeHandler.execute_async(tuple_ops)
        for dept_id in all_dept_ids:
            await DepartmentSyncRBACService.aapply_department_default_roles_for_user(
                op.user_id, int(dept_id),
            )

    # ------------------------------------------------------------------
    # Redis lock helpers
    # ------------------------------------------------------------------

    @classmethod
    async def _acquire_redis_lock(cls, config_id: int) -> Optional[str]:
        """Acquire Redis distributed lock. Returns lock token or None."""
        try:
            from bisheng.core.cache.redis_manager import get_redis_client
            redis = await get_redis_client()
            lock_key = f'{REDIS_LOCK_KEY_PREFIX}{config_id}'
            token = secrets.token_hex(16)
            acquired = await redis.async_connection.set(
                lock_key, token, nx=True, ex=REDIS_LOCK_TTL,
            )
            return token if acquired else None
        except Exception as e:
            logger.warning(f'Redis lock acquisition failed (non-fatal): {e}')
            return None

    @classmethod
    async def _release_redis_lock(
        cls, config_id: int, token: Optional[str],
    ) -> None:
        """Release Redis lock if we hold it."""
        if not token:
            return
        try:
            from bisheng.core.cache.redis_manager import get_redis_client
            redis = await get_redis_client()
            lock_key = f'{REDIS_LOCK_KEY_PREFIX}{config_id}'
            # Only release if we still hold the lock
            current = await redis.async_connection.get(lock_key)
            if current and current.decode() == token:
                await redis.async_connection.delete(lock_key)
        except Exception as e:
            logger.warning(f'Redis lock release failed (non-fatal): {e}')
