"""Exercise super-admin maintenance against a real SQLite database."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from scripts import set_admin as script


@pytest.fixture
async def runtime(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(script.User.__table__.create)
        await connection.execute(text("CREATE TABLE role (id INTEGER PRIMARY KEY)"))
        await connection.execute(text("INSERT INTO role VALUES (1)"))
        await connection.execute(
            text(
                "CREATE TABLE userrole (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, role_id INTEGER, tenant_id INTEGER NOT NULL DEFAULT 1, create_time DATETIME DEFAULT CURRENT_TIMESTAMP, update_time DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        for user_id in (1, 7, 8):
            await connection.execute(
                script.User.__table__.insert().values(
                    user_id=user_id,
                    user_name=f"User {user_id}",
                    password="test",
                    external_id=f"person-{user_id}",
                    delete=0,
                )
            )
        await connection.execute(text("INSERT INTO userrole(user_id, role_id) VALUES (7,1), (7,2), (7,9), (8,1)"))

    @asynccontextmanager
    async def get_session():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    state = SimpleNamespace(fga=True, invalidated=[])

    async def sync(user_id, action):
        state.fga = action == "grant"

    state.sync = AsyncMock(side_effect=sync)
    monkeypatch.setattr(script, "get_async_db_session", get_session)
    monkeypatch.setattr(script, "_sync_admin", state.sync, raising=False)
    monkeypatch.setattr(script, "_read_fga_super", AsyncMock(side_effect=lambda _: state.fga), raising=False)
    monkeypatch.setattr(
        script, "_invalidate_caches", AsyncMock(side_effect=lambda uid: state.invalidated.append(uid)), raising=False
    )

    async def roles(user_id):
        async with get_session() as session:
            return sorted(
                (await session.exec(select(script.UserRole.role_id).where(script.UserRole.user_id == user_id))).all()
            )

    state.roles, state.engine, state.session = roles, engine, get_session
    yield state
    await engine.dispose()


async def test_revoke_preview_does_not_change_either_store(runtime):
    assert await script.set_admin(7, action="revoke") == 0
    assert await runtime.roles(7) == [1, 2, 9]
    runtime.sync.assert_not_awaited()
    assert runtime.invalidated == []


async def test_revoke_preserves_other_roles_and_clears_cache(runtime):
    assert await script.set_admin(7, action="revoke", apply=True) == 0
    assert await runtime.roles(7) == [2, 9]
    assert not runtime.fga
    assert runtime.invalidated == [7]


@pytest.mark.parametrize("apply", [False, True])
async def test_first_user_can_never_be_revoked(runtime, apply):
    assert await script.set_admin(1, action="revoke", apply=apply) == 1
    runtime.sync.assert_not_awaited()


async def test_last_enabled_admin_cannot_be_revoked(runtime):
    async with runtime.engine.begin() as connection:
        await connection.execute(script.User.__table__.update().where(script.User.user_id == 8).values(delete=1))
    assert await script.set_admin(7, action="revoke", apply=True) == 1
    assert await runtime.roles(7) == [1, 2, 9]
    runtime.sync.assert_not_awaited()


async def test_grant_remains_compatible_and_idempotent(runtime):
    assert await script.set_admin(1) == 0
    assert await script.set_admin(1) == 0
    assert await runtime.roles(1) == [1]
    assert runtime.sync.await_count == 2


async def test_revoke_retry_repairs_fga_after_db_already_removed(runtime):
    async with runtime.engine.begin() as connection:
        await connection.execute(text("DELETE FROM userrole WHERE user_id=7 AND role_id=1"))
    assert await script.set_admin(7, action="revoke", apply=True) == 0
    assert await runtime.roles(7) == [2, 9]
    assert not runtime.fga


async def test_partial_failure_returns_nonzero_and_can_be_retried(runtime):
    effect = runtime.sync.side_effect
    runtime.sync.side_effect = RuntimeError("FGA unavailable")
    assert await script.set_admin(7, action="revoke", apply=True) == 2
    runtime.sync.side_effect = effect
    assert await script.set_admin(7, action="revoke", apply=True) == 0
    assert await runtime.roles(7) == [2, 9]
    assert not runtime.fga


async def test_status_detects_inconsistency_without_writing(runtime):
    runtime.fga = False
    assert await script.set_admin(7, action="status") == 2
    assert await runtime.roles(7) == [1, 2, 9]
    runtime.sync.assert_not_awaited()


async def test_unknown_user_is_rejected(runtime):
    assert await script.set_admin(99) == 1
    runtime.sync.assert_not_awaited()


async def test_disabled_user_cannot_be_promoted_but_can_be_revoked(runtime):
    async with runtime.engine.begin() as connection:
        await connection.execute(script.User.__table__.update().where(script.User.user_id == 7).values(delete=1))
    assert await script.set_admin(7) == 1
    assert await script.set_admin(7, action="revoke", apply=True) == 0


async def test_external_failure_does_not_claim_success(runtime):
    script._read_fga_super.side_effect = RuntimeError("offline")
    assert await script.set_admin(7, action="status") == 2


async def test_failed_cache_cleanup_is_nonzero(runtime):
    script._invalidate_caches.side_effect = RuntimeError("Redis offline")
    assert await script.set_admin(7, action="revoke", apply=True) == 2


async def test_silent_sync_failure_is_detected(runtime):
    runtime.sync.side_effect = None
    assert await script.set_admin(7, action="revoke", apply=True) == 2


async def test_grant_preview_does_not_insert_admin(runtime):
    assert await script.set_admin(1, apply=False) == 0
    assert await runtime.roles(1) == []
    runtime.sync.assert_not_awaited()


@pytest.mark.parametrize("user_id", [0, -1])
async def test_nonpositive_user_is_rejected(runtime, user_id):
    assert await script.set_admin(user_id) == 1
    runtime.sync.assert_not_awaited()


@pytest.mark.parametrize("failure", [None, "initialize", "permission", "operation"])
async def test_runtime_releases_resources_on_success_and_failure(monkeypatch, failure):
    from unittest.mock import Mock

    from bisheng.common.services.config_service import settings
    from bisheng.core.context import manager
    from bisheng.core.openfga import manager as fga_manager
    from bisheng.permission.application import process_runtime

    resources = []

    async def initialize(**kwargs):
        resources.append("connection")
        if failure == "initialize":
            raise RuntimeError("init failed")

    async def close():
        resources.clear()

    monkeypatch.setattr(settings.openfga, "enabled", True)
    monkeypatch.setattr(manager, "initialize_app_context", initialize)
    monkeypatch.setattr(manager, "close_app_context", close)
    context = Mock()
    context.get_registry.return_value.async_close_all = AsyncMock()
    monkeypatch.setattr(manager, "app_context", context)
    factory = Mock()
    monkeypatch.setattr(fga_manager, "FGAManager", factory)
    monkeypatch.setattr(process_runtime, "register_f048_permission_runtime_context", Mock())
    permission_ready = AsyncMock(
        side_effect=RuntimeError("permission unavailable") if failure == "permission" else None
    )
    monkeypatch.setattr(process_runtime, "get_f048_process_runtime", permission_ready)
    operation = AsyncMock(
        return_value=0, side_effect=RuntimeError("operation failed") if failure == "operation" else None
    )
    monkeypatch.setattr(script, "set_admin", operation)
    assert await script._run(7, action="status", apply=None) == (2 if failure else 0)
    assert resources == []
    if failure != "initialize":
        assert factory.call_args.kwargs["environment"] == "production"


@pytest.mark.parametrize(
    "arguments, expected",
    [
        ([], ("grant", None)),
        (["--action", "status"], ("status", None)),
        (["--dry-run"], ("grant", False)),
        (["--action", "revoke"], ("revoke", None)),
        (["--action", "revoke", "--apply"], ("revoke", True)),
    ],
)
def test_cli_modes(monkeypatch, arguments, expected):
    operation = AsyncMock(return_value=0)
    monkeypatch.setattr(script, "_run", operation)
    monkeypatch.setattr("sys.argv", ["set_admin.py", "7", *arguments])
    assert script.main() == 0
    operation.assert_awaited_once_with(7, action=expected[0], apply=expected[1])


@pytest.mark.parametrize(
    "arguments", [["1", "--action", "revoke", "--apply"], ["0"], ["7", "--action", "status", "--apply"]]
)
def test_cli_rejects_invalid_requests_before_connecting(monkeypatch, arguments):
    operation = AsyncMock()
    monkeypatch.setattr(script, "_run", operation)
    monkeypatch.setattr("sys.argv", ["set_admin.py", *arguments])
    with pytest.raises(SystemExit) as result:
        script.main()
    assert result.value.code != 0
    operation.assert_not_awaited()


async def test_cache_invalidation_covers_all_tenants_without_matching_other_users(monkeypatch):
    from fakeredis.aioredis import FakeRedis

    from bisheng.core.cache import redis_manager

    redis = FakeRedis()
    keys = [
        "user:7:is_super",
        "perm:chk:1:7:super_admin:system:global",
        "perm:chk:22:7:super_admin:system:global",
        "perm:lst:22:7:read:knowledge",
        "perm:chk:1:77:super_admin:system:global",
        "user:77:is_super",
    ]
    for key in keys:
        await redis.set(key, "1")
    connection = SimpleNamespace(scan_iter=redis.scan_iter, delete=redis.delete)
    wrapper = SimpleNamespace(async_connection=connection, adelete=redis.delete)
    monkeypatch.setattr(redis_manager, "get_redis_client", AsyncMock(return_value=wrapper))
    await script._invalidate_caches(7)
    assert set(await redis.keys("*")) == {keys[-2].encode(), keys[-1].encode()}
    await redis.aclose()


async def test_strict_sync_raises_on_transport_failure_without_background_compensation(monkeypatch):
    from bisheng.permission.domain.services.permission_service import PermissionService

    client = SimpleNamespace(write_tuples=AsyncMock(side_effect=RuntimeError("offline")))
    monkeypatch.setattr(PermissionService, "_aget_fga", AsyncMock(return_value=client))
    compensation = AsyncMock()
    monkeypatch.setattr(PermissionService, "_save_failed_tuples", compensation)
    with pytest.raises(RuntimeError, match="offline"):
        await script._sync_admin(7, "grant")
    compensation.assert_not_awaited()


async def test_partial_context_initialization_closes_already_opened_connections(monkeypatch):
    from bisheng.common.services.config_service import settings
    from bisheng.core.context import manager
    from bisheng.core.context.base import FunctionContextManager

    resources = []

    async def open_connection():
        resources.append("db")
        return "db"

    async def close_connection(value):
        resources.remove(value)

    async def fail():
        raise RuntimeError("next dependency unavailable")

    class PartialContext(manager.ApplicationContextManager):
        def _register_default_contexts(self, config, *, instance_role):
            self.register_context(FunctionContextManager("database", open_connection, close_connection))
            self.register_context(FunctionContextManager("broken", fail))

    context = PartialContext()
    monkeypatch.setattr(manager, "app_context", context)
    monkeypatch.setattr(settings.openfga, "enabled", True)
    assert await script._run(7, action="status", apply=None) == 2
    assert resources == []
