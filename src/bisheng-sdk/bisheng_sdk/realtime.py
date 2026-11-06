"""Transactional record collaboration for a single-writer hosted SQLite app.

HTTP/authentication stays with the application. Events contain invalidation
metadata only; an application's endpoints must authorize every read and stream.
"""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from bisheng_sdk._env import workbench_database_path


class RevisionConflict(Exception):
    """The record changed since the caller read it."""


class OperationConflict(Exception):
    """An idempotency key was reused for a different write."""


class ReplayExpired(Exception):
    """Reload a snapshot: the requested cursor is outside the retained log."""


class RealtimeStore:
    def __init__(self, path=None):
        self.path = str(path or workbench_database_path())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS wb_records (
                  collection TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL,
                  data TEXT, PRIMARY KEY(collection,id));
                CREATE TABLE IF NOT EXISTS wb_events (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, collection TEXT NOT NULL,
                  record_id TEXT NOT NULL, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS wb_operations (
                  actor TEXT NOT NULL, operation_id TEXT NOT NULL, request_hash TEXT NOT NULL,
                  result TEXT NOT NULL, PRIMARY KEY(actor,operation_id));
                CREATE TABLE IF NOT EXISTS wb_replay (id INTEGER PRIMARY KEY, floor INTEGER NOT NULL);
                INSERT OR IGNORE INTO wb_replay VALUES (1,0);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def name(value):
        if not isinstance(value, str) or not value or len(value) > 200 or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid record, collection or operation identity")
        return value

    @staticmethod
    def encode(value):
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode()) > 65536:
            raise ValueError("Record exceeds the allowed size")
        return encoded

    def write(self, collection, record_id, value, *, expected_revision, operation_id, actor):
        self.name(collection), self.name(record_id), self.name(operation_id), self.name(actor)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("A non-negative expected revision is required")
        data = self.encode(value) if value is not None else None
        request_hash = hashlib.sha256(
            self.encode([collection, record_id, data, expected_revision]).encode()
        ).hexdigest()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT request_hash,result FROM wb_operations WHERE actor=? AND operation_id=?", (actor, operation_id)
            ).fetchone()
            if prior:
                if prior["request_hash"] != request_hash:
                    raise OperationConflict()
                return json.loads(prior["result"])
            row = db.execute(
                "SELECT revision FROM wb_records WHERE collection=? AND id=?", (collection, record_id)
            ).fetchone()
            revision = row["revision"] if row else 0
            if revision != expected_revision:
                raise RevisionConflict()
            revision += 1
            db.execute(
                "INSERT INTO wb_records VALUES(?,?,?,?) ON CONFLICT(collection,id) DO UPDATE SET revision=excluded.revision,data=excluded.data",
                (collection, record_id, revision, data),
            )
            event = db.execute(
                "INSERT INTO wb_events(collection,record_id,revision) VALUES(?,?,?)", (collection, record_id, revision)
            )
            result = {"id": record_id, "revision": revision, "value": value, "cursor": event.lastrowid}
            db.execute(
                "INSERT INTO wb_operations VALUES(?,?,?,?)", (actor, operation_id, request_hash, self.encode(result))
            )
            return result

    def snapshot(self, collection):
        self.name(collection)
        with self.connection() as db:
            db.execute("BEGIN")
            cursor = db.execute("SELECT COALESCE(MAX(seq),0) FROM wb_events").fetchone()[0]
            floor = db.execute("SELECT floor FROM wb_replay WHERE id=1").fetchone()[0]
            rows = db.execute(
                "SELECT id,revision,data FROM wb_records WHERE collection=? AND data IS NOT NULL ORDER BY id",
                (collection,),
            ).fetchall()
            return {
                "cursor": max(cursor, floor),
                "records": [
                    {"id": row["id"], "revision": row["revision"], "value": json.loads(row["data"])} for row in rows
                ],
            }

    def events(self, after, *, limit=100):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Invalid event cursor")
        with self.connection() as db:
            db.execute("BEGIN")
            floor = db.execute("SELECT floor FROM wb_replay WHERE id=1").fetchone()[0]
            maximum = db.execute("SELECT COALESCE(MAX(seq),0) FROM wb_events").fetchone()[0]
            if after < floor or after > max(floor, maximum):
                raise ReplayExpired()
            return [
                dict(row)
                for row in db.execute(
                    "SELECT seq,collection,record_id,revision FROM wb_events WHERE seq>? ORDER BY seq LIMIT ?",
                    (after, limit),
                )
            ]

    def prune(self, through):
        if type(through) is not int or through < 0:
            raise ValueError("Invalid retention cursor")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            maximum = db.execute("SELECT COALESCE(MAX(seq),0) FROM wb_events").fetchone()[0]
            floor = db.execute("SELECT floor FROM wb_replay WHERE id=1").fetchone()[0]
            floor = max(floor, min(through, maximum))
            db.execute("UPDATE wb_replay SET floor=? WHERE id=1", (floor,))
            db.execute("DELETE FROM wb_events WHERE seq<=?", (floor,))
