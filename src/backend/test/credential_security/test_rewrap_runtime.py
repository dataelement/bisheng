"""AC-28..36: actual SQLModel updates preserve tenants, timestamps and JSON."""

import importlib.util
import json
from contextlib import contextmanager, nullcontext
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import Column, DateTime, String, create_engine
from sqlmodel import Field, Session, SQLModel

from bisheng.core.config.credential_rewrap import CredentialConfigurationError


class Org(SQLModel, table=True):
    __tablename__ = "rewrap_test_org"
    id: int = Field(primary_key=True)
    tenant_id: int
    value: str
    auth_config: str
    update_time: datetime = Field(sa_column=Column(DateTime, onupdate=datetime.now))


class Conf(SQLModel, table=True):
    __tablename__ = "rewrap_test_conf"
    id: int = Field(primary_key=True)
    key: str = Field(sa_column=Column(String))
    value: str
    update_time: datetime = Field(sa_column=Column(DateTime, onupdate=datetime.now))


@pytest.fixture
def runtime(tmp_path):
    path = Path(__file__).resolve().parents[2] / "scripts/rewrap_credentials.py"
    spec = importlib.util.spec_from_file_location("rewrap_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///" + str(tmp_path / "data.db"))
    SQLModel.metadata.create_all(engine, tables=[Org.__table__, Conf.__table__])

    @contextmanager
    def sessions():
        with Session(engine) as session:
            yield session

    store = module.RuntimeStore(sessions, Org, Conf, nullcontext)
    time = datetime(2025, 1, 1)
    with sessions() as s:
        s.add_all(
            [
                Org(id=1, tenant_id=2, value="untouched", auth_config="old", update_time=time),
                Conf(
                    id=1,
                    key="sandbox_endpoint",
                    value=json.dumps({"token_enc": "old", "endpoints": ["https://runner"], "unknown": 42}),
                    update_time=time,
                ),
            ]
        )
        s.commit()
    yield module, store, sessions, time
    engine.dispose()


def test_lock_compare_update_and_resume_keep_time(runtime):
    _, store, sessions, time = runtime
    entries = [
        {"kind": "org_sync", "id": 1, "tenant_id": 2, "old": "old", "new": "new"},
        {"kind": "sandbox", "id": 1, "tenant_id": None, "old": "old", "new": "new"},
    ]
    store.apply_batch(entries)
    store.apply_batch(entries)  # journal lag: already-new is an idempotent success
    with sessions() as s:
        org = s.get(Org, 1)
        conf = s.get(Conf, 1)
        assert org.tenant_id == 2 and org.value == "untouched" and org.auth_config == "new"
        assert org.update_time == time and conf.update_time == time
        assert json.loads(conf.value) == {"token_enc": "new", "endpoints": ["https://runner"], "unknown": 42}


def test_third_value_rolls_back_entire_current_batch(runtime):
    _, store, sessions, _ = runtime
    with pytest.raises(CredentialConfigurationError):
        store.apply_batch(
            [
                {"kind": "org_sync", "id": 1, "tenant_id": 2, "old": "old", "new": "new"},
                {"kind": "sandbox", "id": 1, "tenant_id": None, "old": "different", "new": "new"},
            ]
        )
    with sessions() as s:
        assert s.get(Org, 1).auth_config == "old"
    with pytest.raises(CredentialConfigurationError):
        store.apply_batch([{"kind": "org_sync", "id": 1, "tenant_id": 99, "old": "old", "new": "new"}])


def test_cache_failure_is_pending_and_resume_does_not_rewrite(runtime, tmp_path):
    from types import SimpleNamespace

    from cryptography.fernet import Fernet

    from bisheng.core.config.secret_crypto import load_keyring

    module, store, sessions, _ = runtime
    old_key = Fernet.generate_key()
    old = Fernet(old_key)
    keyfile = tmp_path / "keyring.json"
    keyfile.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode(), old_key.decode()]}))
    keyfile.chmod(0o600)
    keys = load_keyring(keyfile)
    with sessions() as s:
        org = s.get(Org, 1)
        org.auth_config = old.encrypt(b'{"unknown":42}').decode()
        conf = s.get(Conf, 1)
        conf.value = json.dumps({"token_enc": old.encrypt(b"unchanged").decode(), "endpoints": []})
        s.add(org)
        s.add(conf)
        s.commit()
    args = SimpleNamespace(verify_primary_only=False, resume=None, apply=True, backup_dir=tmp_path / "backup")

    def offline():
        raise ConnectionError("redis offline")

    with pytest.raises(CredentialConfigurationError, match="CACHE_PENDING"):
        module.execute(args, store, keys, offline, lambda key: None)
    with sessions() as s:
        committed = s.get(Org, 1).auth_config
    assert keys.decrypt_primary(committed) == '{"unknown":42}'
    assert json.loads((args.backup_dir / "journal.json").read_text())["phase"] == "DB_COMPLETE_CACHE_PENDING"
    args.resume = args.backup_dir
    assert module.execute(args, store, keys, lambda: None, lambda key: None) == 0
    with sessions() as s:
        assert s.get(Org, 1).auth_config == committed
    assert json.loads((args.backup_dir / "journal.json").read_text())["phase"] == "COMPLETE"


def test_backup_failure_occurs_before_any_update(runtime, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    module, _, _, _ = runtime
    store = MagicMock()
    store.records.return_value = []
    monkeypatch.setattr(module, "backup_plan", MagicMock(side_effect=OSError("disk full")))
    args = SimpleNamespace(verify_primary_only=False, resume=None, apply=True, backup_dir=tmp_path / "backup")
    with pytest.raises(OSError):
        module.execute(args, store, MagicMock(), MagicMock(), MagicMock())
    store.apply_batch.assert_not_called()


@pytest.mark.parametrize("cache_unavailable", [False, True])
async def test_cache_cleanup_keeps_existing_database_context(runtime, monkeypatch, cache_unavailable):
    """A cache maintenance call must not close an already-active DB consumer."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from sqlalchemy import text

    from bisheng.core.cache import redis_conn, redis_manager
    from bisheng.core.context import manager

    module, _, _, _ = runtime
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE consumer_state (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO consumer_state VALUES (1)"))
    client = SimpleNamespace(
        adelete=AsyncMock(side_effect=ConnectionError("cache unavailable") if cache_unavailable else None),
        aclose=AsyncMock(),
    )
    monkeypatch.setattr(redis_conn, "RedisClient", lambda url: client)
    monkeypatch.setattr(redis_manager, "get_redis_client_sync", lambda: client)
    monkeypatch.setattr(manager, "initialize_app_context", AsyncMock())

    async def close_global_context():
        engine.dispose()

    monkeypatch.setattr(manager, "close_app_context", close_global_context)
    try:
        if cache_unavailable:
            with pytest.raises(ConnectionError):
                await module.clear_sandbox_cache(SimpleNamespace(redis_url="redis://test"))
        else:
            await module.clear_sandbox_cache(SimpleNamespace(redis_url="redis://test"))
        with engine.connect() as conn:
            assert conn.execute(text("SELECT id FROM consumer_state")).scalar_one() == 1
        client.adelete.assert_awaited_once_with("config:sandbox_endpoint")
        client.aclose.assert_awaited_once()
    finally:
        engine.dispose()
