"""F133 account discovery is exact, read-only and never guesses a tenant."""

from contextlib import asynccontextmanager
from importlib import import_module
from importlib.util import find_spec
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateTable
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.sso_sync import KunlianIdentityUnavailableError
from bisheng.core.context.tenant import current_tenant_id, is_tenant_filter_bypassed
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.user.domain.models.user import User


def test_user_owner_exports_account_resolution():
    assert find_spec("bisheng.user.application.kunlian_account") is not None, "F133 account Owner export is missing"


@pytest.fixture
async def account_owner():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        for table in (User.__table__, Tenant.__table__, UserTenant.__table__):
            ddl = str(CreateTable(table).compile(engine.sync_engine))
            # Reproduce case-insensitive production collation, with actual model columns.
            ddl = ddl.replace("user_name VARCHAR(128)", "user_name VARCHAR(128) COLLATE NOCASE")
            await conn.execute(text(ddl))

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    try:
        module = import_module("bisheng.user.application.kunlian_account")
    except ModuleNotFoundError as exc:
        if exc.name != "bisheng.user.application.kunlian_account":
            raise
        pytest.fail("F133 account resolution is not implemented", pytrace=False)
    repo_module = import_module("bisheng.user.domain.repositories.kunlian_account")
    directory = SimpleNamespace(
        find_account_bindings=AsyncMock(
            return_value=[
                SimpleNamespace(
                    connection_id="kl",
                    local_user_id=10,
                    external_tenant_id="ext",
                    subject="subject",
                )
            ]
        ),
        get_tenant_binding=AsyncMock(
            return_value=SimpleNamespace(
                connection_id="kl",
                external_tenant_id="ext",
                local_tenant_id=2,
                enabled=True,
            )
        ),
    )
    app = module.KunlianAccountApplication(repo_module.KunlianAccountRepository(sessions), directory)
    try:
        yield app, sessions, directory
    finally:
        await engine.dispose()


async def seed(sessions, *, name="Alice", deleted=0, membership=True, status="active", active=1):
    async with sessions() as session:
        session.add(User(user_id=10, user_name=name, password="", delete=deleted))
        session.add(Tenant(id=2, tenant_code="two", tenant_name="Two"))
        if membership:
            session.add(UserTenant(user_id=10, tenant_id=2, status=status, is_active=active))
        await session.commit()


async def test_sso_reverse_binding_lookup_is_read_only_and_connection_scoped(account_owner):
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.sso_sync.domain.models.kunlian import KunlianConnectionState, KunlianIdentityBinding
    from bisheng.sso_sync.domain.repositories.kunlian import KunlianDirectoryRepository

    _, sessions, _ = account_owner
    async with sessions() as session:
        connection = await session.connection()
        await connection.run_sync(KunlianConnectionState.__table__.create)
        await connection.run_sync(KunlianIdentityBinding.__table__.create)
        session.add(KunlianConnectionState(connection_id="kl"))
        session.add(
            KunlianIdentityBinding(
                identity_key="k" * 64,
                connection_id="kl",
                issuer="issuer",
                subject="subject",
                external_tenant_id="ext",
                member_id="member",
                local_user_id=10,
                source_revision="r" * 64,
            )
        )
        await session.commit()
    repository = KunlianDirectoryRepository(sessions)
    with tenant_execution_scope(1):
        rows = await repository.find_account_bindings("kl", 10)
        assert len(rows) == 1 and rows[0].subject == "subject"
        assert await repository.find_account_bindings("other", 10) == []
        assert await repository.find_account_bindings("kl", 11) == []
        assert (await repository.get_binding("k" * 64)).source_revision == "r" * 64


async def test_exact_account_returns_subject_not_member_or_name(account_owner):
    app, sessions, directory = account_owner
    await seed(sessions)
    token = current_tenant_id.set(99)
    try:
        result = await app.resolve_account("kl", "Alice")
        assert (result.user_id, result.tenant_id, result.external_tenant_id, result.external_user_id) == (
            10,
            2,
            "ext",
            "subject",
        )
        assert current_tenant_id.get() == 99
        assert not is_tenant_filter_bypassed()
        directory.find_account_bindings.assert_awaited_once_with("kl", 10)
    finally:
        current_tenant_id.reset(token)


@pytest.mark.parametrize("requested", ["alice", "ALICE", "Alice ", "", " ", "x" * 129])
async def test_collation_or_normalization_cannot_select_another_account(account_owner, requested):
    app, sessions, _ = account_owner
    await seed(sessions)
    with pytest.raises(KunlianIdentityUnavailableError):
        await app.resolve_account("kl", requested)
    assert not is_tenant_filter_bypassed()


@pytest.mark.parametrize("kwargs", [{"deleted": 1}, {"membership": False}, {"status": "disabled"}, {"active": None}])
async def test_disabled_or_missing_current_membership_is_refused(account_owner, kwargs):
    app, sessions, _ = account_owner
    await seed(sessions, **kwargs)
    with pytest.raises(KunlianIdentityUnavailableError):
        await app.resolve_account("kl", "Alice")


async def test_ambiguous_current_memberships_are_refused(account_owner):
    app, sessions, _ = account_owner
    await seed(sessions)
    app.repository.current_memberships = AsyncMock(return_value=[2, 3])
    with pytest.raises(KunlianIdentityUnavailableError):
        await app.resolve_account("kl", "Alice")


async def test_collation_candidates_do_not_hide_duplicate_exact_accounts(account_owner):
    app, sessions, _ = account_owner
    await seed(sessions, name="alice")
    async with sessions() as session:
        session.add(User(user_id=11, user_name="ALICE", password=""))
        session.add(User(user_id=12, user_name="Alice", password=""))
        session.add(User(user_id=13, user_name="Alice", password=""))
        await session.commit()
    matches = await app.repository.exact_accounts("Alice")
    assert len(matches) == 2
    assert {row.user_id for row in matches} == {12, 13}
    with pytest.raises(KunlianIdentityUnavailableError):
        await app.resolve_account("kl", "Alice")


async def test_directory_discovery_is_root_scoped_and_restored_on_error(account_owner):
    app, sessions, directory = account_owner
    await seed(sessions)

    async def unavailable(*args):
        assert current_tenant_id.get() == 1
        assert not is_tenant_filter_bypassed()
        raise RuntimeError("repository unavailable")

    directory.find_account_bindings.side_effect = unavailable
    token = current_tenant_id.set(99)
    try:
        with pytest.raises(RuntimeError, match="repository unavailable"):
            await app.resolve_account("kl", "Alice")
        assert current_tenant_id.get() == 99
        assert not is_tenant_filter_bypassed()
    finally:
        current_tenant_id.reset(token)


async def test_duplicate_exact_names_are_refused_even_when_one_disabled(account_owner):
    app, sessions, _ = account_owner
    await seed(sessions)
    async with sessions() as session:
        session.add(User(user_id=11, user_name="Alice", password="", delete=1))
        await session.commit()
    with pytest.raises(KunlianIdentityUnavailableError):
        await app.resolve_account("kl", "Alice")


@pytest.mark.parametrize(
    "failure", ["missing", "duplicate", "wrong_user", "wrong_connection", "wrong_tenant", "disabled_mapping"]
)
async def test_binding_or_internal_tenant_mapping_must_agree(account_owner, failure):
    app, sessions, directory = account_owner
    await seed(sessions)
    binding = directory.find_account_bindings.return_value[0]
    mapping = directory.get_tenant_binding.return_value
    if failure == "missing":
        directory.find_account_bindings.return_value = []
    elif failure == "duplicate":
        directory.find_account_bindings.return_value = [binding, binding]
    elif failure == "wrong_user":
        binding.local_user_id = 11
    elif failure == "wrong_connection":
        binding.connection_id = "other"
    elif failure == "wrong_tenant":
        mapping.local_tenant_id = 3
    else:
        mapping.enabled = False
    with pytest.raises(KunlianIdentityUnavailableError):
        await app.resolve_account("kl", "Alice")
    assert not is_tenant_filter_bypassed()
