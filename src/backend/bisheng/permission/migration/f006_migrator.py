"""F006: RBAC → ReBAC Permission Data Migration.

Migrates legacy permission data from MySQL tables (role_access, user_role,
user_group, space_channel_member, resource ownership) to OpenFGA tuples.

Usage:
    # Default mode: execute full migration
    python -m bisheng.permission.migration.migrate_rbac_to_rebac

    # Preview mode: statistics only, no writes
    python -m bisheng.permission.migration.migrate_rbac_to_rebac --dry-run

    # Verify mode: compare old vs new permission results
    python -m bisheng.permission.migration.migrate_rbac_to_rebac --verify

    # Resume from step N
    python -m bisheng.permission.migration.migrate_rbac_to_rebac --step 3

    # Run one step only
    python -m bisheng.permission.migration.migrate_rbac_to_rebac --only-step 3
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from typing import Awaitable, Callable, Optional

from loguru import logger
from sqlalchemy import text as sa_text

from bisheng.core.openfga.exceptions import FGAConnectionError, FGAWriteError
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
from bisheng.permission.migration.batch_utils import (
    ProgressTracker,
    TupleDeduplicator,
    iter_keyset_batches,
)
from bisheng.permission.migration.f006_constants import (
    ACCESS_TYPE_MAPPING,
    FLOW_TYPE_MAPPING,
    GROUP_RESOURCE_TYPE_MAPPING,
    KNOWLEDGE_LEGACY_TYPES,
    RELATION_PRIORITY,
    SCM_ROLE_MAPPING,
    SCM_TYPE_MAPPING,
    _BATCH_SIZE,
    _CHECKPOINT_FILENAME,
)
from bisheng.permission.migration.f006_schemas import MigrationStats, VerifyReport

StepFn = Callable[[], Awaitable[int]]


# ── Migrator ──────────────────────────────────────────────────────

class RBACToReBACMigrator:
    """One-shot migration from RBAC tables to OpenFGA tuples.

    Supports dry-run (statistics only), verify (compare old/new), and
    checkpoint-based resume after interruption.
    """

    def __init__(
        self,
        dry_run: bool = False,
        verify_only: bool = False,
        start_step: int = 1,
        only_step: Optional[int] = None,
        checkpoint_dir: Optional[str] = None,
        batch_size: int = 1000,
        dedup_backend: str = 'memory',
        dedup_db_path: Optional[str] = None,
        progress: bool | None = None,
    ):
        self.dry_run = dry_run
        self.verify_only = verify_only
        self.start_step = start_step
        self.only_step = only_step
        self.checkpoint_dir = checkpoint_dir or self._default_checkpoint_dir()
        if batch_size <= 0:
            raise ValueError(f'batch_size must be greater than 0, got {batch_size}')
        self.batch_size = batch_size
        self.progress = progress
        self._buffer: list[TupleOperation] = []
        self._deduplicator = TupleDeduplicator(
            RELATION_PRIORITY,
            backend=dedup_backend,
            db_path=dedup_db_path,
        )
        self._global_seen = self._deduplicator.memory
        self._stats = MigrationStats()
        self._fga = None
        self._failed_tuple_count = 0

    # ── Orchestration ─────────────────────────────────────────────

    async def run(self) -> MigrationStats | VerifyReport:
        """Execute the migration pipeline."""
        from bisheng.core.openfga.manager import aget_fga_client, get_fga_client

        try:
            self._fga = await aget_fga_client()
            if self._fga is None:
                self._fga = get_fga_client()
            if self._fga is None and not self.dry_run:
                raise RuntimeError('OpenFGA client not available. Cannot execute migration.')

            steps = self._migration_steps()
            self._validate_step_range(self.start_step, '--step')
            if self.only_step is not None:
                self._validate_step_range(self.only_step, '--only-step')

            if self.only_step is not None:
                checkpoint = 0
            elif self.dry_run:
                checkpoint = self.start_step - 1
            else:
                checkpoint = max(
                    self._load_checkpoint(),
                    self.start_step - 1,
                )
            mode = 'DRY-RUN' if self.dry_run else 'EXECUTE'
            logger.info(f'=== F006 Permission Migration ({mode}) ===')
            if self.only_step is not None:
                logger.info(f'Running only step {self.only_step}')
            elif self.dry_run:
                logger.info(f'Dry-run ignores saved checkpoint; preview starts from step {self.start_step}')
            elif checkpoint > 0:
                logger.info(f'Resuming from checkpoint: step {checkpoint} completed')
            selected_steps = [
                step for step in steps
                if step[0] == self.only_step or (self.only_step is None and step[0] > checkpoint)
            ]

            with ProgressTracker(
                enabled=self.progress,
                total=len(selected_steps),
                desc='F006 steps',
                unit='step',
            ) as step_bar:
                for step_num, step_name, step_fn in steps:
                    if self.only_step is not None and step_num != self.only_step:
                        logger.info(f'Step {step_num}: {step_name} — skipped (--only-step)')
                        continue
                    if step_num <= checkpoint:
                        logger.info(f'Step {step_num}: {step_name} — skipped (checkpoint)')
                        continue

                    t0 = time.monotonic()
                    count = await step_fn()
                    elapsed = time.monotonic() - t0
                    self._update_step_stat(step_num, count)
                    logger.info(f'Step {step_num}: {step_name} — {count} tuples ({elapsed:.1f}s)')
                    step_bar.update()

                    if not self.dry_run and self.only_step is None:
                        self._save_checkpoint(step_num)

            self._compute_summary()
            self._print_summary()
            if not self.dry_run and self._failed_tuple_count:
                raise RuntimeError(
                    f'F006 migration left {self._failed_tuple_count} unresolved tuple writes; '
                    'retry pending failed_tuples before marking migration complete',
                )
            return self._stats
        finally:
            self._deduplicator.close()

    def _migration_steps(self) -> list[tuple[int, str, StepFn]]:
        return [
            (1, 'Super Admin', self.step1_super_admin),
            (2, 'User Group Membership', self.step2_user_group_membership),
            (3, 'Role Access Expansion', self.step3_role_access),
            (4, 'Space/Channel Members', self.step4_space_channel_members),
            (5, 'Resource Owners', self.step5_resource_owners),
            (6, 'Folder Hierarchy', self.step6_folder_hierarchy),
            (7, 'Department Membership', self.step7_department_membership),
            (8, 'Group Resources', self.step8_group_resources),
        ]

    def _validate_step_range(self, step: int, flag_name: str) -> None:
        valid_steps = {step_num for step_num, _, _ in self._migration_steps()}
        if step not in valid_steps:
            min_step = min(valid_steps)
            max_step = max(valid_steps)
            raise ValueError(f'{flag_name} must be between {min_step} and {max_step}, got {step}')

    def _update_step_stat(self, step_num: int, count: int):
        attr_map = {
            1: 'step1_super_admin', 2: 'step2_user_group',
            3: 'step3_role_access', 4: 'step4_space_channel',
            5: 'step5_resource_owners', 6: 'step6_folder_hierarchy',
            7: 'step7_department_membership', 8: 'step8_group_resources',
        }
        attr = attr_map.get(step_num)
        if attr:
            setattr(self._stats, attr, count)

    def _compute_summary(self):
        s = self._stats
        total_seen = 0
        # Aggregate by object_type and relation from _global_seen
        by_type: dict[str, int] = {}
        by_rel: dict[str, int] = {}
        for (_, obj), rel in self._deduplicator.iter_seen():
            total_seen += 1
            obj_type = obj.split(':')[0] if ':' in obj else obj
            by_type[obj_type] = by_type.get(obj_type, 0) + 1
            by_rel[rel] = by_rel.get(rel, 0) + 1
        s.total = total_seen
        s.by_object_type = by_type
        s.by_relation = by_rel

    def _print_summary(self):
        s = self._stats
        mode = 'DRY-RUN' if self.dry_run else 'EXECUTE'
        mode_zh = '预览模式，不写入 OpenFGA' if self.dry_run else '执行模式，已写入 OpenFGA'
        lines = [
            f'\n=== F006 权限迁移汇总 ({mode}, {mode_zh}) ===',
            f'Step 1 — 系统管理员权限:          {s.step1_super_admin}',
            f'Step 2 — 用户组成员关系:          {s.step2_user_group}',
            f'Step 3 — role_access 资源权限展开: {s.step3_role_access}'
            + (f'  (展开前原始条目: {s.step3_raw})' if s.step3_raw else ''),
            f'Step 4 — 空间/频道成员权限:        {s.step4_space_channel}',
            f'Step 5 — 资源所有者 owner 权限:    {s.step5_resource_owners}',
        ]
        if s.step5_by_type:
            for t, c in sorted(s.step5_by_type.items()):
                lines.append(f'         {t}: {c}')
        lines.append(f'Step 6 — 知识库文件夹父子关系:   {s.step6_folder_hierarchy}')
        if s.step6_folders or s.step6_files:
            lines.append(f'         文件夹数量: {s.step6_folders}, 文件数量: {s.step6_files}')
        lines.append(f'Step 7 — 部门成员关系:            {s.step7_department_membership}')
        lines.append(f'Step 8 — 用户组资源管理权限:      {s.step8_group_resources}')
        lines.append(f'')
        lines.append(f'唯一 tuple 总数: {s.total}')
        if s.by_object_type:
            lines.append(f'按资源类型统计: {s.by_object_type}')
        if s.by_relation:
            lines.append(f'按关系类型统计: {s.by_relation}')
        if self.dry_run:
            lines.extend([
                '',
                '说明:',
                '- dry-run 只统计将要写入的权限 tuple，不会写入 OpenFGA，也不会保存 checkpoint。',
                '- Step 3 的“展开前原始条目”表示 role_access 按用户角色展开后的候选权限数量，最终写入数会经过去重和高优先级覆盖。',
                '- 各 Step 数表示该步骤去重后提交的 tuple 数；后续步骤若覆盖前面步骤的同一 key，Step 求和可以大于最终唯一 tuple 总数。',
                '- 唯一 tuple 总数表示本次 dry-run 预计最终需要保留的唯一权限关系数量。',
            ])
        else:
            lines.extend([
                '',
                '说明:',
                '- 各 Step 数表示该步骤去重后提交的 tuple 数；后续步骤若覆盖前面步骤的同一 key，Step 求和可以大于最终唯一 tuple 总数。',
                '- 唯一 tuple 总数表示迁移结束后最终保留在去重视图中的权限关系数量。',
            ])
        logger.info('\n'.join(lines))

    # ── Checkpoint ────────────────────────────────────────────────

    def _default_checkpoint_dir(self) -> str:
        d = os.path.join(tempfile.gettempdir(), 'bisheng-permission-migration')
        os.makedirs(d, exist_ok=True)
        return d

    def _checkpoint_path(self) -> str:
        return os.path.join(self.checkpoint_dir, _CHECKPOINT_FILENAME)

    def _load_checkpoint(self) -> int:
        path = self._checkpoint_path()
        if not os.path.exists(path):
            return 0
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            completed = data.get('completed_step', 0)
            logger.info(f'Checkpoint loaded: step {completed} completed at {data.get("timestamp", "?")}')
            return completed
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f'Failed to load checkpoint: {e}')
            return 0

    def _save_checkpoint(self, step: int):
        path = self._checkpoint_path()
        data = {
            'completed_step': step,
            'timestamp': datetime.now().isoformat(),
            'stats': self._stats.to_dict(),
        }
        try:
            with open(path, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.warning(f'Failed to save checkpoint: {e}')

    def clear_checkpoint(self):
        path = self._checkpoint_path()
        if not os.path.exists(path):
            return
        try:
            os.remove(path)
            logger.info(f'Checkpoint cleared: {path}')
        except OSError as e:
            logger.warning(f'Failed to clear checkpoint: {e}')

    # ── Migration Steps ──────────────────────────────────────────

    async def step1_super_admin(self) -> int:
        """Step 1: user_role (role_id=1) → (system:global, super_admin, user:{id})."""
        from bisheng.core.database import get_async_db_session
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.database.constants import AdminRole

        total = 0
        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                async for rows in iter_keyset_batches(
                    session,
                    lambda last_id: (
                            sa_text('SELECT id, user_id FROM userrole '
                                    'WHERE role_id = :rid AND id > :last_id '
                                    'ORDER BY id LIMIT :limit'),
                            {'rid': AdminRole, 'last_id': last_id},
                    ),
                    batch_size=self.batch_size,
                    progress=self.progress,
                    progress_desc='step1 userrole',
                ):
                    ops = [
                        TupleOperation(
                            action='write',
                            user=f'user:{row[1]}',
                            relation='super_admin',
                            object='system:global',
                        )
                        for row in rows
                    ]
                    self._collect(ops)
                    total += await self._flush()
        return total

    async def step2_user_group_membership(self) -> int:
        """Step 2: user_group → (user_group:{gid}, admin|member, user:{uid})."""
        from bisheng.core.database import get_async_db_session
        from bisheng.core.context.tenant import bypass_tenant_filter

        total = 0
        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                async for rows in iter_keyset_batches(
                    session,
                    lambda last_id: (
                            sa_text(
                                'SELECT picked.id, picked.user_id, picked.group_id, picked.is_group_admin '
                                'FROM ('
                                '  SELECT ug.id, ug.user_id, ug.group_id, ug.is_group_admin, '
                                '         ROW_NUMBER() OVER ('
                                '           PARTITION BY ug.user_id, ug.group_id '
                                '           ORDER BY ug.is_group_admin DESC, ug.update_time DESC, ug.create_time DESC, ug.id DESC'
                                '         ) AS rn '
                                '  FROM usergroup AS ug '
                                '  WHERE ug.id > :last_id'
                                ') AS picked '
                                'WHERE picked.rn = 1 '
                                'ORDER BY picked.id LIMIT :limit'
                            ),
                            {'last_id': last_id},
                    ),
                    batch_size=self.batch_size,
                    progress=self.progress,
                    progress_desc='step2 usergroup',
                ):
                    ops = [
                        TupleOperation(
                            action='write',
                            user=f'user:{row[1]}',
                            relation='admin' if row[3] else 'member',
                            object=f'user_group:{row[2]}',
                        )
                        for row in rows
                    ]
                    self._collect(ops)
                    total += await self._flush()
        return total

    async def step3_role_access(self) -> int:
        """Step 3: role_access (non-WEB_MENU, non-admin) → per-user resource tuples."""
        from bisheng.core.database import get_async_db_session
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.database.constants import AdminRole

        total = 0
        raw_count = 0
        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                async for role_accesses in iter_keyset_batches(
                    session,
                    lambda last_id: (
                            sa_text('SELECT id, role_id, third_id, type FROM roleaccess '
                                    'WHERE type != 99 AND role_id != :admin_rid '
                                    'AND id > :last_id ORDER BY id LIMIT :limit'),
                            {'admin_rid': AdminRole, 'last_id': last_id},
                    ),
                    batch_size=self.batch_size,
                    progress=self.progress,
                    progress_desc='step3 roleaccess',
                ):
                    for _, role_id, third_id, access_type in role_accesses:
                        mapping = ACCESS_TYPE_MAPPING.get(access_type)
                        if not mapping:
                            continue
                        obj_type, relation = mapping
                        object_types = [obj_type]
                        alias = KNOWLEDGE_LEGACY_TYPES.get(obj_type)
                        if alias:
                            object_types.append(alias)

                        async for user_rows in iter_keyset_batches(
                            session,
                            lambda last_id, role_id=role_id: (
                                    sa_text('SELECT id, user_id FROM userrole '
                                            'WHERE role_id = :role_id AND role_id != :admin_rid '
                                            'AND id > :last_id ORDER BY id LIMIT :limit'),
                                    {
                                        'role_id': role_id,
                                        'admin_rid': AdminRole,
                                        'last_id': last_id,
                                    },
                            ),
                            batch_size=self.batch_size,
                            progress=self.progress,
                            progress_desc=f'step3 userrole role={role_id}',
                        ):
                            ops = [
                                TupleOperation(
                                    action='write',
                                    user=f'user:{row[1]}',
                                    relation=relation,
                                    object=f'{target_type}:{third_id}',
                                )
                                for row in user_rows
                                for target_type in object_types
                            ]
                            raw_count += len(ops)
                            self._collect(ops)
                            total += await self._flush()

        self._stats.step3_raw = raw_count
        return total

    async def step4_space_channel_members(self) -> int:
        """Step 4: space_channel_member (ACTIVE) → owner/manager/viewer tuples."""
        from bisheng.core.database import get_async_db_session
        from bisheng.core.context.tenant import bypass_tenant_filter

        total = 0
        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                async for members in iter_keyset_batches(
                    session,
                    lambda last_id: (
                            sa_text("SELECT id, business_id, business_type, user_id, user_role "
                                    "FROM space_channel_member WHERE status = 'ACTIVE' "
                                    "AND id > :last_id ORDER BY id LIMIT :limit"),
                            {'last_id': last_id},
                    ),
                    batch_size=self.batch_size,
                    progress=self.progress,
                    progress_desc='step4 space_channel_member',
                ):
                    ops = []
                    for _, biz_id, biz_type, uid, role in members:
                        # Production enum values are uppercase; test fixtures use
                        # lowercase varchar. Normalize before lookup.
                        relation = SCM_ROLE_MAPPING.get((role or '').lower())
                        obj_type = SCM_TYPE_MAPPING.get((biz_type or '').lower())
                        if not relation or not obj_type:
                            logger.warning(f'Step 4: skip unknown role={role} or type={biz_type}')
                            continue
                        ops.append(TupleOperation(
                            action='write',
                            user=f'user:{uid}',
                            relation=relation,
                            object=f'{obj_type}:{biz_id}',
                        ))
                    self._collect(ops)
                    total += await self._flush()
        return total

    async def step5_resource_owners(self) -> int:
        """Step 5: resource tables user_id → owner tuples."""
        from bisheng.core.database import get_async_db_session
        from bisheng.core.context.tenant import bypass_tenant_filter

        owner_queries = [
            (
                'SELECT id, id, user_id FROM knowledge '
                'WHERE type != 3 AND id > :last_id ORDER BY id LIMIT :limit',
                'knowledge_library',
                False,
                0,
            ),
            (
                'SELECT id, id, user_id FROM knowledge '
                'WHERE type = 3 AND id > :last_id ORDER BY id LIMIT :limit',
                'knowledge_space',
                False,
                0,
            ),
            (
                'SELECT id, id, user_id FROM t_gpts_tools '
                'WHERE is_delete = 0 AND id > :last_id ORDER BY id LIMIT :limit',
                'tool',
                False,
                0,
            ),
            (
                'SELECT id, id, user_id FROM channel '
                'WHERE id > :last_id ORDER BY id LIMIT :limit',
                'channel',
                False,
                '',
            ),
            (
                'SELECT id, id, user_id FROM dashboard '
                'WHERE id > :last_id ORDER BY id LIMIT :limit',
                'dashboard',
                True,
                0,
            ),
        ]

        total = 0
        by_type: dict[str, int] = {}

        # Flow needs special handling: flow_type → object_type mapping
        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                async for rows in iter_keyset_batches(
                    session,
                    lambda last_id: (
                            sa_text('SELECT id, id, user_id, flow_type FROM flow '
                                    'WHERE flow_type IN (5, 10) AND id > :last_id '
                                    'ORDER BY id LIMIT :limit'),
                            {'last_id': str(last_id) if last_id else ''},
                    ),
                    batch_size=self.batch_size,
                    start_cursor='',
                    progress=self.progress,
                    progress_desc='step5 flow owners',
                ):
                    ops: list[TupleOperation] = []
                    for _, fid, uid, ft in rows:
                        obj_type = FLOW_TYPE_MAPPING.get(ft)
                        if obj_type:
                            ops.append(TupleOperation(
                                action='write', user=f'user:{uid}',
                                relation='owner', object=f'{obj_type}:{fid}',
                            ))
                            by_type[obj_type] = by_type.get(obj_type, 0) + 1
                    self._collect(ops)
                    total += await self._flush()

        # Generic owner queries
        for query, obj_type, skip_on_error, start_cursor in owner_queries:
            try:
                async with get_async_db_session() as session:
                    with bypass_tenant_filter():
                        async for rows in iter_keyset_batches(
                            session,
                            lambda last_id, query=query: (
                                    sa_text(query),
                                    {'last_id': last_id},
                            ),
                            batch_size=self.batch_size,
                            start_cursor=start_cursor,
                            progress=self.progress,
                            progress_desc=f'step5 {obj_type} owners',
                        ):
                            ops = [
                                TupleOperation(
                                    action='write', user=f'user:{uid}',
                                    relation='owner', object=f'{obj_type}:{rid}',
                                )
                                for _, rid, uid in rows
                            ]
                            by_type[obj_type] = by_type.get(obj_type, 0) + len(ops)
                            self._collect(ops)
                            total += await self._flush()
            except Exception as e:
                if skip_on_error:
                    logger.warning(f'Owner migration for {obj_type} skipped: {e}')
                else:
                    raise

        self._stats.step5_by_type = by_type

        return total

    async def step6_folder_hierarchy(self) -> int:
        """Step 6: knowledge_file → parent tuples (folder/knowledge_file hierarchy)."""
        from bisheng.core.database import get_async_db_session
        from bisheng.core.context.tenant import bypass_tenant_filter

        total = 0
        folders = 0
        file_count = 0
        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                async for files in iter_keyset_batches(
                    session,
                    lambda last_id: (
                            sa_text('SELECT id, id, knowledge_id, file_type, file_level_path '
                                    'FROM knowledgefile WHERE id > :last_id '
                                    'ORDER BY id LIMIT :limit'),
                            {'last_id': last_id},
                    ),
                    batch_size=self.batch_size,
                    progress=self.progress,
                    progress_desc='step6 knowledgefile',
                ):
                    ops = []
                    for _, fid, kid, ftype, fpath in files:
                        parent_type, parent_id = self._resolve_parent(fid, kid, fpath)
                        if parent_type is None:
                            continue
                        child_type = 'folder' if ftype == 0 else 'knowledge_file'
                        ops.append(TupleOperation(
                            action='write',
                            user=f'{parent_type}:{parent_id}',
                            relation='parent',
                            object=f'{child_type}:{fid}',
                        ))
                        if ftype == 0:
                            folders += 1
                        else:
                            file_count += 1
                    self._collect(ops)
                    total += await self._flush()

        self._stats.step6_folders = folders
        self._stats.step6_files = file_count
        return total

    async def step7_department_membership(self) -> int:
        """Step 7: user_department -> user:{uid} member department:{dept_id}."""
        from bisheng.core.database import get_async_db_session
        from bisheng.core.context.tenant import bypass_tenant_filter

        total = 0
        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                async for rows in iter_keyset_batches(
                    session,
                    lambda last_id: (
                            sa_text('SELECT id, user_id, department_id FROM user_department '
                                    'WHERE id > :last_id ORDER BY id LIMIT :limit'),
                            {'last_id': last_id},
                    ),
                    batch_size=self.batch_size,
                    progress=self.progress,
                    progress_desc='step7 user_department',
                ):
                    ops = [
                        TupleOperation(
                            action='write',
                            user=f'user:{user_id}',
                            relation='member',
                            object=f'department:{department_id}',
                        )
                        for _, user_id, department_id in rows
                    ]
                    self._collect(ops)
                    total += await self._flush()
        return total

    async def step8_group_resources(self) -> int:
        """Step 8: groupresource -> user_group admin manager tuples.

        Legacy ``groupresource`` drives the resources managed by user-group
        administrators, not ordinary group members, so migrate it through the
        ``user_group:{id}#admin`` userset with manager-level access.
        """
        from bisheng.core.database import get_async_db_session
        from bisheng.core.context.tenant import bypass_tenant_filter

        total = 0
        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                async for rows in iter_keyset_batches(
                    session,
                    lambda last_id: (
                            sa_text('SELECT id, group_id, third_id, type FROM groupresource '
                                    'WHERE id > :last_id ORDER BY id LIMIT :limit'),
                            {'last_id': last_id},
                    ),
                    batch_size=self.batch_size,
                    progress=self.progress,
                    progress_desc='step8 groupresource',
                ):
                    ops: list[TupleOperation] = []
                    for _, group_id, third_id, resource_type in rows:
                        object_types = GROUP_RESOURCE_TYPE_MAPPING.get(resource_type)
                        if not object_types:
                            continue
                        for object_type in object_types:
                            ops.append(TupleOperation(
                                action='write',
                                user=f'user_group:{group_id}#admin',
                                relation='manager',
                                object=f'{object_type}:{third_id}',
                            ))
                    self._collect(ops)
                    total += await self._flush()
        return total

    # ── Tuple Collection & Writing ────────────────────────────────

    def _collect(self, ops: list[TupleOperation]):
        """Accumulate tuples with global cross-step dedup."""
        for op in ops:
            decision = self._deduplicator.record(op.user, op.object, op.relation)
            if decision.accepted:
                self._buffer.append(op)
            # else: skip — a higher-priority relation already collected

    async def _flush(self) -> int:
        """Dedup the buffer, batch-write to OpenFGA, return count."""
        if not self._buffer:
            return 0

        deduped = self._dedup_tuples(self._buffer)
        self._buffer.clear()
        unique_step_count = len(deduped)

        if self.dry_run:
            return unique_step_count

        written = 0
        with ProgressTracker(
            enabled=self.progress,
            total=len(deduped),
            desc='OpenFGA writes',
            unit='tuple',
        ) as bar:
            for i in range(0, len(deduped), _BATCH_SIZE):
                batch = deduped[i:i + _BATCH_SIZE]
                writes = [
                    {'user': t.user, 'relation': t.relation, 'object': t.object}
                    for t in batch
                ]
                try:
                    await self._fga.write_tuples(writes=writes)
                    written += len(batch)
                except FGAWriteError:
                    # Batch may contain "already exists" — fall back to singles
                    written += await self._write_singles(batch)
                except FGAConnectionError:
                    raise  # Unrecoverable — abort, don't save checkpoint
                finally:
                    bar.update(len(batch))
        return unique_step_count

    async def _write_singles(self, tuples: list[TupleOperation]) -> int:
        """Fall back to single-tuple writes. Record failures to FailedTuple."""
        written = 0
        for t in tuples:
            try:
                await self._fga.write_tuples(
                    writes=[{'user': t.user, 'relation': t.relation, 'object': t.object}]
                )
                written += 1
            except FGAWriteError as e:
                err_lower = str(e).lower()
                if 'already exists' in err_lower or 'cannot write' in err_lower:
                    written += 1  # Idempotent — tuple already present
                else:
                    logger.warning(f'Failed tuple: {t} — {e}')
                    self._failed_tuple_count += 1
                    await self._save_failed_tuple(t, str(e))
            except FGAConnectionError:
                raise
        return written

    async def _save_failed_tuple(self, op: TupleOperation, error: str):
        """Record a failed tuple write to the compensation table (INV-4)."""
        try:
            from bisheng.database.models.failed_tuple import FailedTuple, FailedTupleDao
            ft = FailedTuple(
                action=op.action,
                fga_user=op.user,
                relation=op.relation,
                object=op.object,
                status='pending',
                error_message=error[:500],
            )
            await FailedTupleDao.acreate_batch([ft])
        except Exception as e:
            logger.error(f'Failed to save FailedTuple: {e}')

    def _dedup_tuples(self, tuples: list[TupleOperation]) -> list[TupleOperation]:
        """Within a buffer, keep only the highest-priority relation per (user, object)."""
        best: dict[tuple[str, str], TupleOperation] = {}
        for t in tuples:
            key = (t.user, t.object)
            if key not in best:
                best[key] = t
            else:
                new_prio = RELATION_PRIORITY.get(t.relation, 0)
                old_prio = RELATION_PRIORITY.get(best[key].relation, 0)
                if new_prio > old_prio:
                    best[key] = t
        return list(best.values())

    # ── Utility ───────────────────────────────────────────────────

    @staticmethod
    def _resolve_parent(
        file_id, knowledge_id, file_level_path,
    ) -> tuple[Optional[str], Optional[str]]:
        """Derive parent (type, id) from file_level_path materialized path."""
        path = file_level_path or ''
        segments = [s for s in path.split('/') if s]
        if not segments:
            return ('knowledge_library', str(knowledge_id))
        last = segments[-1]
        if not last.isdigit():
            logger.warning(f'Invalid path segment "{last}" for file {file_id}, skipping')
            return (None, None)
        return ('folder', last)
