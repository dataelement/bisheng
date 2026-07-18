"""Reconcile role_access (MySQL) ↔ OpenFGA tuples for resource permissions.

After the RBAC→ReBAC migration (F006 step3), the old role_access/refresh API
continued to update MySQL without syncing FGA. This script rebuilds the
per-user FGA tuples so they match the current MySQL role_access state.

Algorithm:
  1. Read all non-WEB_MENU role_access rows and expand via user_role to
     per-user (user_id, object_type, relation, resource_id) tuples — the
     "desired" set.
  2. Read existing user:* FGA tuples for users that currently belong to roles.
  3. Diff: write desired tuples missing from FGA; delete stale user:* tuples
     only when they are not backed by an explicit resource permission binding.

Usage:
    python -m bisheng.permission.migration.reconcile_role_access_fga
    python -m bisheng.permission.migration.reconcile_role_access_fga --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger
from sqlalchemy import text as sa_text

from bisheng.permission.migration.f006_constants import (
    ACCESS_TYPE_MAPPING,
    FLOW_TYPE_MAPPING,
    KNOWLEDGE_LEGACY_TYPES,
    SCM_ROLE_MAPPING,
    SCM_TYPE_MAPPING,
)
from bisheng.permission.migration.batch_utils import ProgressTracker, iter_keyset_batches

RESOURCE_TYPES_WITH_FGA = sorted({obj_type for obj_type, _ in ACCESS_TYPE_MAPPING.values()})

SUMMARY_FIELD_NOTES_ZH = {
    'source_role_access_rows': '原始 role_access 表中参与迁移对比的记录数，不包含 WEB_MENU 和管理员角色记录。',
    'source_expanded_permissions': '从 role_access 按用户角色展开后的权限条目数量，包含 knowledge_library/knowledge_space 兼容展开。',
    'source_unique_permissions': '展开并去重后的预写入权限数量，也就是 MySQL 原始表当前期望写入 OpenFGA 的唯一权限数。',
    'actual_fga_permissions': '当前 OpenFGA 中扫描到的相关 viewer/editor 用户权限数量。',
    'planned_writes': 'dry-run 预测需要新增写入 OpenFGA 的权限数量。',
    'planned_deletes': 'dry-run 预测需要从 OpenFGA 删除的陈旧权限数量。',
    'protected_permissions': '虽然不在 role_access 期望集合中，但被显式资源授权或空间/频道成员关系保护而不会删除的权限数量。',
    'actual_only_permissions': '当前 OpenFGA 中存在但 MySQL role_access 期望集合中不存在的权限数量，包含 protected 和 planned_deletes。',
    'fga_read_failures': '读取 OpenFGA 资源 tuple 失败的资源数量；大于 0 时对比报告不完整。',
}

DETAIL_FILE_NOTES_ZH = {
    'planned_writes.jsonl': '每行是一条 dry-run 预测需要写入 OpenFGA 的权限。',
    'planned_deletes.jsonl': '每行是一条 dry-run 预测需要从 OpenFGA 删除的权限。',
    'protected.jsonl': '每行是一条被保护、不会删除的 OpenFGA 权限。',
    'actual_only.jsonl': '每行是一条 OpenFGA 中存在但 role_access 期望集合中不存在的权限。',
}


@dataclass
class Stats:
    source_role_access_rows: int = 0
    source_expanded_permissions: int = 0
    source_unique_permissions: int = 0
    desired: int = 0
    actual: int = 0
    to_write: int = 0
    to_delete: int = 0
    protected: int = 0
    written: int = 0
    deleted: int = 0


async def _session_exec(session, statement, params: dict | None = None):
    if hasattr(session, 'exec'):
        if params is None:
            return await session.exec(statement)
        return await session.exec(statement, params=params)
    if params is None:
        return await session.execute(statement)
    return await session.execute(statement, params)


@dataclass
class SourcePermissionSnapshot:
    role_access_rows: int
    expanded_permissions: int
    desired: set[tuple[str, str, str, str]]


def _create_workspace(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous = NORMAL;
        CREATE TABLE IF NOT EXISTS desired_tuple (
            user TEXT NOT NULL,
            relation TEXT NOT NULL,
            object_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            PRIMARY KEY (user, relation, object_type, resource_id)
        );
        CREATE TABLE IF NOT EXISTS actual_tuple (
            user TEXT NOT NULL,
            relation TEXT NOT NULL,
            object_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            PRIMARY KEY (user, relation, object_type, resource_id)
        );
        CREATE TABLE IF NOT EXISTS protected_tuple (
            user TEXT NOT NULL,
            relation TEXT NOT NULL,
            object_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            PRIMARY KEY (user, relation, object_type, resource_id)
        );
        CREATE TABLE IF NOT EXISTS candidate_user (
            user TEXT PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS candidate_resource (
            object_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            PRIMARY KEY (object_type, resource_id)
        );
        CREATE TABLE IF NOT EXISTS diff_tuple (
            action TEXT NOT NULL,
            user TEXT NOT NULL,
            relation TEXT NOT NULL,
            object_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            PRIMARY KEY (action, user, relation, object_type, resource_id)
        );
        CREATE INDEX IF NOT EXISTS idx_diff_action ON diff_tuple(action);
        CREATE INDEX IF NOT EXISTS idx_diff_object_type ON diff_tuple(action, object_type);
        CREATE INDEX IF NOT EXISTS idx_diff_relation ON diff_tuple(action, relation);
        """
    )
    return conn


def _insert_tuples(conn: sqlite3.Connection, table: str, rows: list[tuple[str, str, str, str]]) -> None:
    if not rows:
        return
    conn.executemany(
        f'INSERT OR IGNORE INTO {table}(user, relation, object_type, resource_id) '
        'VALUES (?, ?, ?, ?)',
        rows,
    )
    conn.commit()


def _insert_candidate_users(conn: sqlite3.Connection, users: list[str]) -> None:
    if not users:
        return
    conn.executemany(
        'INSERT OR IGNORE INTO candidate_user(user) VALUES (?)',
        [(user,) for user in users],
    )
    conn.commit()


def _insert_candidate_resources(conn: sqlite3.Connection, resources: list[tuple[str, str]]) -> None:
    if not resources:
        return
    conn.executemany(
        'INSERT OR IGNORE INTO candidate_resource(object_type, resource_id) VALUES (?, ?)',
        resources,
    )
    conn.commit()


def _count_table(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])


async def _candidate_user_ids() -> set[int]:
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.database.constants import AdminRole
    from bisheng.user.domain.models.user import User
    from sqlalchemy import select

    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            result = await _session_exec(
                session,
                sa_text('SELECT DISTINCT user_id FROM userrole WHERE role_id != :admin_rid'),
                {'admin_rid': AdminRole},
            )
            user_ids = {int(row[0]) for row in result.fetchall()}
            try:
                # SQLAlchemy expression so ``user`` and ``delete`` are auto-quoted
                # per dialect (MySQL backticks; DM8 / standard double quotes).
                users = await _session_exec(
                    session,
                    select(User.user_id).where(User.delete == 0),
                )
                user_ids.update(int(row[0]) for row in users.fetchall())
            except Exception as e:
                logger.warning(f'Failed to load all active users for stale tuple scan: {e}')
            return user_ids


async def _build_source_snapshot() -> SourcePermissionSnapshot:
    """Return raw and expanded role_access permission data from MySQL."""
    from bisheng.core.database import get_async_db_session
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.database.constants import AdminRole

    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            ra_result = await _session_exec(
                session,
                sa_text('SELECT role_id, third_id, type FROM roleaccess '
                        'WHERE type != 99 AND role_id != :admin_rid'),
                {'admin_rid': AdminRole},
            )
            role_accesses = ra_result.fetchall()

            ur_result = await _session_exec(
                session,
                sa_text('SELECT user_id, role_id FROM userrole WHERE role_id != :admin_rid'),
                {'admin_rid': AdminRole},
            )
            user_roles = ur_result.fetchall()

    role_user_map: dict[int, list[int]] = {}
    for uid, rid in user_roles:
        role_user_map.setdefault(rid, []).append(uid)

    desired: set[tuple[str, str, str, str]] = set()
    expanded_permissions = 0
    for role_id, third_id, access_type in role_accesses:
        mapping = ACCESS_TYPE_MAPPING.get(access_type)
        if not mapping:
            continue
        obj_type, relation = mapping
        for uid in role_user_map.get(role_id, []):
            desired.add((f'user:{uid}', relation, obj_type, str(third_id)))
            legacy = KNOWLEDGE_LEGACY_TYPES.get(obj_type)
            if legacy:
                desired.add((f'user:{uid}', relation, legacy, str(third_id)))
                expanded_permissions += 1
            expanded_permissions += 1
    return SourcePermissionSnapshot(
        role_access_rows=len(role_accesses),
        expanded_permissions=expanded_permissions,
        desired=desired,
    )


async def _build_desired_set() -> set[tuple[str, str, str, str]]:
    """Return {(user, relation, object_type, resource_id)} from MySQL."""
    return (await _build_source_snapshot()).desired


async def _populate_candidate_users(
    conn: sqlite3.Connection,
    batch_size: int,
    progress: bool | None = None,
) -> None:
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.database.constants import AdminRole

    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            async for rows in iter_keyset_batches(
                session,
                lambda last_id: (
                    sa_text('SELECT id, user_id FROM userrole '
                            'WHERE role_id != :admin_rid AND id > :last_id '
                            'ORDER BY id LIMIT :limit'),
                    {'admin_rid': AdminRole, 'last_id': last_id},
                ),
                batch_size=batch_size,
                progress=progress,
                progress_desc='candidate userrole',
            ):
                _insert_candidate_users(conn, [f'user:{row[1]}' for row in rows])
            try:
                from bisheng.user.domain.models.user import User
                from sqlalchemy import bindparam, select

                async for rows in iter_keyset_batches(
                    session,
                    lambda last_id: (
                        # SQLAlchemy expression so ``user`` / ``delete`` are
                        # auto-quoted per dialect; raw `\`delete\`` is rejected
                        # by DM8.
                        select(User.user_id, User.user_id)
                        .where(User.delete == 0, User.user_id > bindparam('last_id'))
                        .order_by(User.user_id)
                        .limit(bindparam('limit')),
                        {'last_id': last_id},
                    ),
                    batch_size=batch_size,
                    progress=progress,
                    progress_desc='candidate users',
                ):
                    _insert_candidate_users(conn, [f'user:{row[1]}' for row in rows])
            except Exception as e:
                logger.warning(f'Failed to load all active users for stale tuple scan: {e}')


async def _populate_desired_workspace(
    conn: sqlite3.Connection,
    batch_size: int,
    progress: bool | None = None,
) -> tuple[int, int]:
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.database.constants import AdminRole

    source_rows = 0
    expanded = 0
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
                batch_size=batch_size,
                progress=progress,
                progress_desc='desired roleaccess',
            ):
                source_rows += len(role_accesses)
                for _, role_id, third_id, access_type in role_accesses:
                    mapping = ACCESS_TYPE_MAPPING.get(access_type)
                    if not mapping:
                        continue
                    obj_type, relation = mapping
                    object_types = [obj_type]
                    legacy = KNOWLEDGE_LEGACY_TYPES.get(obj_type)
                    if legacy:
                        object_types.append(legacy)

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
                        batch_size=batch_size,
                        progress=progress,
                        progress_desc=f'desired userrole role={role_id}',
                    ):
                        tuples = [
                            (f'user:{row[1]}', relation, target_type, str(third_id))
                            for row in user_rows
                            for target_type in object_types
                        ]
                        expanded += len(tuples)
                        _insert_tuples(conn, 'desired_tuple', tuples)
                        _insert_candidate_resources(
                            conn,
                            [(target_type, str(third_id)) for target_type in object_types],
                        )
    return source_rows, expanded


async def _populate_candidate_resources(
    conn: sqlite3.Connection,
    batch_size: int,
    progress: bool | None = None,
) -> None:
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session

    resource_queries = [
        (
            'SELECT id, id FROM knowledge WHERE id > :last_id ORDER BY id LIMIT :limit',
            ('knowledge_library', 'knowledge_space'),
            0,
        ),
        (
            'SELECT id, id FROM t_gpts_tools '
            'WHERE is_delete = 0 AND id > :last_id ORDER BY id LIMIT :limit',
            ('tool',),
            0,
        ),
        (
            'SELECT id, id FROM dashboard WHERE id > :last_id ORDER BY id LIMIT :limit',
            ('dashboard',),
            0,
        ),
        (
            'SELECT id, id FROM flow WHERE flow_type IN (5, 10) '
            'AND id > :last_id ORDER BY id LIMIT :limit',
            ('flow',),
            '',
        ),
    ]
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            for query, object_types, start_cursor in resource_queries:
                try:
                    async for rows in iter_keyset_batches(
                        session,
                        lambda last_id, query=query: (
                            sa_text(query),
                            {'last_id': last_id},
                        ),
                        batch_size=batch_size,
                        start_cursor=start_cursor,
                        progress=progress,
                        progress_desc='candidate resources',
                    ):
                        resources: list[tuple[str, str]] = []
                        for _, resource_id in rows:
                            for object_type in object_types:
                                if object_type == 'flow':
                                    continue
                                resources.append((object_type, str(resource_id)))
                        _insert_candidate_resources(conn, resources)
                except Exception as e:
                    logger.warning(f'Failed to load candidate resources with query [{query}]: {e}')

            try:
                async for rows in iter_keyset_batches(
                    session,
                    lambda last_id: (
                        sa_text('SELECT id, id, flow_type FROM flow '
                                'WHERE flow_type IN (5, 10) AND id > :last_id '
                                'ORDER BY id LIMIT :limit'),
                        {'last_id': last_id},
                    ),
                    batch_size=batch_size,
                    start_cursor='',
                    progress=progress,
                    progress_desc='candidate flow resources',
                ):
                    resources = [
                        (FLOW_TYPE_MAPPING[flow_type], str(resource_id))
                        for _, resource_id, flow_type in rows
                        if flow_type in FLOW_TYPE_MAPPING
                    ]
                    _insert_candidate_resources(conn, resources)
            except Exception as e:
                logger.warning(f'Failed to load candidate flow resources: {e}')


async def _populate_actual_workspace(
    conn: sqlite3.Connection,
    batch_size: int,
    progress: bool | None = None,
) -> int:
    from bisheng.permission.domain.services.permission_service import PermissionService

    fga = PermissionService._get_fga()
    if fga is None:
        logger.error('FGAClient not available — cannot read actual tuples')
        return 0

    role_access_relations = {'viewer', 'editor'}
    failed = 0
    offset = 0
    total = _count_table(conn, 'candidate_resource')
    with ProgressTracker(
        enabled=progress,
        total=total,
        desc='FGA read resources',
        unit='resource',
    ) as bar:
        while True:
            rows = conn.execute(
                'SELECT object_type, resource_id FROM candidate_resource '
                'ORDER BY object_type, resource_id LIMIT ? OFFSET ?',
                (batch_size, offset),
            ).fetchall()
            if not rows:
                break
            offset += len(rows)
            for obj_type, resource_id in rows:
                object_filter = f'{obj_type}:{resource_id}'
                try:
                    tuples = await fga.read_tuples(object=object_filter)
                except Exception as e:
                    failed += 1
                    logger.warning(f'Failed to read tuples for {object_filter}: {e}')
                    bar.update()
                    continue
                actual_rows = []
                for item in tuples:
                    user = item.get('user', '')
                    obj = item.get('object', '')
                    relation = item.get('relation', '')
                    if not user.startswith('user:') or relation not in role_access_relations:
                        continue
                    if obj != object_filter:
                        continue
                    actual_rows.append((user, relation, obj_type, str(resource_id)))
                _insert_tuples(conn, 'actual_tuple', actual_rows)
                bar.update()
    return failed


async def _populate_space_channel_member_protected_workspace(
    conn: sqlite3.Connection,
    batch_size: int,
    progress: bool | None = None,
) -> None:
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session

    try:
        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                async for rows in iter_keyset_batches(
                    session,
                    lambda last_id: (
                        sa_text("SELECT id, business_id, business_type, user_id, user_role "
                                "FROM space_channel_member WHERE status = 'ACTIVE' "
                                "AND id > :last_id ORDER BY id LIMIT :limit"),
                        {'last_id': last_id},
                    ),
                    batch_size=batch_size,
                    progress=progress,
                    progress_desc='protected space_channel_member',
                ):
                    protected_rows = []
                    for _, business_id, business_type, user_id, user_role in rows:
                        relation = SCM_ROLE_MAPPING.get((user_role or '').lower())
                        object_type = SCM_TYPE_MAPPING.get((business_type or '').lower())
                        if not relation or not object_type:
                            continue
                        protected_rows.append((
                            f'user:{user_id}',
                            relation,
                            object_type,
                            str(business_id),
                        ))
                    _insert_tuples(conn, 'protected_tuple', protected_rows)
    except Exception as e:
        logger.warning(f'Failed to load space/channel member protected tuples: {e}')


async def _populate_protected_workspace(
    conn: sqlite3.Connection,
    batch_size: int,
    progress: bool | None = None,
) -> None:
    protected = await _resource_permission_user_binding_set()
    _insert_tuples(conn, 'protected_tuple', list(protected))
    await _populate_space_channel_member_protected_workspace(conn, batch_size, progress)


def _permission_to_dict(item: tuple[str, str, str, str]) -> dict:
    user, relation, obj_type, resource_id = item
    return {
        'user': user,
        'relation': relation,
        'object_type': obj_type,
        'resource_id': resource_id,
        'object': f'{obj_type}:{resource_id}',
    }


def _sorted_permissions(items: set[tuple[str, str, str, str]]) -> list[dict]:
    return [_permission_to_dict(item) for item in sorted(items)]


def _count_by_index(items: set[tuple[str, str, str, str]], index: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = item[index]
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _build_compare_report(
    *,
    source: SourcePermissionSnapshot,
    actual: set[tuple[str, str, str, str]],
    to_write: set[tuple[str, str, str, str]],
    to_delete: set[tuple[str, str, str, str]],
    protected: set[tuple[str, str, str, str]],
) -> dict:
    desired = source.desired
    actual_only = actual - desired
    return {
        'generated_at': datetime.now().isoformat(),
        'title_zh': 'role_access 与 OpenFGA 权限差异 dry-run 对比报告',
        'field_notes_zh': SUMMARY_FIELD_NOTES_ZH,
        'summary': {
            'source_role_access_rows': source.role_access_rows,
            'source_expanded_permissions': source.expanded_permissions,
            'source_unique_permissions': len(desired),
            'actual_fga_permissions': len(actual),
            'planned_writes': len(to_write),
            'planned_deletes': len(to_delete),
            'protected_permissions': len(protected),
            'actual_only_permissions': len(actual_only),
        },
        'aggregates': {
            'source_desired': {
                'by_object_type': _count_by_index(desired, 2),
                'by_relation': _count_by_index(desired, 1),
                'by_user': _count_by_index(desired, 0),
            },
            'actual_fga': {
                'by_object_type': _count_by_index(actual, 2),
                'by_relation': _count_by_index(actual, 1),
                'by_user': _count_by_index(actual, 0),
            },
            'planned_writes': {
                'by_object_type': _count_by_index(to_write, 2),
                'by_relation': _count_by_index(to_write, 1),
                'by_user': _count_by_index(to_write, 0),
            },
            'planned_deletes': {
                'by_object_type': _count_by_index(to_delete, 2),
                'by_relation': _count_by_index(to_delete, 1),
                'by_user': _count_by_index(to_delete, 0),
            },
        },
        'details': {
            'source_desired': _sorted_permissions(desired),
            'actual_fga': _sorted_permissions(actual),
            'planned_writes': _sorted_permissions(to_write),
            'planned_deletes': _sorted_permissions(to_delete),
            'protected': _sorted_permissions(protected),
            'actual_only': _sorted_permissions(actual_only),
        },
    }


def _write_report(report: dict, report_path: str) -> None:
    path = Path(report_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def _log_dry_run_summary(report: dict) -> None:
    summary = report['summary']
    lines = [
        '',
        '=== role_access 与 OpenFGA 权限差异 dry-run 对比报告 ===',
        f"原始 role_access 记录数:      {summary['source_role_access_rows']}",
        f"原始表展开权限数量:          {summary['source_expanded_permissions']}",
        f"原始表唯一权限数量:          {summary['source_unique_permissions']}",
        f"当前 OpenFGA 权限数量:       {summary['actual_fga_permissions']}",
        f"预写入 OpenFGA 权限数量:     {summary['planned_writes']}",
        f"预删除 OpenFGA 权限数量:     {summary['planned_deletes']}",
        f"受保护不删除权限数量:        {summary['protected_permissions']}",
        f"OpenFGA 独有权限数量:        {summary['actual_only_permissions']}",
    ]
    if 'fga_read_failures' in summary:
        lines.append(f"OpenFGA 读取失败资源数量:    {summary['fga_read_failures']}")
    lines.extend([
        '',
        '字段说明:',
        f"- 原始表唯一权限数量: {SUMMARY_FIELD_NOTES_ZH['source_unique_permissions']}",
        f"- 预写入 OpenFGA 权限数量: {SUMMARY_FIELD_NOTES_ZH['planned_writes']}",
        f"- 受保护不删除权限数量: {SUMMARY_FIELD_NOTES_ZH['protected_permissions']}",
        f"- OpenFGA 独有权限数量: {SUMMARY_FIELD_NOTES_ZH['actual_only_permissions']}",
    ])
    logger.info('\n'.join(lines))


def _compute_workspace_diff(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DELETE FROM diff_tuple;
        INSERT OR IGNORE INTO diff_tuple(action, user, relation, object_type, resource_id)
        SELECT 'write', d.user, d.relation, d.object_type, d.resource_id
        FROM desired_tuple d
        LEFT JOIN actual_tuple a
          ON a.user = d.user
         AND a.relation = d.relation
         AND a.object_type = d.object_type
         AND a.resource_id = d.resource_id
        WHERE a.user IS NULL;

        INSERT OR IGNORE INTO diff_tuple(action, user, relation, object_type, resource_id)
        SELECT 'actual_only', a.user, a.relation, a.object_type, a.resource_id
        FROM actual_tuple a
        JOIN candidate_user u ON u.user = a.user
        LEFT JOIN desired_tuple d
          ON d.user = a.user
         AND d.relation = a.relation
         AND d.object_type = a.object_type
         AND d.resource_id = a.resource_id
        WHERE d.user IS NULL;

        INSERT OR IGNORE INTO diff_tuple(action, user, relation, object_type, resource_id)
        SELECT 'protected', a.user, a.relation, a.object_type, a.resource_id
        FROM actual_tuple a
        JOIN candidate_user u ON u.user = a.user
        JOIN protected_tuple p
          ON p.user = a.user
         AND p.relation = a.relation
         AND p.object_type = a.object_type
         AND p.resource_id = a.resource_id
        LEFT JOIN desired_tuple d
          ON d.user = a.user
         AND d.relation = a.relation
         AND d.object_type = a.object_type
         AND d.resource_id = a.resource_id
        WHERE d.user IS NULL;

        INSERT OR IGNORE INTO diff_tuple(action, user, relation, object_type, resource_id)
        SELECT 'delete', a.user, a.relation, a.object_type, a.resource_id
        FROM actual_tuple a
        JOIN candidate_user u ON u.user = a.user
        LEFT JOIN desired_tuple d
          ON d.user = a.user
         AND d.relation = a.relation
         AND d.object_type = a.object_type
         AND d.resource_id = a.resource_id
        LEFT JOIN protected_tuple p
          ON p.user = a.user
         AND p.relation = a.relation
         AND p.object_type = a.object_type
         AND p.resource_id = a.resource_id
        WHERE d.user IS NULL
          AND p.user IS NULL;
        """
    )
    conn.commit()


def _workspace_summary(
    conn: sqlite3.Connection,
    *,
    source_role_access_rows: int,
    source_expanded_permissions: int,
    fga_read_failures: int,
) -> dict:
    counts = {
        'source_role_access_rows': source_role_access_rows,
        'source_expanded_permissions': source_expanded_permissions,
        'source_unique_permissions': _count_table(conn, 'desired_tuple'),
        'actual_fga_permissions': _count_table(conn, 'actual_tuple'),
        'planned_writes': int(conn.execute(
            "SELECT COUNT(*) FROM diff_tuple WHERE action = 'write'"
        ).fetchone()[0]),
        'planned_deletes': int(conn.execute(
            "SELECT COUNT(*) FROM diff_tuple WHERE action = 'delete'"
        ).fetchone()[0]),
        'protected_permissions': int(conn.execute(
            "SELECT COUNT(*) FROM diff_tuple WHERE action = 'protected'"
        ).fetchone()[0]),
        'actual_only_permissions': int(conn.execute(
            "SELECT COUNT(*) FROM diff_tuple WHERE action = 'actual_only'"
        ).fetchone()[0]),
        'fga_read_failures': fga_read_failures,
    }
    return {
        'generated_at': datetime.now().isoformat(),
        'title_zh': 'role_access 与 OpenFGA 权限差异 dry-run 对比报告',
        'field_notes_zh': SUMMARY_FIELD_NOTES_ZH,
        'detail_file_notes_zh': DETAIL_FILE_NOTES_ZH,
        'summary': counts,
    }


def _workspace_aggregates(conn: sqlite3.Connection) -> dict:
    aggregates: dict[str, dict] = {
        '说明': '按 action 维度统计权限差异，write 表示预写入，delete 表示预删除，protected 表示受保护不删除，actual_only 表示 OpenFGA 独有。',
        'by_object_type': {},
        'by_relation': {},
    }
    for action, object_type, count in conn.execute(
        'SELECT action, object_type, COUNT(*) FROM diff_tuple GROUP BY action, object_type'
    ):
        aggregates['by_object_type'].setdefault(action, {})[object_type] = count
    for action, relation, count in conn.execute(
        'SELECT action, relation, COUNT(*) FROM diff_tuple GROUP BY action, relation'
    ):
        aggregates['by_relation'].setdefault(action, {})[relation] = count
    return aggregates


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _iter_diff_rows(conn: sqlite3.Connection, action: str, batch_size: int):
    offset = 0
    while True:
        rows = conn.execute(
            'SELECT user, relation, object_type, resource_id FROM diff_tuple '
            'WHERE action = ? ORDER BY user, relation, object_type, resource_id '
            'LIMIT ? OFFSET ?',
            (action, batch_size, offset),
        ).fetchall()
        if not rows:
            break
        offset += len(rows)
        for row in rows:
            yield row


def _export_workspace_report(
    conn: sqlite3.Connection,
    report_dir: str,
    batch_size: int,
    summary: dict,
    progress: bool | None = None,
) -> None:
    path = Path(report_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    _write_json(path / 'summary.json', summary)
    _write_json(path / 'aggregates.json', _workspace_aggregates(conn))
    file_map = {
        'write': 'planned_writes.jsonl',
        'delete': 'planned_deletes.jsonl',
        'protected': 'protected.jsonl',
        'actual_only': 'actual_only.jsonl',
    }
    for action, filename in file_map.items():
        total = int(conn.execute(
            'SELECT COUNT(*) FROM diff_tuple WHERE action = ?',
            (action,),
        ).fetchone()[0])
        with (path / filename).open('w', encoding='utf-8') as file:
            with ProgressTracker(
                enabled=progress,
                total=total,
                desc=f'export {filename}',
                unit='row',
            ) as bar:
                for row in _iter_diff_rows(conn, action, batch_size):
                    file.write(json.dumps(_permission_to_dict(row), ensure_ascii=False) + '\n')
                    bar.update()


def _all_role_access_object_types() -> set[str]:
    all_types = set(RESOURCE_TYPES_WITH_FGA)
    for obj_type in RESOURCE_TYPES_WITH_FGA:
        legacy = KNOWLEDGE_LEGACY_TYPES.get(obj_type)
        if legacy:
            all_types.add(legacy)
    return all_types


async def _candidate_resource_objects(
    desired: set[tuple[str, str, str, str]],
) -> set[tuple[str, str]]:
    """Return resource objects whose direct user grants should be reconciled."""
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session

    objects = {(obj_type, resource_id) for _, _, obj_type, resource_id in desired}

    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            for query, object_types in [
                ('SELECT id FROM knowledge', ('knowledge_library', 'knowledge_space')),
                ('SELECT id FROM t_gpts_tools WHERE is_delete = 0', ('tool',)),
                ('SELECT id FROM dashboard', ('dashboard',)),
            ]:
                try:
                    result = await _session_exec(session, sa_text(query))
                    for row in result.fetchall():
                        for object_type in object_types:
                            objects.add((object_type, str(row[0])))
                except Exception as e:
                    logger.warning(f'Failed to load candidate resources with query [{query}]: {e}')

            try:
                result = await _session_exec(
                    session,
                    sa_text('SELECT id, flow_type FROM flow WHERE flow_type IN (5, 10)'),
                )
                for resource_id, flow_type in result.fetchall():
                    object_type = FLOW_TYPE_MAPPING.get(flow_type)
                    if object_type:
                        objects.add((object_type, str(resource_id)))
            except Exception as e:
                logger.warning(f'Failed to load candidate flow resources: {e}')

    return objects


async def _build_actual_set(
    user_ids: set[int],
    resource_objects: set[tuple[str, str]],
) -> set[tuple[str, str, str, str]]:
    """Return {(user, relation, object_type, resource_id)} from FGA.

    Only considers current role users, not every OpenFGA tuple in the store.
    Only considers viewer/editor relations (the ones managed by role_access).
    """
    from bisheng.permission.domain.services.permission_service import PermissionService

    fga = PermissionService._get_fga()
    if fga is None:
        logger.error('FGAClient not available — cannot read actual tuples')
        return set()

    role_access_relations = {'viewer', 'editor'}
    user_filters = {f'user:{uid}' for uid in user_ids}
    actual: set[tuple[str, str, str, str]] = set()

    for obj_type, resource_id in sorted(resource_objects):
        object_filter = f'{obj_type}:{resource_id}'
        try:
            tuples = await fga.read_tuples(object=object_filter)
        except Exception as e:
            logger.warning(f'Failed to read tuples for {object_filter}: {e}')
            continue
        for t in tuples:
            user = t.get('user', '')
            obj = t.get('object', '')
            rel = t.get('relation', '')
            if user not in user_filters or rel not in role_access_relations:
                continue
            parts = obj.split(':', 1)
            if len(parts) != 2:
                continue
            t_type, t_id = parts
            if obj == object_filter:
                actual.add((user, rel, t_type, t_id))
    return actual


async def _resource_permission_user_binding_set() -> set[tuple[str, str, str, str]]:
    """Return FGA tuple signatures backed by resource permission user bindings."""
    from bisheng.common.models.config import ConfigDao

    all_types = _all_role_access_object_types()
    bound: set[tuple[str, str, str, str]] = set()
    row = await ConfigDao.aget_config_by_key('permission_relation_model_bindings_v1')
    if not row or not (row.value or '').strip():
        return bound
    try:
        bindings = json.loads(row.value or '[]')
    except Exception:
        logger.warning('Failed to parse resource permission bindings config')
        return bound
    if not isinstance(bindings, list):
        return bound

    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        resource_type = binding.get('resource_type')
        if resource_type not in all_types:
            continue
        if binding.get('subject_type') != 'user':
            continue
        relation = binding.get('relation')
        if relation not in {'viewer', 'editor'}:
            continue
        resource_id = str(binding.get('resource_id'))
        subject_id = binding.get('subject_id')
        if subject_id is None:
            continue
        bound.add((f'user:{subject_id}', relation, resource_type, resource_id))
        legacy = KNOWLEDGE_LEGACY_TYPES.get(resource_type)
        if legacy:
            bound.add((f'user:{subject_id}', relation, legacy, resource_id))
        if resource_type == 'knowledge_space':
            bound.add((f'user:{subject_id}', relation, 'knowledge_library', resource_id))
    return bound


async def _reconcile_with_workspace(
    *,
    dry_run: bool,
    batch_size: int,
    report_path: str | None = None,
    report_dir: str | None = None,
    workspace_path: str | None = None,
    keep_workspace: bool = False,
    progress: bool | None = None,
) -> Stats:
    from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
    from bisheng.permission.domain.services.permission_service import PermissionService
    from bisheng.permission.domain.services.permission_cache import PermissionCache

    if batch_size <= 0:
        raise ValueError(f'batch_size must be greater than 0, got {batch_size}')

    created_workspace = workspace_path is None
    if workspace_path is None:
        fd, workspace_path = tempfile.mkstemp(prefix='bisheng-role-access-reconcile-', suffix='.sqlite3')
        os.close(fd)

    stats = Stats()
    conn = _create_workspace(workspace_path)
    try:
        logger.info(f'Using reconcile workspace: {workspace_path}')
        logger.info('Building desired tuples from MySQL role_access ...')
        source_rows, expanded = await _populate_desired_workspace(conn, batch_size, progress)
        stats.source_role_access_rows = source_rows
        stats.source_expanded_permissions = expanded
        stats.source_unique_permissions = _count_table(conn, 'desired_tuple')
        stats.desired = stats.source_unique_permissions

        logger.info('Building candidate users/resources ...')
        await _populate_candidate_users(conn, batch_size, progress)
        await _populate_candidate_resources(conn, batch_size, progress)

        logger.info('Building actual tuples from FGA ...')
        fga_read_failures = await _populate_actual_workspace(conn, batch_size, progress)

        logger.info('Building protected tuples from explicit resource bindings and space/channel members ...')
        await _populate_protected_workspace(conn, batch_size, progress)

        logger.info('Computing tuple diffs in SQLite ...')
        with ProgressTracker(enabled=progress, total=1, desc='SQLite diff', unit='step') as bar:
            _compute_workspace_diff(conn)
            bar.update()
        summary = _workspace_summary(
            conn,
            source_role_access_rows=source_rows,
            source_expanded_permissions=expanded,
            fga_read_failures=fga_read_failures,
        )
        counts = summary['summary']
        stats.actual = counts['actual_fga_permissions']
        stats.to_write = counts['planned_writes']
        stats.to_delete = counts['planned_deletes']
        stats.protected = counts['protected_permissions']

        if dry_run:
            _log_dry_run_summary(summary)
            if report_path:
                _write_json(Path(report_path).expanduser(), summary)
                logger.info(f'Dry-run summary report written to: {report_path}')
            if report_dir:
                _export_workspace_report(conn, report_dir, batch_size, summary, progress)
                logger.info(f'Dry-run JSONL compare report written to: {report_dir}')
            return stats

        operations: list[TupleOperation] = []
        affected_user_ids: set[int] = set()
        for action in ('write', 'delete'):
            fga_action = 'delete' if action == 'delete' else 'write'
            total = int(conn.execute(
                'SELECT COUNT(*) FROM diff_tuple WHERE action = ?',
                (action,),
            ).fetchone()[0])
            with ProgressTracker(
                enabled=progress,
                total=total,
                desc=f'FGA {fga_action}',
                unit='tuple',
            ) as bar:
                for user, relation, obj_type, resource_id in _iter_diff_rows(conn, action, batch_size):
                    operations.append(TupleOperation(
                        action=fga_action,
                        user=user,
                        relation=relation,
                        object=f'{obj_type}:{resource_id}',
                    ))
                    affected_user_ids.add(int(user.split(':', 1)[1]))
                    if len(operations) >= batch_size:
                        await PermissionService.batch_write_tuples(operations, crash_safe=True)
                        bar.update(len(operations))
                        operations.clear()
                if operations:
                    await PermissionService.batch_write_tuples(operations, crash_safe=True)
                    bar.update(len(operations))
                    operations.clear()

        stats.written = stats.to_write
        stats.deleted = stats.to_delete
        if affected_user_ids:
            logger.info(f'Invalidating cache for {len(affected_user_ids)} users ...')
            for uid in affected_user_ids:
                await PermissionCache.invalidate_user(uid)
        return stats
    finally:
        conn.close()
        if not keep_workspace and workspace_path:
            try:
                os.remove(workspace_path)
            except OSError:
                pass
            for suffix in ('-wal', '-shm'):
                try:
                    os.remove(workspace_path + suffix)
                except OSError:
                    pass
        elif keep_workspace or not created_workspace:
            logger.warning(f'Reconcile workspace retained; it may contain sensitive permission data: {workspace_path}')


async def reconcile(
    dry_run: bool = False,
    report_path: str | None = None,
    report_dir: str | None = None,
    workspace_path: str | None = None,
    keep_workspace: bool = False,
    batch_size: int = 1000,
    progress: bool | None = None,
) -> Stats:
    return await _reconcile_with_workspace(
        dry_run=dry_run,
        batch_size=batch_size,
        report_path=report_path,
        report_dir=report_dir,
        workspace_path=workspace_path,
        keep_workspace=keep_workspace,
        progress=progress,
    )


async def _legacy_reconcile_in_memory(dry_run: bool = False, report_path: str | None = None) -> Stats:
    from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
    from bisheng.permission.domain.services.permission_service import PermissionService
    from bisheng.permission.domain.services.permission_cache import PermissionCache

    # Kept for small-data debugging and historical reference. The public
    # ``reconcile`` entry point uses the SQLite workspace implementation above.
    stats = Stats()

    logger.info('Building desired set from MySQL role_access ...')
    source = await _build_source_snapshot()
    desired = source.desired
    stats.source_role_access_rows = source.role_access_rows
    stats.source_expanded_permissions = source.expanded_permissions
    stats.source_unique_permissions = len(desired)
    stats.desired = len(desired)
    logger.info(
        f'Source role_access rows: {stats.source_role_access_rows}, '
        f'expanded permissions: {stats.source_expanded_permissions}, '
        f'unique desired tuples: {stats.desired}'
    )

    role_user_ids = await _candidate_user_ids()
    logger.info(f'Candidate users for role_access FGA scan: {len(role_user_ids)}')

    resource_objects = await _candidate_resource_objects(desired)
    logger.info(f'Candidate resources for role_access FGA scan: {len(resource_objects)}')

    logger.info('Building actual set from FGA ...')
    actual = await _build_actual_set(role_user_ids, resource_objects)
    stats.actual = len(actual)
    logger.info(f'Actual tuples: {stats.actual}')

    protected = await _resource_permission_user_binding_set()
    to_write = desired - actual
    stale = actual - desired
    to_delete = stale - protected
    stats.to_write = len(to_write)
    stats.to_delete = len(to_delete)
    stats.protected = len(stale & protected)

    logger.info(
        f'To write: {stats.to_write}, to delete: {stats.to_delete}, '
        f'protected by explicit bindings: {stats.protected}'
    )

    if dry_run:
        protected_stale = stale & protected
        report = _build_compare_report(
            source=source,
            actual=actual,
            to_write=to_write,
            to_delete=to_delete,
            protected=protected_stale,
        )
        _log_dry_run_summary(report)
        if report_path:
            _write_report(report, report_path)
            logger.info(f'Dry-run compare report written to: {report_path}')
        if to_delete:
            logger.info('Sample deletes (first 20):')
            for item in list(to_delete)[:20]:
                logger.info(f'  DELETE {item}')
        if to_write:
            logger.info('Sample writes (first 20):')
            for item in list(to_write)[:20]:
                logger.info(f'  WRITE  {item}')
        return stats

    operations: list[TupleOperation] = []
    affected_user_ids: set[int] = set()

    for user, relation, obj_type, resource_id in to_delete:
        operations.append(TupleOperation(
            action='delete', user=user,
            relation=relation, object=f'{obj_type}:{resource_id}',
        ))
        uid = user.split(':')[1]
        affected_user_ids.add(int(uid))

    for user, relation, obj_type, resource_id in to_write:
        operations.append(TupleOperation(
            action='write', user=user,
            relation=relation, object=f'{obj_type}:{resource_id}',
        ))
        uid = user.split(':')[1]
        affected_user_ids.add(int(uid))

    if operations:
        logger.info(f'Executing {len(operations)} FGA operations ...')
        await PermissionService.batch_write_tuples(operations, crash_safe=True)
        stats.written = stats.to_write
        stats.deleted = stats.to_delete

    if affected_user_ids:
        logger.info(f'Invalidating cache for {len(affected_user_ids)} users ...')
        for uid in affected_user_ids:
            await PermissionCache.invalidate_user(uid)

    return stats


async def _main(
    dry_run: bool,
    report_path: str | None = None,
    report_dir: str | None = None,
    workspace_path: str | None = None,
    keep_workspace: bool = False,
    batch_size: int = 1000,
    progress: bool | None = None,
) -> None:
    from bisheng.common.services.config_service import settings
    from bisheng.core.context import close_app_context, initialize_app_context

    await initialize_app_context(config=settings)

    try:
        t0 = time.time()
        stats = await reconcile(
            dry_run=dry_run,
            report_path=report_path,
            report_dir=report_dir,
            workspace_path=workspace_path,
            keep_workspace=keep_workspace,
            batch_size=batch_size,
            progress=progress,
        )
        elapsed = time.time() - t0

        logger.info(
            f"Reconcile {'DRY-RUN' if dry_run else 'DONE'} in {elapsed:.1f}s — "
            f'source_rows={stats.source_role_access_rows} '
            f'source_expanded={stats.source_expanded_permissions} '
            f'source_unique={stats.source_unique_permissions} '
            f'actual={stats.actual} write={stats.to_write} delete={stats.to_delete} '
            f'protected={stats.protected}'
        )
    finally:
        await close_app_context()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Reconcile role_access ↔ FGA tuples')
    parser.add_argument('--dry-run', action='store_true', help='Preview only, no writes')
    parser.add_argument(
        '--report',
        help='Write a JSON summary report; only valid with --dry-run',
    )
    parser.add_argument(
        '--report-dir',
        help='Write detailed JSONL compare report files; only valid with --dry-run',
    )
    parser.add_argument(
        '--workspace',
        help='SQLite workspace path. Deleted after run unless --keep-workspace is set.',
    )
    parser.add_argument(
        '--keep-workspace',
        action='store_true',
        help='Keep SQLite workspace after run. It may contain sensitive permission data.',
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        metavar='N',
        help='Database/FGA/report batch size (default: 1000)',
    )
    progress_group = parser.add_mutually_exclusive_group()
    progress_group.add_argument(
        '--progress',
        action='store_true',
        default=None,
        help='Force progress bars on',
    )
    progress_group.add_argument(
        '--no-progress',
        action='store_false',
        dest='progress',
        help='Force progress bars off',
    )
    args = parser.parse_args()
    if (args.report or args.report_dir) and not args.dry_run:
        parser.error('--report and --report-dir can only be used with --dry-run')
    asyncio.run(_main(
        dry_run=args.dry_run,
        report_path=args.report,
        report_dir=args.report_dir,
        workspace_path=args.workspace,
        keep_workspace=args.keep_workspace,
        batch_size=args.batch_size,
        progress=args.progress,
    ))
