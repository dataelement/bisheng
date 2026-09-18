from __future__ import annotations

import json
import subprocess
import sys
from contextlib import asynccontextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from scripts import unset_admin as script


# 独立 SQLite 表验证实际 SQL 和事务, 不连接项目配置中的数据库.
class User(SQLModel, table=True):
    __tablename__ = "unset_test_user"
    user_id: int = Field(primary_key=True)
    user_name: str
    delete: int = 0
    token_version: int = 0


class Role(SQLModel, table=True):
    __tablename__ = "unset_test_role"
    id: int = Field(primary_key=True)
    tenant_id: int = 1


class UserRole(SQLModel, table=True):
    __tablename__ = "unset_test_userrole"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int
    role_id: int
    tenant_id: int = 1


class FailedTuple(SQLModel, table=True):
    __tablename__ = "unset_test_failed_tuple"
    id: int | None = Field(default=None, primary_key=True)
    action: str = "write"
    fga_user: str
    relation: str = "super_admin"
    object: str = "system:global"
    status: str = "pending"
    error_message: str = "original"
    tenant_id: int = 1


class FakeLock:
    def __init__(self):
        self.busy = False
        self.held = False

    async def acquire(self):
        self.held = not self.busy
        return self.held

    async def owned(self):
        return self.held

    async def reacquire(self):
        return self.held

    async def release(self):
        self.held = False


class FakeRedis:
    def __init__(self):
        self.guard = FakeLock()
        self.deleted = []
        self.cache_error = False
        self.patterns = []

    def lock(self, name, **kwargs):
        assert name == script.RETRY_LOCK_KEY
        return self.guard

    async def scan_iter(self, match, **kwargs):
        self.patterns.append(match)
        yield match.replace("*", "7", 1).replace("*", "cached")

    async def delete(self, *keys):
        if self.cache_error:
            raise RuntimeError("cache unavailable")
        self.deleted.extend(keys)


class FakeFga:
    def __init__(self):
        self.super = True
        self.fail = False

    async def is_super(self, user_id):
        return self.super

    async def revoke(self, user_id):
        if self.fail:
            raise RuntimeError("FGA unavailable")
        self.super = False


@pytest.fixture
async def backend():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [model.__table__ for model in (User, Role, UserRole, FailedTuple)]
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync: SQLModel.metadata.create_all(sync, tables=tables))

    @asynccontextmanager
    async def session():
        async with AsyncSession(engine, expire_on_commit=False) as current:
            yield current

    b = SimpleNamespace(
        session=session,
        bypass=nullcontext,
        User=User,
        Role=Role,
        UserRole=UserRole,
        FailedTuple=FailedTuple,
        admin_role=1,
        default_role=2,
    )
    async with session() as current:
        current.add_all(
            [
                User(user_id=1, user_name="admin"),
                User(user_id=8, user_name="target"),
                Role(id=1),
                Role(id=2),
                Role(id=9, tenant_id=7),
                UserRole(user_id=1, role_id=1),
                UserRole(user_id=8, role_id=1),
                UserRole(user_id=8, role_id=9, tenant_id=7),
                FailedTuple(fga_user="user:8"),
                FailedTuple(fga_user="user:8", relation="viewer", object="knowledge_space:3"),
                FailedTuple(fga_user="user:1"),
            ]
        )
        await current.commit()
    yield b
    await engine.dispose()


async def database_contents(backend):
    async with backend.session() as session:
        return {
            model.__name__: [row.model_dump() for row in (await session.exec(select(model))).all()]
            for model in (User, UserRole, FailedTuple)
        }


async def test_preview_has_no_writes_and_shows_scope(backend):
    before = await database_contents(backend)
    fga = FakeFga()
    state = await script.execute(backend, fga, 8, apply=False)
    assert state["fga_super_admin"] is True
    assert state["roles"] == [{"role_id": 1, "tenant_id": 1}, {"role_id": 9, "tenant_id": 7}]
    assert await database_contents(backend) == before
    assert fga.super is True


async def test_revoke_preserves_other_roles_and_users_and_is_idempotent(backend):
    fga, redis = FakeFga(), FakeRedis()
    await script.execute(backend, fga, 8, apply=True, redis=redis)
    state = await script.snapshot(backend, 8)
    assert {(r["role_id"], r["tenant_id"]) for r in state["roles"]} == {(2, 1), (9, 7)}
    assert state["pending_writes"] == state["pending_deletes"] == []
    assert fga.super is False
    contents = await database_contents(backend)
    assert contents["User"][0]["token_version"] == 0
    assert contents["User"][1]["token_version"] == 1
    retries = contents["FailedTuple"]
    assert retries[0]["status"] == "dead"
    assert retries[1]["status"] == retries[2]["status"] == "pending"
    assert retries[3]["action"] == "delete" and retries[3]["status"] == "succeeded"
    assert redis.patterns == ["perm:chk:*:8:*", "perm:lst:*:8:*"]
    assert "user:8:is_super" in redis.deleted and "user:8:token_version" in redis.deleted
    await script.execute(backend, fga, 8, apply=True, redis=redis)
    assert await database_contents(backend) == contents


@pytest.mark.parametrize("failure", ["fga", "cache"])
async def test_partial_failure_never_reports_success_and_can_resume(backend, capsys, failure):
    fga, redis = FakeFga(), FakeRedis()
    fga.fail = failure == "fga"
    redis.cache_error = failure == "cache"
    with pytest.raises(RuntimeError):
        await script.execute(backend, fga, 8, apply=True, redis=redis)
    output = capsys.readouterr().out
    assert '"phase": "database_committed"' in output
    assert '"phase": "verified"' not in output
    state = await script.snapshot(backend, 8)
    assert all(r["role_id"] != 1 for r in state["roles"])
    assert state["pending_writes"] == [] and state["pending_deletes"]
    assert not redis.guard.held
    fga.fail = redis.cache_error = False
    await script.execute(backend, fga, 8, apply=True, redis=redis)
    assert (await script.snapshot(backend, 8))["pending_deletes"] == []


@pytest.mark.parametrize("reason", ["missing_user", "last_admin", "busy_worker", "missing_default_role"])
async def test_preflight_failure_does_not_change_database(backend, reason):
    from sqlalchemy import delete, update

    redis, target = FakeRedis(), 8
    async with backend.session() as session:
        if reason == "last_admin":
            await session.exec(update(User).where(User.user_id == 1).values(delete=1))
        elif reason == "missing_default_role":
            await session.exec(delete(Role).where(Role.id == 2))
        elif reason == "missing_user":
            target = 999
        else:
            redis.guard.busy = True
        await session.commit()
    before = await database_contents(backend)
    with pytest.raises(script.UnsetAdminError):
        await script.execute(backend, FakeFga(), target, apply=True, redis=redis)
    assert await database_contents(backend) == before


async def test_database_failure_rolls_back_role_removal_and_retry_cancellation(backend):
    # 模拟最后一次数据库 UPDATE 失败, 确认先前的 DELETE/UPDATE 没有部分提交.
    from sqlalchemy import event

    async with backend.session() as session:
        engine = session.bind.sync_engine
    before = await database_contents(backend)

    def fail_update(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE unset_test_user SET token_version"):
            raise RuntimeError("database unavailable")

    event.listen(engine, "before_cursor_execute", fail_update)
    try:
        with pytest.raises(RuntimeError):
            await script.execute(backend, FakeFga(), 8, apply=True, redis=FakeRedis())
    finally:
        event.remove(engine, "before_cursor_execute", fail_update)
    assert await database_contents(backend) == before


async def test_existing_default_role_is_preserved_without_duplicate(backend):
    async with backend.session() as session:
        session.add(UserRole(user_id=8, role_id=2, tenant_id=7))
        await session.commit()
    await script.execute(backend, FakeFga(), 8, apply=True, redis=FakeRedis())
    roles = (await script.snapshot(backend, 8))["roles"]
    assert [r for r in roles if r["role_id"] == 2] == [{"role_id": 2, "tenant_id": 7}]


async def test_fga_uses_existing_store_and_strict_checks_for_both_models():
    requests, allowed = [], {"value": True}

    def handler(request):
        requests.append(request)
        if request.url.path == "/stores":
            return httpx.Response(200, json={"stores": [{"name": "bisheng", "id": "store"}]})
        if request.url.path.endswith("authorization-models"):
            return httpx.Response(200, json={"authorization_models": [{"id": "new"}]})
        body = json.loads(request.content)
        if request.url.path.endswith("check"):
            assert body["consistency"] == "HIGHER_CONSISTENCY"
            return httpx.Response(200, json={"allowed": allowed["value"]})
        assert body["deletes"]["tuple_keys"] == [script.ExistingFga.key(8)]
        allowed["value"] = False
        return httpx.Response(200, json={})

    config = SimpleNamespace(
        enabled=True, store_id=None, store_name="bisheng", model_id=None, dual_model_mode=True, legacy_model_id="old"
    )
    async with httpx.AsyncClient(base_url="http://fga", transport=httpx.MockTransport(handler)) as http:
        fga = await script.ExistingFga.connect(config, http)
        assert all(r.method == "GET" for r in requests)
        await fga.revoke(8)
        assert await fga.is_super(8) is False
    checks = [json.loads(r.content)["authorization_model_id"] for r in requests if r.url.path.endswith("check")]
    assert set(checks) == {"new", "old"}


@pytest.mark.parametrize("response", [{}, {"allowed": "false"}])
async def test_invalid_fga_response_cannot_be_treated_as_revoked(response):
    async with httpx.AsyncClient(
        base_url="http://fga", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))
    ) as http:
        with pytest.raises(script.UnsetAdminError):
            await script.ExistingFga(http, "store", ["model"]).is_super(8)


@pytest.mark.parametrize("status, allowed_after", [(503, False), (200, True)])
async def test_fga_write_failure_or_remaining_grant_never_reports_success(status, allowed_after):
    state = {"allowed": True}

    def handler(request):
        if request.url.path.endswith("check"):
            return httpx.Response(200, json={"allowed": state["allowed"]})
        state["allowed"] = allowed_after
        return httpx.Response(status, json={})

    async with httpx.AsyncClient(base_url="http://fga", transport=httpx.MockTransport(handler)) as http:
        with pytest.raises((httpx.HTTPStatusError, script.UnsetAdminError)):
            await script.ExistingFga(http, "store", ["model"]).revoke(8)


async def test_lost_lock_prevents_mutation(backend):
    redis = FakeRedis()
    redis.guard.owned = AsyncMock(return_value=False)
    before = await database_contents(backend)
    with pytest.raises(script.UnsetAdminError, match="锁已丢失"):
        await script.execute(backend, FakeFga(), 8, apply=True, redis=redis)
    assert await database_contents(backend) == before


def test_cli_help_and_invalid_id_do_not_require_backend_services():
    path = Path(script.__file__)
    for args, expected in [(["--help"], 0), (["0", "--apply"], 2)]:
        result = subprocess.run([sys.executable, str(path), *args], capture_output=True, text=True)
        assert result.returncode == expected, result.stderr


async def test_main_returns_nonzero_on_failure(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["unset_admin.py", "8", "--apply"])
    monkeypatch.setattr(script, "run", AsyncMock(side_effect=script.UnsetAdminError("未完成")))
    # main 自行创建事件循环, 用线程避开 pytest 的事件循环.
    import asyncio

    assert await asyncio.to_thread(script.main) == 1
    assert '"phase": "failed"' in capsys.readouterr().out
