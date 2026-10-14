"""Maintenance cleanup preserves unrelated tables and requires an exact backup."""

import json

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, select

from scripts.clear_eplus_history import cleanup


@pytest.fixture
def database():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    turns = Table(
        "eplus_turn",
        metadata,
        Column("id", String, primary_key=True),
        Column("tenant_id", Integer),
        Column("conversation_id", String),
        Column("status", String),
        Column("answer_text", String),
    )
    conversations = Table("eplus_conversation", metadata, Column("id", String, primary_key=True))
    inbound = Table("eplus_inbound_message", metadata, Column("id", Integer, primary_key=True))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            turns.insert(),
            [
                {"id": "a", "tenant_id": 1, "conversation_id": "c1", "status": "SUCCEEDED", "answer_text": "old"},
                {"id": "b", "tenant_id": 1, "conversation_id": "c2", "status": "FAILED", "answer_text": None},
                {"id": "c", "tenant_id": 2, "conversation_id": "c3", "status": "SUCCEEDED", "answer_text": "other"},
            ],
        )
        connection.execute(conversations.insert(), {"id": "c1"})
        connection.execute(inbound.insert(), {"id": 1})
    yield engine, turns, conversations, inbound
    engine.dispose()


def test_preview_backs_up_without_deleting(database, tmp_path):
    engine, turns, _, _ = database
    path = tmp_path / "backup.json"
    with engine.begin() as connection:
        assert cleanup(connection, tenant_id=1, backup_path=path) == 2
        assert len(connection.execute(select(turns)).all()) == 3
    assert len(json.loads(path.read_text())["rows"]) == 2
    assert path.stat().st_mode & 0o777 == 0o600


def test_apply_deletes_all_terminal_turns_but_preserves_other_tables(database, tmp_path):
    engine, turns, conversations, inbound = database
    path = tmp_path / "backup.json"
    with engine.begin() as connection:
        cleanup(connection, tenant_id=1, backup_path=path)
        assert cleanup(connection, tenant_id=1, backup_path=path, apply=True, workers_stopped=True) == 2
        assert connection.execute(select(turns.c.id)).scalars().all() == ["c"]
        assert connection.execute(select(conversations.c.id)).scalar_one() == "c1"
        assert connection.execute(select(inbound.c.id)).scalar_one() == 1


@pytest.mark.parametrize("status", ["PREPARING", "QUEUED", "RUNNING", "UNKNOWN"])
def test_nonterminal_turn_blocks_cleanup(database, tmp_path, status):
    engine, turns, _, _ = database
    with engine.begin() as connection:
        connection.execute(turns.update().where(turns.c.id == "a").values(status=status))
        with pytest.raises(RuntimeError, match="non-terminal"):
            cleanup(connection, tenant_id=1, backup_path=tmp_path / "backup.json")
        assert len(connection.execute(select(turns)).all()) == 3


def test_changed_rows_reject_apply(database, tmp_path):
    engine, turns, _, _ = database
    path = tmp_path / "backup.json"
    with engine.begin() as connection:
        cleanup(connection, tenant_id=1, backup_path=path)
        connection.execute(turns.update().where(turns.c.id == "a").values(answer_text="changed"))
        with pytest.raises(RuntimeError, match="does not match"):
            cleanup(connection, tenant_id=1, backup_path=path, apply=True, workers_stopped=True)
        assert len(connection.execute(select(turns)).all()) == 3


def test_requires_stopped_workers_and_existing_backup(database, tmp_path):
    engine, turns, _, _ = database
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="workers"):
            cleanup(connection, tenant_id=1, backup_path=tmp_path / "backup.json", apply=True)
        with pytest.raises(FileNotFoundError):
            cleanup(connection, tenant_id=1, backup_path=tmp_path / "backup.json", apply=True, workers_stopped=True)
        assert len(connection.execute(select(turns)).all()) == 3


def test_backup_failure_never_deletes(database, tmp_path):
    engine, turns, _, _ = database
    path = tmp_path / "backup.json"
    path.write_text("existing")
    with engine.begin() as connection:
        with pytest.raises(FileExistsError):
            cleanup(connection, tenant_id=1, backup_path=path)
        assert len(connection.execute(select(turns)).all()) == 3


def test_explicit_all_tenants(database, tmp_path):
    engine, turns, _, _ = database
    path = tmp_path / "backup.json"
    with engine.begin() as connection:
        assert cleanup(connection, tenant_id=None, backup_path=path) == 3
        assert cleanup(connection, tenant_id=None, backup_path=path, apply=True, workers_stopped=True) == 3
        assert connection.execute(select(turns)).all() == []


def test_cleanup_does_not_reflect_indexes(database, tmp_path, monkeypatch):
    engine, _, _, _ = database

    def broken_index_reflection(*args, **kwargs):
        raise AttributeError("attribute '_data' of BaseRow objects is not writable")

    monkeypatch.setattr(engine.dialect, "get_indexes", broken_index_reflection)
    with engine.begin() as connection:
        assert cleanup(connection, tenant_id=1, backup_path=tmp_path / "backup.json") == 2
