"""覆盖 AC: AC-37、AC-38、AC-40、AC-63。"""

import os
import sqlite3
from pathlib import Path

import pytest

from runtime_manager.config import Config
from runtime_manager.container_runner import ExecutionError
from runtime_manager.platform_appdb import PlatformAppDb


class Platform:
    def __init__(self):
        self.confirmed = True
        self.content = None

    def upload(self, op, path, **kwargs):
        self.content = Path(path).read_bytes()
        return {"artifact_id": "snap", "state": "verified", "confirmed_at": "now" if self.confirmed else None}


def setup(tmp_path):
    cfg = Config(data_root=tmp_path)
    path = cfg.app_data_dir("app") / "app.db"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE data (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO data VALUES (1,'kept')")
    platform = Platform()
    return (
        PlatformAppDb(
            cfg,
            platform,
            {
                "app_id": "app",
                "operation_id": "op",
                "payload": {"resolved_delivery": {"profile": {"uid": os.getuid(), "gid": os.getgid()}}},
            },
        ),
        platform,
        path,
    )


def test_unconfirmed_snapshot_blocks_ddl(tmp_path):
    service, platform, path = setup(tmp_path)
    platform.confirmed = False
    with pytest.raises(ExecutionError, match="snapshot_confirmation"):
        service.backup()
    with pytest.raises(ExecutionError, match="snapshot_confirmation"):
        service.migrate_confirmed([{"op": "drop_table", "table": "data"}])
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM data").fetchone()[0] == "kept"


def test_backup_is_consistent_and_remains_protected(tmp_path):
    service, _platform, _path = setup(tmp_path)
    assert service.backup()["confirmed_at"]
    backup = tmp_path / "protected-backups/app/op.sqlite"
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT value FROM data").fetchone()[0] == "kept"
    assert backup.exists()


def test_destructive_migration_replay_is_idempotent(tmp_path):
    service, _platform, path = setup(tmp_path)
    snapshot = service.backup()
    plan = [{"op": "drop_table", "table": "data"}]
    service.migrate_confirmed(plan, snapshot=snapshot)
    assert service.migrate_confirmed(plan, snapshot=snapshot)["skipped"] == ["already_committed"]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='data'").fetchone() is None
        assert connection.execute("SELECT COUNT(*) FROM _bisheng_runtime_migrations").fetchone()[0] == 1


def test_restore_protects_current_database_and_keeps_target_ownership(tmp_path):
    service, platform, path = setup(tmp_path)
    service.backup()
    original = platform.content
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE data SET value='newer'")

    def download(operation, artifact, target):
        target.write_bytes(original)
        return {"kind": "snapshot"}

    platform.download = download
    result = service.restore_confirmed("snapshot-original")
    assert result["protected_snapshot"]["confirmed_at"]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM data").fetchone()[0] == "kept"
    assert path.stat().st_uid == os.getuid()


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_app_database_link_is_rejected_before_host_io(tmp_path, suffix):
    service, _platform, path = setup(tmp_path)
    target = tmp_path / "outside.sqlite"
    target.write_bytes(b"unrelated")
    link = Path(str(path) + suffix)
    link.unlink(missing_ok=True)
    link.symlink_to(target)
    with pytest.raises(ExecutionError, match="database_link"):
        service.backup()
    assert target.read_bytes() == b"unrelated"
