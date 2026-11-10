"""Original creator/org/quota facts over native SQL, without M2 authority."""

import importlib
from dataclasses import FrozenInstanceError, fields
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.models.space_channel_member import SpaceChannelMember
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    tenant_execution_scope,
    visible_tenant_ids,
)
from bisheng.core.database import tenant_filter
from bisheng.database.models.department import Department
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.database.models.user_role import UserRole
from bisheng.user.domain.models.user import User

NOW = datetime(2026, 11, 7, 1, 2, 3, 456)
PAGED = {"memberships": UserTenant, "departments": Department, "roles": Role}
ALL_METHODS = (
    "aget_tenant",
    "alist_memberships",
    "alist_departments",
    "alist_roles",
    "alist_user_roles",
    "ainspect_users",
    "ainspect_roles",
    "avalidate_global_integrity",
)
SHAPES = {
    "tenant": {
        "id",
        "status",
        "parent_tenant_id",
        "root_dept_id",
        "share_default_to_children",
        "quota_config",
        "update_time",
    },
    "memberships": {"id", "user_id", "tenant_id", "is_default", "status", "is_active", "last_access_time", "join_time"},
    "departments": {
        "id",
        "tenant_id",
        "parent_id",
        "path",
        "status",
        "is_deleted",
        "is_tenant_root",
        "mounted_tenant_id",
        "update_time",
    },
    "roles": {
        "id",
        "tenant_id",
        "role_type",
        "department_id",
        "quota_config",
        "knowledge_space_file_limit",
        "update_time",
    },
    "user_roles": {"user_id", "role_id", "id", "tenant_id", "create_time", "update_time"},
    "creator": {"user_id", "exists", "delete"},
}


@pytest.fixture
def repo():
    return importlib.import_module(
        "bisheng.knowledge.domain.repositories.unification_control_repository"
    ).UnificationControlRepository()


@pytest.fixture
async def native(monkeypatch):
    models = (Tenant, UserTenant, Department, Role, UserRole, User, SpaceChannelMember)
    names = {
        model.__tablename__
        for model in models
        if "tenant_id" in model.__table__.c and model.__tablename__ not in tenant_filter._EXCLUDED_TABLES
    }
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(
        tenant_filter, "_tenant_aware_tables", (tenant_filter._tenant_aware_tables | names) - {"user_tenant"}
    )
    tenant_filter.register_tenant_filter_events()
    token = set_current_tenant_id(101)
    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = sa.MetaData()
    for model in models:
        table = model.__table__.to_metadata(metadata)
        if "tenant_id" in table.c:
            table.c.tenant_id.nullable = True  # legacy corruption without changing production metadata
        if model is UserRole:
            table.c.id.autoincrement = False  # SQLite cannot generate a component of a composite PK
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            Tenant.__table__.insert(),
            [{"id": ident, "tenant_code": f"t{ident}", "tenant_name": f"t{ident}"} for ident in (1, 101, 202)],
        )
    queries, writes, statements = [], [], []

    @sa.event.listens_for(engine.sync_engine, "before_cursor_execute")
    def statement_seen(_conn, _cursor, statement, parameters, context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append((statement, parameters))
            statements.append(context.compiled.statement)
        elif statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    async def insert(model, rows):
        async with engine.begin() as connection:
            await connection.execute(model.__table__.insert(), rows)

    try:
        yield type(
            "Native",
            (),
            {
                "engine": engine,
                "insert": staticmethod(insert),
                "queries": queries,
                "writes": writes,
                "statements": statements,
            },
        )()
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()


def row(kind, ident, tenant=101, **changes):
    common = {"id": ident, "tenant_id": tenant}
    return {
        "memberships": lambda: {
            **common,
            "user_id": ident + 10,
            "is_default": ident % 2,
            "is_active": None,
            "status": "disabled" if ident % 2 else "active",
            "last_access_time": NOW,
            "join_time": NOW,
        },
        "departments": lambda: {
            **common,
            "dept_id": f"d{tenant}-{ident}",
            "name": "private-department-name",
            "parent_id": 9999,
            "path": "/99/9999/",
            "status": "archived",
            "is_deleted": 1,
            "is_tenant_root": 1,
            "mounted_tenant_id": 202,
            "update_time": NOW,
        },
        "roles": lambda: {
            **common,
            "role_name": f"private-role-{tenant}-{ident}",
            "role_type": "global" if tenant == 1 else "tenant",
            "department_id": None,
            "quota_config": {"private-quota": {"knowledge_space": {"limit": ident}}},
            "knowledge_space_file_limit": 17,
            "update_time": NOW,
        },
        "user_roles": lambda: {
            **common,
            "user_id": 7,
            "role_id": 5,
            "create_time": NOW,
            "update_time": NOW,
        },
    }[kind]() | changes


async def call(repo, method, session):
    kwargs = {"ainspect_users": {"user_ids": (7,)}, "ainspect_roles": {"role_ids": (5,)}}.get(method, {})
    return await getattr(repo, method)(session, **kwargs)


def assert_page_sql(queries, size):
    assert all("LIMIT" in sql.upper() and "OFFSET ?" in sql.upper() for sql, _ in queries)
    assert all(params[-2:] == (size + 1, 0) for _, params in queries)
    assert all(" JOIN " not in sql.upper() for sql, _ in queries)


async def test_original_model_keys_and_native_fixture_preserve_composite_identity(native):
    assert tuple(col.name for col in UserRole.__table__.primary_key) == ("user_id", "role_id", "id")
    assert tuple(col.name for col in User.__table__.primary_key) == ("user_id",)
    assert "user_tenant" in tenant_filter._EXCLUDED_TABLES
    await native.insert(UserRole, [row("user_roles", 1), row("user_roles", 1, user_id=8)])
    async with AsyncSession(native.engine) as session, session.begin():
        assert len((await session.execute(sa.select(UserRole.user_id, UserRole.role_id, UserRole.id))).all()) == 2


@pytest.mark.parametrize("kind", PAGED)
async def test_sparse_401_rows_use_three_local_seek_pages_with_history_and_foreign_rows(repo, native, kind):
    ids = tuple(3 * n + 5 for n in range(401))
    await native.insert(
        PAGED[kind],
        [row(kind, ident) for ident in reversed(ids)] + [row(kind, 1, 1), row(kind, 3, 202), row(kind, 9999, 202)],
    )
    token = visible_tenant_ids.set(frozenset({1, 101, 202}))
    try:
        async with AsyncSession(native.engine) as session, session.begin():
            found, cursors, after = [], [], None
            while True:
                result = await getattr(repo, f"alist_{kind}")(session, after_id=after)
                assert isinstance(result.items, tuple)
                assert len(result.items) <= 200
                assert all(item.tenant_id == 101 for item in result.items)
                found.extend(item.id for item in result.items)
                if result.next_after is None:
                    break
                cursors.append(result.next_after)
                after = result.next_after
        assert tuple(found) == ids
        assert cursors == [ids[199], ids[399]]
        assert len(native.queries) == 3
        assert_page_sql(native.queries, 200)
        if kind == "memberships":
            assert all("user_tenant.tenant_id =" in sql for sql, _ in native.queries)
    finally:
        visible_tenant_ids.reset(token)


async def test_composite_seek_keeps_401_keys_including_same_id_different_user_and_role(repo, native):
    keys = tuple(sorted((10 + n // 200, 20 + (n // 100) % 2, 1 + n % 100) for n in range(401)))
    await native.insert(
        UserRole,
        [row("user_roles", ident, user_id=user, role_id=role) for user, role, ident in reversed(keys)]
        + [row("user_roles", 9999, 1, user_id=1), row("user_roles", 9999, 202, user_id=2)],
    )
    async with AsyncSession(native.engine) as session, session.begin():
        found, cursors, after = [], [], None
        while True:
            result = await repo.alist_user_roles(session, after_key=after)
            found.extend((item.user_id, item.role_id, item.id) for item in result.items)
            if result.next_after is None:
                break
            assert type(result.next_after) is tuple and len(result.next_after) == 3
            cursors.append(result.next_after)
            after = result.next_after
        with pytest.raises(FrozenInstanceError):
            result.next_after = (1, 2, 3)
        assert not hasattr(result, "__dict__")
    assert tuple(found) == keys and cursors == [keys[199], keys[399]]
    assert len(native.queries) == 3
    assert_page_sql(native.queries, 200)
    for sql, _ in native.queries[1:]:
        assert "userrole.user_id >" in sql and "userrole.role_id >" in sql and "userrole.id >" in sql
        assert " OR " in sql and " AND " in sql
        assert "ORDER BY userrole.user_id, userrole.role_id, userrole.id" in sql


async def test_closed_facts_preserve_raw_history_global_creators_and_private_quota(repo, native):
    await native.insert(
        User, [{"user_id": 7, "user_name": "private-user", "password": "private-credential", "delete": 1}]
    )
    await native.insert(
        UserTenant, [row("memberships", 1, user_id=7), row("memberships", 2, 202, user_id=7, is_active=1)]
    )
    await native.insert(Department, [row("departments", 1)])
    await native.insert(Role, [row("roles", 5), row("roles", 6, 1), row("roles", 7, 202)])
    await native.insert(UserRole, [row("user_roles", 1)])
    async with native.engine.begin() as connection:
        await connection.execute(
            sa.update(Tenant)
            .where(Tenant.id == 101)
            .values(
                status="archived",
                parent_tenant_id=1,
                root_dept_id=99,
                share_default_to_children=0,
                quota_config={"private-tenant-quota": {"knowledge_space": {"limit": 2}}},
                storage_config={"private-storage": "must-not-read"},
                update_time=NOW,
            )
        )
    async with AsyncSession(native.engine) as session, session.begin():
        tenant = await repo.aget_tenant(session)
        members = (await repo.alist_memberships(session)).items
        departments = (await repo.alist_departments(session)).items
        roles = (await repo.alist_roles(session)).items
        user_roles = (await repo.alist_user_roles(session)).items
        creators = await repo.ainspect_users(session, user_ids=(7, 99, 7))
        role_facts = await repo.ainspect_roles(session, role_ids=(6, 7, 99, 6))
        facts = {
            "tenant": tenant,
            "memberships": members[0],
            "departments": departments[0],
            "roles": roles[0],
            "user_roles": user_roles[0],
            "creator": creators[0],
        }
        for kind, fact in facts.items():
            assert {item.name for item in fields(fact)} == SHAPES[kind]
            assert not hasattr(fact, "__dict__")
            with pytest.raises(FrozenInstanceError):
                setattr(fact, next(iter(SHAPES[kind])), None)
            assert "private-" not in repr(fact)
        assert tenant.status == "archived" and tenant.parent_tenant_id == 1 and tenant.share_default_to_children == 0
        assert tenant.quota_config["private-tenant-quota"]["knowledge_space"]["limit"] == 2
        assert len(members) == 1 and members[0].is_active is None and members[0].status == "disabled"
        assert departments[0].is_deleted == 1 and departments[0].path == "/99/9999/"
        assert [item.id for item in roles] == [5]
        assert [(item.user_id, item.exists, item.delete) for item in creators] == [(7, True, 1), (99, False, None)]
        assert [(item.id, item.exists, item.tenant_id) for item in role_facts] == [
            (6, True, 1),
            (7, True, 202),
            (99, False, None),
        ]
        for fact in role_facts:
            assert {item.name for item in fields(fact)} == SHAPES["roles"] | {"exists"}
            assert "private-" not in repr(fact)
        assert role_facts[0].role_type == "global"
        assert role_facts[-1].quota_config is None and role_facts[-1].knowledge_space_file_limit is None
        tenant.quota_config["private-tenant-quota"]["knowledge_space"]["limit"] = 999
        roles[0].quota_config["private-quota"]["knowledge_space"]["limit"] = 999
        assert (await repo.aget_tenant(session)).quota_config["private-tenant-quota"]["knowledge_space"]["limit"] == 2
        assert (await repo.alist_roles(session)).items[0].quota_config["private-quota"]["knowledge_space"]["limit"] == 5
    selects = "\n".join(sql.lower().split("from")[0] for sql, _ in native.queries)
    for forbidden in ("password", "storage_config", "contact_", "user_name", "role_name", "remark", "default_role_ids"):
        assert forbidden not in selects


@pytest.mark.parametrize("kind", ["users", "roles"])
async def test_exact_global_500_deduplicated_ids_read_three_batches_in_input_order(repo, native, kind):
    if kind == "users":
        await native.insert(
            User,
            [
                {"user_id": ident, "user_name": "private-user", "password": "private-credential", "delete": ident % 2}
                for ident in range(1, 500)
            ],
        )
    else:
        await native.insert(Role, [row("roles", ident, 1 if ident % 2 else 202) for ident in range(1, 500)])
    ids = (*range(500, 0, -1), 500, 1, 250)
    async with AsyncSession(native.engine) as session, session.begin():
        method = getattr(repo, f"ainspect_{kind}")
        facts = await method(session, **{f"{'user' if kind == 'users' else 'role'}_ids": ids})
        assert [getattr(item, "user_id" if kind == "users" else "id") for item in facts] == list(range(500, 0, -1))
        assert not facts[0].exists and all(item.exists for item in facts[1:])
        assert len(native.queries) == 3
        assert [len(params) for _, params in native.queries] == [200, 200, 100]
        assert all(" IN (" in sql and " JOIN " not in sql.upper() for sql, _ in native.queries)
        before = len(native.queries)
        assert await method(session, **{f"{'user' if kind == 'users' else 'role'}_ids": ()}) == ()
        assert len(native.queries) == before


@pytest.mark.parametrize("kind", ["tenant", "roles", "exact_role"])
@pytest.mark.parametrize("bad", [{"private-nonfinite": float("nan")}, {"private-nonfinite": float("inf")}, "malformed"])
async def test_malformed_or_nonfinite_quota_json_fails_without_original_content(repo, native, kind, bad):
    model = Tenant if kind == "tenant" else Role
    ident = 101 if kind == "tenant" else 5
    if model is Role:
        await native.insert(Role, [row("roles", ident, 202 if kind == "exact_role" else 101)])
    async with native.engine.begin() as connection:
        if bad == "malformed":
            await connection.execute(
                sa.text(f"UPDATE {model.__tablename__} SET quota_config=:value WHERE id=:id"),
                {"value": "private-broken{", "id": ident},
            )
        else:
            await connection.execute(sa.update(model).where(model.id == ident).values(quota_config=bad))
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError) as error:
            if kind == "tenant":
                await repo.aget_tenant(session)
            elif kind == "roles":
                await repo.alist_roles(session)
            else:
                await repo.ainspect_roles(session, role_ids=(ident,))
        assert error.value.code == 10998
        assert "private-" not in str(error.value) and "private-" not in repr(error.value)


@pytest.mark.parametrize("kind", ["memberships", "departments", "roles", "user_roles"])
@pytest.mark.parametrize("tenant", [None, 0, -1, 999])
async def test_global_probes_detect_null_nonpositive_unknown_tenants_without_raw_personal_data(
    repo, native, kind, tenant
):
    model = PAGED.get(kind, UserRole)
    await native.insert(model, [row(kind, 17, tenant)])
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError) as error:
            await repo.avalidate_global_integrity(session)
        assert error.value.code == 10998
        assert "private-" not in str(error.value)
        assert error.value.kwargs["id"] == 17
        if kind == "user_roles":
            assert error.value.kwargs["user_id"] == 7 and error.value.kwargs["role_id"] == 5
    assert all("LIMIT" in sql.upper() and params[-2:] == (1, 0) for sql, params in native.queries)
    assert all(
        "private-" not in sql and "quota_config" not in sql and "password" not in sql for sql, _ in native.queries
    )


async def test_global_probes_once_then_tenant_pages_do_not_repeat_global_or_join_relations(repo, native):
    for kind, model in PAGED.items():
        await native.insert(model, [row(kind, 1), row(kind, 2, 202)])
    # Missing role/user/department parents are facts for later preflight, not hidden or authorized here.
    await native.insert(UserRole, [row("user_roles", 1), row("user_roles", 2, 202)])
    async with AsyncSession(native.engine) as session, session.begin():
        await repo.avalidate_global_integrity(session)
        assert len(native.queries) == 5  # Original four probes, then the genuine empty SPACE page.
        assert all("LEFT OUTER JOIN" in sql.upper() and params[-2:] == (1, 0) for sql, params in native.queries[:4])
        for tenant in (101, 202):
            with tenant_execution_scope(tenant):
                for kind in (*PAGED, "user_roles"):
                    assert len((await getattr(repo, f"alist_{kind}")(session)).items) == 1
        assert len(native.queries) == 13
    assert sum("LEFT OUTER JOIN" in sql.upper() for sql, _ in native.queries) == 4
    # Compile actual executed statement trees for MySQL; no connection or vendor-specific tuple seek.
    for statement in native.statements:
        compiled = str(statement.compile(dialect=mysql.dialect())).lower()
        assert "json_extract" not in compiled and "tuple(" not in compiled


@pytest.mark.parametrize("method", ALL_METHODS)
async def test_every_read_keeps_unrelated_new_and_dirty_caller_objects_unflushed(repo, native, method):
    await native.insert(Role, [row("roles", 5)])
    async with AsyncSession(native.engine) as session:
        async with session.begin():
            loaded = (await session.execute(sa.select(Role).where(Role.id == 5))).scalar_one()
            loaded.quota_config = {"private-pending": 88}
            pending = User(user_id=77, user_name="private-pending-user", password="-")
            session.add(pending)
            flushes = []
            sa.event.listen(session.sync_session, "before_flush", lambda *_: flushes.append(True))
            native.writes.clear()
            result = await call(repo, method, session)
            assert result is not None or method == "avalidate_global_integrity"
            assert not flushes and not native.writes
            assert pending in session.new and loaded in session.dirty
            assert session.in_transaction()
            with session.no_autoflush:
                original = (await session.execute(sa.select(Role.quota_config).where(Role.id == 5))).scalar_one()
            assert original == row("roles", 5)["quota_config"]
            await session.rollback()


@pytest.mark.parametrize("method", ALL_METHODS)
@pytest.mark.parametrize("invalid", ["no_transaction", "bypass", "missing_tenant"])
async def test_every_port_refuses_untrusted_scope_before_sql_or_autoflush(repo, native, method, invalid):
    async with AsyncSession(native.engine) as session:
        async with session.begin():
            pending = User(user_id=77, user_name="pending", password="-")
            if invalid == "no_transaction":
                await session.rollback()
            else:
                session.add(pending)
            flushes = []
            sa.event.listen(session.sync_session, "before_flush", lambda *_: flushes.append(True))
            native.queries.clear()
            native.writes.clear()
            if invalid == "bypass":
                with bypass_tenant_filter(), pytest.raises(KnowledgeOperationPlanConflictError):
                    await call(repo, method, session)
            elif invalid == "missing_tenant":
                token = set_current_tenant_id(None)
                try:
                    with pytest.raises(KnowledgeOperationPlanConflictError):
                        await call(repo, method, session)
                finally:
                    current_tenant_id.reset(token)
            else:
                with pytest.raises(KnowledgeOperationPlanConflictError):
                    await call(repo, method, session)
            assert not native.queries and not native.writes and not flushes
            if invalid != "no_transaction":
                assert pending in session.new
            await session.rollback()


@pytest.mark.parametrize("kind", PAGED)
@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 201}, {"limit": True}, {"after_id": 0}, {"after_id": "1"}])
async def test_scalar_pagers_refuse_invalid_bounds_before_io(repo, native, kind, kwargs):
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await getattr(repo, f"alist_{kind}")(session, **kwargs)
    assert not native.queries


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 201},
        {"limit": False},
        {"after_key": (1, 2)},
        {"after_key": [1, 2, 3]},
        {"after_key": (1, True, 3)},
        {"after_key": (1, 2, 0)},
    ],
)
async def test_composite_pager_refuses_noncanonical_keys_and_bounds(repo, native, kwargs):
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.alist_user_roles(session, **kwargs)
    assert not native.queries


@pytest.mark.parametrize("kind", ["users", "roles"])
@pytest.mark.parametrize("ids", [[1], (True,), (0,), (-1,), ("1",), tuple(range(1, 502))])
async def test_exact_facts_refuse_invalid_or_unbounded_keys_without_io(repo, native, kind, ids):
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await getattr(repo, f"ainspect_{kind}")(session, **{f"{'user' if kind == 'users' else 'role'}_ids": ids})
    assert not native.queries


async def test_missing_current_tenant_and_fake_session_fail_closed_without_credentials(repo, native):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await repo.aget_tenant(object())
    async with AsyncSession(native.engine) as session, session.begin():
        with tenant_execution_scope(999), pytest.raises(KnowledgeOperationPlanConflictError) as error:
            await repo.aget_tenant(session)
        assert error.value.code == 10998


async def test_nonpositive_or_bool_current_tenants_are_not_concrete_scope(repo, native):
    async with AsyncSession(native.engine) as session, session.begin():
        for tenant in (True, 0, -1, "101"):
            token = set_current_tenant_id(tenant)
            try:
                with pytest.raises(KnowledgeOperationPlanConflictError):
                    await repo.aget_tenant(session)
            finally:
                current_tenant_id.reset(token)
    assert not native.queries


async def test_invalid_stored_composite_key_fails_instead_of_being_dropped(repo, native):
    await native.insert(UserRole, [row("user_roles", 1, user_id=0)])
    async with AsyncSession(native.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.alist_user_roles(session)
