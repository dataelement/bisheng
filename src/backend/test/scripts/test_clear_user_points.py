"""只使用临时 SQLite 验证积分清空的范围、备份和事务回滚。"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, create_engine, event, select

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "clear_user_points.py"
SPEC = importlib.util.spec_from_file_location("clear_user_points_script", SCRIPT)
script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(script)


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'points.db'}")
    metadata = MetaData()
    Table(
        "user",
        metadata,
        Column("user_id", Integer, primary_key=True),
        Column("user_name", String),
        Column("external_id", String),
        Column("external_code", String),
    )
    for name in ("user_point_account", "user_point_log", "point_pending_deduct", "point_rank_snapshot"):
        Table(
            name,
            metadata,
            Column("id", Integer, primary_key=True),
            Column("tenant_id", Integer),
            Column("user_id", Integer),
            Column("value", Integer),
        )
    Table(
        "point_sync_outbox",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("tenant_id", Integer),
        Column("log_id", ForeignKey("user_point_log.id")),
    )
    Table(
        "point_favorite_tier_award",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("tenant_id", Integer),
        Column("file_id", Integer),
    )
    for name in ("point_rule", "point_copy"):
        Table(name, metadata, Column("id", Integer, primary_key=True), Column("tenant_id", Integer))
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        metadata.create_all(connection)
        connection.execute(
            metadata.tables["user"].insert(),
            [
                {"user_id": 7, "user_name": "wenruli", "external_id": "employee7", "external_code": "code7"},
                {"user_id": 8, "user_name": "other", "external_id": "employee8", "external_code": "code8"},
            ],
        )
        for name in ("user_point_account", "user_point_log", "point_pending_deduct", "point_rank_snapshot"):
            connection.execute(
                metadata.tables[name].insert(),
                [
                    {"id": 1, "tenant_id": 1, "user_id": 7, "value": 99},
                    {"id": 2, "tenant_id": 1, "user_id": 8, "value": 33},
                    {"id": 3, "tenant_id": 2, "user_id": 7, "value": 66},
                ],
            )
        connection.execute(
            metadata.tables["point_sync_outbox"].insert(),
            [
                {"id": 1, "tenant_id": 1, "log_id": 1},
                {"id": 2, "tenant_id": 1, "log_id": 2},
                {"id": 3, "tenant_id": 2, "log_id": 3},
            ],
        )
        connection.execute(
            metadata.tables["point_favorite_tier_award"].insert(),
            [{"id": 1, "tenant_id": 1, "file_id": 9}, {"id": 2, "tenant_id": 2, "file_id": 10}],
        )
        for name in ("point_rule", "point_copy"):
            connection.execute(metadata.tables[name].insert(), {"id": 1, "tenant_id": 1})
    yield engine, metadata
    engine.dispose()


def snapshot(database):
    engine, metadata = database
    with engine.connect() as connection:
        return {
            name: [dict(row) for row in connection.execute(select(table)).mappings()]
            for name, table in metadata.tables.items()
        }


@pytest.mark.parametrize("account", ["wenruli", "employee7", "code7"])
def test_preview_preserves_all_data_and_creates_no_backup(database, tmp_path, account):
    before = snapshot(database)
    report = script.clear_user_points(database[0], account=account, backup_dir=tmp_path / "backup")
    assert report["user_id"] == 7
    assert report["counts"] == dict.fromkeys(script.POINT_TABLES, 1)
    assert report["status"] == "只读预览, 未删除"
    assert snapshot(database) == before
    assert not (tmp_path / "backup").exists()


def test_apply_backs_up_then_clears_only_target_user_and_tenant(database, tmp_path):
    before = snapshot(database)
    report = script.clear_user_points(database[0], apply=True, backup_dir=tmp_path / "backup")
    assert report["status"] == "已提交"
    backup = Path(report["backup_file"])
    document = json.loads(backup.read_text())
    assert backup.stat().st_mode & 0o777 == 0o600
    after = snapshot(database)
    for name in script.POINT_TABLES:
        assert document["tables"][name] == [before[name][0]]
        assert after[name] == before[name][1:]
    for name in ("user", "point_favorite_tier_award"):
        assert after[name] == before[name]
    repeated = script.clear_user_points(database[0], apply=True, backup_dir=tmp_path / "backup")
    assert repeated["status"] == "无需清理"
    assert len(list((tmp_path / "backup").glob("*.json"))) == 1


@pytest.mark.parametrize("all_users", [False, True])
def test_delete_failure_rolls_back_preceding_deletes(database, tmp_path, all_users):
    before = snapshot(database)

    def fail_on_log_delete(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith("DELETE FROM user_point_log"):
            raise RuntimeError("模拟删除流水失败")

    event.listen(database[0], "before_cursor_execute", fail_on_log_delete)
    try:
        with pytest.raises(RuntimeError, match="模拟删除流水失败"):
            script.clear_user_points(database[0], all_users=all_users, apply=True, backup_dir=tmp_path / "backup")
    finally:
        event.remove(database[0], "before_cursor_execute", fail_on_log_delete)
    assert snapshot(database) == before
    assert len(list((tmp_path / "backup").glob("*.json"))) == 1


def test_backup_failure_prevents_deletion(database, tmp_path):
    before = snapshot(database)
    invalid_dir = tmp_path / "not-a-directory"
    invalid_dir.write_text("保留已有文件")
    with pytest.raises(OSError):
        script.clear_user_points(database[0], apply=True, backup_dir=invalid_dir)
    assert snapshot(database) == before


@pytest.mark.parametrize("account", ["missing-user", "wenruli' OR '1'='1"])
def test_unmatched_account_never_deletes(database, tmp_path, account):
    before = snapshot(database)
    with pytest.raises(ValueError, match="必须唯一匹配"):
        script.clear_user_points(database[0], account=account, apply=True, backup_dir=tmp_path / "backup")
    assert snapshot(database) == before


def test_ambiguous_account_never_deletes(database, tmp_path):
    with database[0].begin() as connection:
        user = database[1].tables["user"]
        connection.execute(user.update().where(user.c.user_id == 8).values(external_id="wenruli"))
    before = snapshot(database)
    with pytest.raises(ValueError, match="必须唯一匹配"):
        script.clear_user_points(database[0], apply=True, backup_dir=tmp_path / "backup")
    assert snapshot(database) == before


@pytest.mark.parametrize("tenant_id", [1, 2])
@pytest.mark.parametrize("apply", [False, True])
def test_all_users_preserves_other_tenants_accounts_and_config(database, tmp_path, tenant_id, apply):
    # 全量模式也要清理已失去用户账号关联的旧积分流水。
    with database[0].begin() as connection:
        connection.execute(
            database[1].tables["user_point_log"].insert(),
            {"id": 4, "tenant_id": 1, "user_id": 999, "value": 12},
        )
        connection.execute(database[1].tables["point_sync_outbox"].insert(), {"id": 4, "tenant_id": 1, "log_id": 4})
    before = snapshot(database)
    report = script.clear_user_points(
        database[0], tenant_id=tenant_id, all_users=True, apply=apply, backup_dir=tmp_path / "backup"
    )
    assert report["scope"] == "all_users"
    assert report["user_id"] is None
    assert report["account"] is None
    after = snapshot(database)
    if not apply:
        assert after == before
        assert not (tmp_path / "backup").exists()
    else:
        assert report["status"] == "已提交"
        backup = json.loads(Path(report["backup_file"]).read_text())
        assert backup["scope"] == "all_users"
        for name in script.ALL_POINT_TABLES:
            assert backup["tables"][name] == [row for row in before[name] if row["tenant_id"] == tenant_id]
            assert after[name] == [row for row in before[name] if row["tenant_id"] != tenant_id]
        for name in ("user", "point_rule", "point_copy"):
            assert after[name] == before[name]
    for name in script.ALL_POINT_TABLES:
        assert report["counts"][name] == len([row for row in before[name] if row["tenant_id"] == tenant_id])


def test_all_users_and_account_are_mutually_exclusive(database, tmp_path):
    before = snapshot(database)
    with pytest.raises(ValueError, match="不能同时指定"):
        script.clear_user_points(
            database[0], all_users=True, account="wenruli", apply=True, backup_dir=tmp_path / "backup"
        )
    assert snapshot(database) == before
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--all-users", "--account", "wenruli", "--apply"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr
