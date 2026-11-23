"""Private, disposable history snapshots; never a durable migration authority.

The owning maintenance command still freezes the original JSON plan and hashes.
SQLite only bounds temporary row storage and indexes while all writers are stopped.
No business database, object store or permission data is written here.
Imported by ``python scripts/prepare_f118_history.py --plan /secure/history.json``
from src/backend; this helper is not a standalone maintenance command.
"""

import json
import os
import sqlite3
from collections.abc import Mapping
from contextlib import ExitStack
from contextvars import ContextVar
from functools import wraps
from tempfile import TemporaryDirectory

_owners = ContextVar("f118_history_scratch_owners", default=None)


def snapshot_scope(function):
    @wraps(function)
    async def owned(*args, **kwargs):
        with ExitStack() as stack:
            token = _owners.set(stack)
            try:
                return await function(*args, **kwargs)
            finally:
                _owners.reset(token)

    return owned


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class SnapshotRows:
    def __init__(self, store, name, changes=None, removed=frozenset()):
        self.store, self.name = store, name
        self.changes, self.removed = changes or {}, removed

    def __iter__(self):
        cursor = self.store.database.execute(
            "SELECT payload FROM records WHERE collection=? ORDER BY ordinal", (self.name,)
        )
        for (payload,) in cursor:
            row = json.loads(payload)
            if row["id"] not in self.removed:
                yield {**row, **self.changes.get(row["id"], {})}

    def overlay(self, changes, removed):
        return SnapshotRows(self.store, self.name, changes, frozenset(removed))

    def by_id(self):
        return _RowIndex(self)

    def grouped(self, fields):
        if self.changes or self.removed:
            raise ValueError("group indexes require an unchanged snapshot")
        spec = _encode(fields)
        identity = (self.name, spec)
        if identity not in self.store.indexes:
            rows = ((self.name, spec, _encode(_group_key(row, fields)), ordinal) for ordinal, row in enumerate(self))
            self.store.database.executemany("INSERT INTO lookups VALUES (?, ?, ?, ?)", rows)
            self.store.indexes.add(identity)
        return _GroupIndex(self, spec)


def _group_key(row, fields):
    return row[fields[0]] if len(fields) == 1 else tuple(row[field] for field in fields)


class _RowIndex(Mapping):
    def __init__(self, rows):
        self.rows = rows

    def __getitem__(self, ident):
        if ident not in self.rows.removed:
            value = self.rows.store.database.execute(
                "SELECT payload FROM records WHERE collection=? AND identity=?", (self.rows.name, _encode(ident))
            ).fetchone()
            if value is not None:
                return {**json.loads(value[0]), **self.rows.changes.get(ident, {})}
        raise KeyError(ident)

    def __iter__(self):
        cursor = self.rows.store.database.execute(
            "SELECT identity FROM records WHERE collection=? ORDER BY ordinal", (self.rows.name,)
        )
        for (identity,) in cursor:
            ident = json.loads(identity)
            if ident not in self.rows.removed:
                yield ident

    def __len__(self):
        return self.rows.store.counts[self.rows.name] - len(self.rows.removed)

    def values(self):
        return iter(self.rows)

    def items(self):
        return ((row["id"], row) for row in self.rows)


class _GroupIndex:
    def __init__(self, rows, spec):
        self.rows, self.spec = rows, spec

    def get(self, key, default=()):
        result = self.rows.store.database.execute(
            "SELECT r.payload FROM lookups AS l JOIN records AS r "
            "ON r.collection=l.collection AND r.ordinal=l.ordinal "
            "WHERE l.collection=? AND l.spec=? AND l.key=? ORDER BY l.ordinal",
            (self.rows.name, self.spec, _encode(key)),
        )
        values = [json.loads(row[0]) for row in result]
        return values or default

    def __getitem__(self, key):
        return self.get(key)

    def __contains__(self, key):
        return (
            self.rows.store.database.execute(
                "SELECT 1 FROM lookups WHERE collection=? AND spec=? AND key=? LIMIT 1",
                (self.rows.name, self.spec, _encode(key)),
            ).fetchone()
            is not None
        )


class SnapshotStore:
    def __init__(self):
        self.directory = TemporaryDirectory(prefix="f118-history-")
        self.database = None
        self.counts, self.indexes = {}, set()
        try:
            path = os.path.join(self.directory.name, "rows.sqlite")
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            self.database = sqlite3.connect(path)
            self.database.execute("PRAGMA cache_size=-4096")
            self.database.execute("PRAGMA temp_store=FILE")
            self.database.execute(
                "CREATE TABLE records (collection TEXT, ordinal INTEGER, identity TEXT, "
                "payload TEXT, PRIMARY KEY(collection, ordinal), UNIQUE(collection, identity))"
            )
            self.database.execute(
                "CREATE TABLE lookups (collection TEXT, spec TEXT, key TEXT, ordinal INTEGER, "
                "PRIMARY KEY(collection, spec, key, ordinal))"
            )
        except BaseException:
            self.close()
            raise
        owner = _owners.get()
        if owner is not None:
            owner.enter_context(self)

    def append(self, name, rows):
        start = self.counts.get(name, 0)
        self.database.executemany(
            "INSERT INTO records VALUES (?, ?, ?, ?)",
            ((name, start + index, _encode(row["id"]), _encode(row)) for index, row in enumerate(rows)),
        )
        self.counts[name] = start + len(rows)

    def rows(self, name):
        self.counts.setdefault(name, 0)
        return SnapshotRows(self, name)

    def close(self):
        if getattr(self, "database", None) is not None:
            self.database.close()
            self.database = None
        if getattr(self, "directory", None) is not None:
            self.directory.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        self.close()
