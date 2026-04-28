"""Batch helpers for permission migration scripts."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from typing import Any


def resolve_progress_enabled(progress: bool | None) -> bool:
    if progress is not None:
        return progress
    return bool(sys.stderr.isatty())


class ProgressTracker:
    """Small optional tqdm wrapper that degrades to no-op when unavailable."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        total: int | None = None,
        desc: str = '',
        unit: str = 'it',
    ) -> None:
        self.enabled = resolve_progress_enabled(enabled)
        self._bar = None
        if not self.enabled:
            return
        try:
            from tqdm import tqdm
        except Exception:
            return
        self._bar = tqdm(total=total, desc=desc, unit=unit)

    def update(self, n: int = 1) -> None:
        if self._bar is not None:
            self._bar.update(n)

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()
            self._bar = None

    def __enter__(self) -> 'ProgressTracker':
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


async def session_exec(session, statement, params: dict | None = None):
    if hasattr(session, 'exec'):
        if params is None:
            return await session.exec(statement)
        return await session.exec(statement, params=params)
    if params is None:
        return await session.execute(statement)
    return await session.execute(statement, params)


async def iter_keyset_batches(
    session,
    statement_factory,
    *,
    batch_size: int,
    start_cursor: Any = 0,
    progress: bool | None = None,
    progress_desc: str = '',
    progress_unit: str = 'row',
) -> AsyncIterator[list]:
    """Yield rows from keyset-paginated SQL.

    ``statement_factory`` receives ``last_cursor`` and must return
    ``(statement, params)``. The first selected column must be the cursor.
    """
    if batch_size <= 0:
        raise ValueError(f'batch_size must be greater than 0, got {batch_size}')
    last_cursor = start_cursor
    with ProgressTracker(enabled=progress, desc=progress_desc, unit=progress_unit) as bar:
        while True:
            statement, params = statement_factory(last_cursor)
            params = dict(params or {})
            params['limit'] = batch_size
            result = await session_exec(session, statement, params)
            rows = result.fetchall()
            if not rows:
                break
            bar.update(len(rows))
            yield rows
            last_cursor = rows[-1][0]
            if len(rows) < batch_size:
                break


def batched(items: Iterable, batch_size: int) -> Iterable[list]:
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


@dataclass
class DedupDecision:
    accepted: bool
    existing_relation: str = ''


class TupleDeduplicator:
    """Track highest-priority relation for each (user, object).

    The default in-memory backend preserves the historical ``_global_seen``
    inspection surface. The SQLite backend avoids holding the full keyspace in
    Python memory for large migrations.
    """

    def __init__(
        self,
        relation_priority: dict[str, int],
        *,
        backend: str = 'memory',
        db_path: str | None = None,
    ) -> None:
        if backend not in {'memory', 'sqlite'}:
            raise ValueError("dedup backend must be 'memory' or 'sqlite'")
        self.relation_priority = relation_priority
        self.backend = backend
        self.db_path = db_path
        self.memory: dict[tuple[str, str], str] = {}
        self._conn: sqlite3.Connection | None = None
        self._owns_db_path = False
        if backend == 'sqlite':
            if db_path:
                self.db_path = db_path
            else:
                fd, self.db_path = tempfile.mkstemp(
                    prefix='bisheng-f006-dedup-',
                    suffix='.sqlite3',
                )
                os.close(fd)
                self._owns_db_path = True
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute(
                'CREATE TABLE IF NOT EXISTS tuple_seen ('
                'user TEXT NOT NULL, '
                'object TEXT NOT NULL, '
                'relation TEXT NOT NULL, '
                'priority INTEGER NOT NULL, '
                'PRIMARY KEY (user, object))'
            )
            self._conn.commit()

    def record(self, user: str, object_: str, relation: str) -> DedupDecision:
        new_prio = self.relation_priority.get(relation, None)
        if new_prio is None:
            raise RuntimeError(f"relation {relation} not found in relation_priority")
        if self.backend == 'memory':
            existing_rel = self.memory.get((user, object_))
            if existing_rel is None:
                self.memory[(user, object_)] = relation
                return DedupDecision(True, '')
            existing_prio = self.relation_priority.get(existing_rel)
            if new_prio >= existing_prio:
                self.memory[(user, object_)] = relation
                return DedupDecision(True, existing_rel)
            return DedupDecision(False, existing_rel)

        assert self._conn is not None
        row = self._conn.execute(
            'SELECT relation, priority FROM tuple_seen WHERE user = ? AND object = ?',
            (user, object_),
        ).fetchone()
        existing_rel = row[0] if row else ''
        existing_prio = int(row[1]) if row else 0
        if new_prio >= existing_prio:
            self._conn.execute(
                'INSERT INTO tuple_seen(user, object, relation, priority) VALUES (?, ?, ?, ?) '
                'ON CONFLICT(user, object) DO UPDATE SET relation = excluded.relation, '
                'priority = excluded.priority',
                (user, object_, relation, new_prio),
            )
            self._conn.commit()
            return DedupDecision(True, existing_rel)
        return DedupDecision(False, existing_rel)

    def iter_seen(self) -> Iterable[tuple[tuple[str, str], str]]:
        if self.backend == 'memory':
            yield from self.memory.items()
            return
        assert self._conn is not None
        for user, object_, relation in self._conn.execute(
            'SELECT user, object, relation FROM tuple_seen'
        ):
            yield (user, object_), relation

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        if self._owns_db_path and self.db_path:
            for suffix in ('', '-wal', '-shm'):
                try:
                    os.remove(self.db_path + suffix)
                except OSError:
                    pass
