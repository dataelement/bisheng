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
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import text as sa_text

from bisheng.core.openfga.exceptions import FGAConnectionError, FGAWriteError
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation

# ── Mapping Constants ─────────────────────────────────────────────

ACCESS_TYPE_MAPPING: dict[int, tuple[str, str]] = {
    # AccessType.value → (object_type, relation)
    1:  ('knowledge_library', 'viewer'),  # KNOWLEDGE
    3:  ('knowledge_library', 'editor'),  # KNOWLEDGE_WRITE
    5:  ('assistant', 'viewer'),           # ASSISTANT_READ
    6:  ('assistant', 'editor'),           # ASSISTANT_WRITE
    7:  ('tool', 'viewer'),                # GPTS_TOOL_READ
    8:  ('tool', 'editor'),                # GPTS_TOOL_WRITE
    9:  ('workflow', 'viewer'),            # WORKFLOW
    10: ('workflow', 'editor'),            # WORKFLOW_WRITE
    11: ('dashboard', 'viewer'),           # DASHBOARD
    12: ('dashboard', 'editor'),           # DASHBOARD_WRITE
    # 99: WEB_MENU → not migrated
}

FLOW_TYPE_MAPPING: dict[int, str] = {
    5:  'assistant',    # ASSISTANT
    10: 'workflow',     # WORKFLOW
    # 15, 20, 25, 30 → not migrated
}

RELATION_PRIORITY: dict[str, int] = {
    'owner': 4,
    'manager': 3,
    'editor': 2,
    'viewer': 1,
}

SCM_ROLE_MAPPING: dict[str, str] = {
    'creator': 'owner',
    'admin': 'manager',
    'member': 'viewer',
}

SCM_TYPE_MAPPING: dict[str, str] = {
    'space': 'knowledge_space',
    'channel': 'channel',
}

_BATCH_SIZE = 100
_CHECKPOINT_FILENAME = 'migration_f006_checkpoint.json'


# ── Data Classes ──────────────────────────────────────────────────

@dataclass
class MigrationStats:
    step1_super_admin: int = 0
    step2_user_group: int = 0
    step3_role_access: int = 0
    step3_raw: int = 0
    step4_space_channel: int = 0
    step5_resource_owners: int = 0
    step5_by_type: dict = field(default_factory=dict)
    step6_folder_hierarchy: int = 0
    step6_folders: int = 0
    step6_files: int = 0
    step7_department_membership: int = 0
    total: int = 0
    by_object_type: dict = field(default_factory=dict)
    by_relation: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerifyReport:
    total: int = 0
    match: int = 0
    regression: int = 0
    expansion: int = 0


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
        checkpoint_dir: Optional[str] = None,
    ):
        self.dry_run = dry_run
        self.verify_only = verify_only
        self.start_step = start_step
        self.checkpoint_dir = checkpoint_dir or self._default_checkpoint_dir()
        self._buffer: list[TupleOperation] = []
        self._global_seen: dict[tuple[str, str], str] = {}
        self._stats = MigrationStats()
        self._fga = None

    # ── Orchestration ─────────────────────────────────────────────

    async def run(self) -> MigrationStats | VerifyReport:
        """Execute the migration pipeline."""
        from bisheng.core.openfga.manager import get_fga_client

        self._fga = get_fga_client()
        if self._fga is None and not self.dry_run:
            raise RuntimeError('OpenFGA client not available. Cannot execute migration.')

        if self.verify_only:
            return await self.verify_all()

        checkpoint = max(self._load_checkpoint(), self.start_step - 1)
        mode = 'DRY-RUN' if self.dry_run else 'EXECUTE'
        logger.info(f'=== F006 Permission Migration ({mode}) ===')
        if checkpoint > 0:
            logger.info(f'Resuming from checkpoint: step {checkpoint} completed')

        steps = [
            (1, 'Super Admin', self.step1_super_admin),
            (2, 'User Group Membership', self.step2_user_group_membership),
            (3, 'Role Access Expansion', self.step3_role_access),
            (4, 'Space/Channel Members', self.step4_space_channel_members),
            (5, 'Resource Owners', self.step5_resource_owners),
            (6, 'Folder Hierarchy', self.step6_folder_hierarchy),
            (7, 'Department Membership', self.step7_department_membership),
        ]

        for step_num, step_name, step_fn in steps:
            if step_num <= checkpoint:
                logger.info(f'Step {step_num}: {step_name} — skipped (checkpoint)')
                continue

            t0 = time.monotonic()
            count = await step_fn()
            elapsed = time.monotonic() - t0
            self._update_step_stat(step_num, count)
            logger.info(f'Step {step_num}: {step_name} — {count} tuples ({elapsed:.1f}s)')

            if not self.dry_run:
                self._save_checkpoint(step_num)

        self._compute_summary()
        self._print_summary()
        return self._stats

    def _update_step_stat(self, step_num: int, count: int):
        attr_map = {
            1: 'step1_super_admin', 2: 'step2_user_group',
            3: 'step3_role_access', 4: 'step4_space_channel',
            5: 'step5_resource_owners', 6: 'step6_folder_hierarchy',
            7: 'step7_department_membership',
        }
        attr = attr_map.get(step_num)
        if attr:
            setattr(self._stats, attr, count)

    def _compute_summary(self):
        s = self._stats
        s.total = (s.step1_super_admin + s.step2_user_group + s.step3_role_access
                   + s.step4_space_channel + s.step5_resource_owners
                   + s.step6_folder_hierarchy + s.step7_department_membership)
        # Aggregate by object_type and relation from _global_seen
        by_type: dict[str, int] = {}
        by_rel: dict[str, int] = {}
        for (_, obj), rel in self._global_seen.items():
            obj_type = obj.split(':')[0] if ':' in obj else obj
            by_type[obj_type] = by_type.get(obj_type, 0) + 1
            by_rel[rel] = by_rel.get(rel, 0) + 1
        s.by_object_type = by_type
        s.by_relation = by_rel

    def _print_summary(self):
        s = self._stats
        mode = 'DRY-RUN' if self.dry_run else 'EXECUTE'
        lines = [
            f'\n=== F006 Migration Summary ({mode}) ===',
            f'Step 1 — Super Admin:           {s.step1_super_admin}',
            f'Step 2 — User Group Membership: {s.step2_user_group}',
            f'Step 3 — Role Access Expansion: {s.step3_role_access}'
            + (f'  (raw: {s.step3_raw})' if s.step3_raw else ''),
            f'Step 4 — Space/Channel Members: {s.step4_space_channel}',
            f'Step 5 — Resource Owners:       {s.step5_resource_owners}',
        ]
        if s.step5_by_type:
            for t, c in sorted(s.step5_by_type.items()):
                lines.append(f'         {t}: {c}')
        lines.append(f'Step 6 — Folder Hierarchy:      {s.step6_folder_hierarchy}')
        if s.step6_folders or s.step6_files:
            lines.append(f'         folders: {s.step6_folders}, files: {s.step6_files}')
        lines.append(f'Step 7 — Department Membership: {s.step7_department_membership}')
        lines.append(f'')
        lines.append(f'Total unique tuples: {s.total}')
        if s.by_object_type:
            lines.append(f'By object_type: {s.by_object_type}')
        if s.by_relation:
            lines.append(f'By relation:    {s.by_relation}')
        logger.info('\n'.join(lines))

    # ── Checkpoint ────────────────────────────────────────────────

    def _default_checkpoint_dir(self) -> str:
        d = os.path.dirname(os.path.abspath(__file__))
        if os.access(d, os.W_OK):
            return d
        return '/tmp'

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

    # ── Migration Steps ──────────────────────────────────────────

    async def step1_super_admin(self) -> int:
        """Step 1: user_role (role_id=1) → (system:global, super_admin, user:{id})."""
        from bisheng.core.database import get_async_db_session
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.database.constants import AdminRole

        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                result = await session.execute(
                    sa_text('SELECT user_id FROM userrole WHERE role_id = :rid'),
                    {'rid': AdminRole},
                )
                admin_user_ids = [row[0] for row in result.fetchall()]

        ops = [
            TupleOperation(
                action='write',
                user=f'user:{uid}',
                relation='super_admin',
                object='system:global',
            )
            for uid in admin_user_ids
        ]
        self._collect(ops)
        return await self._flush()

    async def step2_user_group_membership(self) -> int:
        """Step 2: user_group → (user_group:{gid}, admin|member, user:{uid})."""
        from bisheng.core.database import get_async_db_session
        from bisheng.core.context.tenant import bypass_tenant_filter

        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                result = await session.execute(
                    sa_text('SELECT user_id, group_id, is_group_admin FROM usergroup')
                )
                rows = result.fetchall()

        ops = [
            TupleOperation(
                action='write',
                user=f'user:{row[0]}',
                relation='admin' if row[2] else 'member',
                object=f'user_group:{row[1]}',
            )
            for row in rows
        ]
        self._collect(ops)
        return await self._flush()

    async def step3_role_access(self) -> int:
        """Step 3: role_access (non-WEB_MENU, non-admin) → per-user resource tuples."""
        from bisheng.core.database import get_async_db_session
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.database.constants import AdminRole

        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                ra_result = await session.execute(
                    sa_text('SELECT role_id, third_id, type FROM roleaccess '
                            'WHERE type != 99 AND role_id != :admin_rid'),
                    {'admin_rid': AdminRole},
                )
                role_accesses = ra_result.fetchall()

                ur_result = await session.execute(
                    sa_text('SELECT user_id, role_id FROM userrole WHERE role_id != :admin_rid'),
                    {'admin_rid': AdminRole},
                )
                user_roles = ur_result.fetchall()

        role_user_map: dict[int, list[int]] = {}
        for uid, rid in user_roles:
            role_user_map.setdefault(rid, []).append(uid)

        raw_ops = []
        for role_id, third_id, access_type in role_accesses:
            mapping = ACCESS_TYPE_MAPPING.get(access_type)
            if not mapping:
                continue
            obj_type, relation = mapping
            for uid in role_user_map.get(role_id, []):
                raw_ops.append(TupleOperation(
                    action='write',
                    user=f'user:{uid}',
                    relation=relation,
                    object=f'{obj_type}:{third_id}',
                ))

        self._stats.step3_raw = len(raw_ops)
        self._collect(raw_ops)
        return await self._flush()

    async def step4_space_channel_members(self) -> int:
        """Step 4: space_channel_member (ACTIVE) → owner/manager/viewer tuples."""
        from bisheng.core.database import get_async_db_session
        from bisheng.core.context.tenant import bypass_tenant_filter

        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                result = await session.execute(
                    sa_text("SELECT business_id, business_type, user_id, user_role "
                            "FROM space_channel_member WHERE status = 'ACTIVE'")
                )
                members = result.fetchall()

        ops = []
        for biz_id, biz_type, uid, role in members:
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
        return await self._flush()

    async def step5_resource_owners(self) -> int:
        """Step 5: resource tables user_id → owner tuples."""
        from bisheng.core.database import get_async_db_session
        from bisheng.core.context.tenant import bypass_tenant_filter

        owner_queries = [
            ('SELECT id, user_id FROM knowledge WHERE type != 3', 'knowledge_library', False),
            ('SELECT id, user_id FROM knowledge WHERE type = 3', 'knowledge_space', False),
            ('SELECT id, user_id FROM t_gpts_tools WHERE is_delete = 0', 'tool', False),
            ('SELECT id, user_id FROM channel', 'channel', False),
            ('SELECT id, user_id FROM dashboard', 'dashboard', True),
        ]

        ops: list[TupleOperation] = []

        # Flow needs special handling: flow_type → object_type mapping
        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                result = await session.execute(
                    sa_text('SELECT id, user_id, flow_type FROM flow '
                            'WHERE flow_type IN (5, 10)')
                )
                for fid, uid, ft in result.fetchall():
                    obj_type = FLOW_TYPE_MAPPING.get(ft)
                    if obj_type:
                        ops.append(TupleOperation(
                            action='write', user=f'user:{uid}',
                            relation='owner', object=f'{obj_type}:{fid}',
                        ))

        # Generic owner queries
        for query, obj_type, skip_on_error in owner_queries:
            try:
                async with get_async_db_session() as session:
                    with bypass_tenant_filter():
                        result = await session.execute(sa_text(query))
                        for rid, uid in result.fetchall():
                            ops.append(TupleOperation(
                                action='write', user=f'user:{uid}',
                                relation='owner', object=f'{obj_type}:{rid}',
                            ))
            except Exception as e:
                if skip_on_error:
                    logger.warning(f'Owner migration for {obj_type} skipped: {e}')
                else:
                    raise

        by_type: dict[str, int] = {}
        for op in ops:
            t = op.object.split(':')[0]
            by_type[t] = by_type.get(t, 0) + 1
        self._stats.step5_by_type = by_type

        self._collect(ops)
        return await self._flush()

    async def step6_folder_hierarchy(self) -> int:
        """Step 6: knowledge_file → parent tuples (folder/knowledge_file hierarchy)."""
        from bisheng.core.database import get_async_db_session
        from bisheng.core.context.tenant import bypass_tenant_filter

        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                result = await session.execute(
                    sa_text('SELECT id, knowledge_id, file_type, file_level_path '
                            'FROM knowledgefile')
                )
                files = result.fetchall()

        ops = []
        folders = 0
        file_count = 0
        for fid, kid, ftype, fpath in files:
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

        self._stats.step6_folders = folders
        self._stats.step6_files = file_count
        self._collect(ops)
        return await self._flush()

    async def step7_department_membership(self) -> int:
        """Step 7: user_department -> user:{uid} member department:{dept_id}."""
        from bisheng.core.database import get_async_db_session
        from bisheng.core.context.tenant import bypass_tenant_filter

        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                result = await session.execute(
                    sa_text('SELECT user_id, department_id FROM user_department')
                )
                rows = result.fetchall()

        ops = [
            TupleOperation(
                action='write',
                user=f'user:{user_id}',
                relation='member',
                object=f'department:{department_id}',
            )
            for user_id, department_id in rows
        ]
        self._collect(ops)
        return await self._flush()

    # ── Verify (stub — implemented in T7) ─────────────────────────

    async def verify_all(self) -> VerifyReport:
        """Sample users/resources and compare old RBAC vs new ReBAC can_read results."""
        from bisheng.core.database import get_async_db_session
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.database.constants import AdminRole

        report = VerifyReport()

        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                user_result = await session.execute(
                    sa_text('SELECT DISTINCT user_id FROM userrole '
                            'WHERE role_id != :admin_rid LIMIT 100'),
                    {'admin_rid': AdminRole},
                )
                user_ids = [r[0] for r in user_result.fetchall()]

                # Sample resources (each type ≤100)
                resources: list[tuple[str, str]] = []

                for query, obj_type in [
                    ('SELECT id FROM knowledge WHERE type != 3 LIMIT 100', 'knowledge_library'),
                    ('SELECT id FROM knowledge WHERE type = 3 LIMIT 100', 'knowledge_space'),
                    ("SELECT id FROM flow WHERE flow_type = 10 LIMIT 100", 'workflow'),
                    ("SELECT id FROM flow WHERE flow_type = 5 LIMIT 100", 'assistant'),
                    ('SELECT id FROM t_gpts_tools WHERE is_delete = 0 LIMIT 100', 'tool'),
                    ('SELECT id FROM channel LIMIT 100', 'channel'),
                ]:
                    try:
                        res = await session.execute(sa_text(query))
                        for row in res.fetchall():
                            resources.append((obj_type, str(row[0])))
                    except Exception:
                        continue

                ur_result = await session.execute(sa_text('SELECT user_id, role_id FROM userrole'))
                user_role_map: dict[int, list[int]] = {}
                for uid, rid in ur_result.fetchall():
                    user_role_map.setdefault(uid, []).append(rid)

                owner_map: dict[tuple[str, str], int] = {}
                for query, obj_type in [
                    ('SELECT id, user_id FROM knowledge WHERE type != 3', 'knowledge_library'),
                    ('SELECT id, user_id FROM knowledge WHERE type = 3', 'knowledge_space'),
                    ("SELECT id, user_id FROM flow WHERE flow_type = 10", 'workflow'),
                    ("SELECT id, user_id FROM flow WHERE flow_type = 5", 'assistant'),
                    ('SELECT id, user_id FROM t_gpts_tools WHERE is_delete = 0', 'tool'),
                    ('SELECT id, user_id FROM channel', 'channel'),
                ]:
                    try:
                        res = await session.execute(sa_text(query))
                        for oid, uid in res.fetchall():
                            owner_map[(obj_type, str(oid))] = uid
                    except Exception:
                        continue

                ra_result = await session.execute(
                    sa_text('SELECT role_id, third_id, type FROM roleaccess WHERE type != 99')
                )
                role_access_set: set[tuple[int, str, int]] = set()
                for rid, tid, atype in ra_result.fetchall():
                    role_access_set.add((rid, tid, atype))

                # space_channel_member: (user_id, business_type, business_id) for ACTIVE
                scm_set: set[tuple[int, str, str]] = set()
                try:
                    scm_result = await session.execute(
                        sa_text("SELECT user_id, business_type, business_id "
                                "FROM space_channel_member WHERE status = 'ACTIVE'")
                    )
                    for s_uid, s_btype, s_bid in scm_result.fetchall():
                        # Normalize case to match scm_type_reverse lookup below.
                        scm_set.add((s_uid, (s_btype or '').lower(), s_bid))
                except Exception:
                    pass  # table may not exist

        if not user_ids or not resources:
            logger.warning('Verify: no users or resources to check')
            return report

        # Reverse map: object_type → business_type for SCM lookup
        scm_type_reverse = {'knowledge_space': 'space', 'channel': 'channel'}

        # Check each (user, resource) pair
        for uid in user_ids:
            for obj_type, obj_id in resources:
                # Old system check: owner OR role_access OR space_channel_member?
                old_result = False
                if owner_map.get((obj_type, obj_id)) == uid:
                    old_result = True
                else:
                    user_roles = user_role_map.get(uid, [])
                    read_types = {
                        'knowledge_library': 1,
                        'knowledge_space': 1, 'assistant': 5, 'tool': 7,
                        'workflow': 9, 'dashboard': 11,
                    }
                    read_type = read_types.get(obj_type)
                    if read_type:
                        for rid in user_roles:
                            if (rid, obj_id, read_type) in role_access_set:
                                old_result = True
                                break

                # Also check space_channel_member (Step 4 source)
                if not old_result:
                    biz_type = scm_type_reverse.get(obj_type)
                    if biz_type and (uid, biz_type, obj_id) in scm_set:
                        old_result = True

                # New system check via PermissionService
                try:
                    from bisheng.permission.domain.services.permission_service import PermissionService
                    new_result = await PermissionService.check(
                        user_id=uid,
                        relation='can_read',
                        object_type=obj_type,
                        object_id=obj_id,
                    )
                except Exception:
                    new_result = False

                report.total += 1
                if old_result == new_result:
                    report.match += 1
                elif old_result and not new_result:
                    report.regression += 1
                    logger.warning(f'REGRESSION: user:{uid} {obj_type}:{obj_id} '
                                   f'old=YES new=NO')
                else:
                    report.expansion += 1

        # Print verify report
        lines = [
            '\n=== F006 Permission Verification ===',
            f'Checked: {len(user_ids)} users × {len(resources)} resources = {report.total} checks',
            f'  Match:      {report.match}',
            f'  Regression: {report.regression}  {"← MUST be 0" if report.regression else "✓"}',
            f'  Expansion:  {report.expansion}  (acceptable)',
            f'Exit code: {"1 (FAIL)" if report.regression > 0 else "0 (PASS)"}',
        ]
        logger.info('\n'.join(lines))
        return report

    # ── Tuple Collection & Writing ────────────────────────────────

    def _collect(self, ops: list[TupleOperation]):
        """Accumulate tuples with global cross-step dedup."""
        for op in ops:
            key = (op.user, op.object)
            new_prio = RELATION_PRIORITY.get(op.relation, 0)
            existing_rel = self._global_seen.get(key, '')
            existing_prio = RELATION_PRIORITY.get(existing_rel, 0)
            if new_prio >= existing_prio:
                self._global_seen[key] = op.relation
                self._buffer.append(op)
            # else: skip — a higher-priority relation already collected

    async def _flush(self) -> int:
        """Dedup the buffer, batch-write to OpenFGA, return count."""
        if not self._buffer:
            return 0

        deduped = self._dedup_tuples(self._buffer)
        self._buffer.clear()

        if self.dry_run:
            return len(deduped)

        written = 0
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
        return written

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


# ── CLI Entry Point ───────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='F006: RBAC → ReBAC Permission Migration',
        epilog='Migrates legacy permission data to OpenFGA for BiSheng v2.5.',
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Preview migration statistics without writing to OpenFGA',
    )
    parser.add_argument(
        '--verify', action='store_true',
        help='Compare old RBAC and new ReBAC permission checks',
    )
    parser.add_argument(
        '--step', type=int, default=1, metavar='N',
        help='Start from step N (default: 1)',
    )
    args = parser.parse_args()

    async def _run():
        from bisheng.common.services.config_service import settings
        from bisheng.core.context import initialize_app_context
        await initialize_app_context(config=settings)

        migrator = RBACToReBACMigrator(
            dry_run=args.dry_run,
            verify_only=args.verify,
            start_step=args.step,
        )
        result = await migrator.run()

        if args.verify and isinstance(result, VerifyReport) and result.regression > 0:
            logger.error(f'VERIFY FAILED: {result.regression} regressions detected')
            sys.exit(1)

    asyncio.run(_run())


if __name__ == '__main__':
    main()
