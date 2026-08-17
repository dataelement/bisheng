"""Service accounts are granted from their own detail page only (F049 T018, pairs with T019).

The resource side has two independent doors and both must be closed, because
closing one still leaves the other wide open (design D7 / pit 9):

* the **picker query** ``grant_subject_service.list_candidate_users`` — its own
  SQL, not ``/user/list``, so the DAO default of T016 does not reach it;
* the **subject validation layer** ``canonical_source`` — a direct
  ``POST …/grants:mutate`` names a subject id and never opens a picker.

The subject-side endpoint (T065) is the single sanctioned path, and it says so
explicitly by passing ``allow_service_account_subject=True`` through the
application layer — the permission domain still knows nothing about "service
accounts", it only sees ``user_type`` and one explicit parameter (C4).

覆盖 AC: AC-16 (invisible in every people picker, still displayable once granted).
"""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.open_api import ServiceAccountNotGrantSubjectError
from bisheng.permission.domain.services.grant_subject_service import (
    GrantSubjectScope,
    list_candidate_users,
)
from bisheng.tenant.domain.services.f048_permission_subject import TenantPermissionSubjectDirectory
from bisheng.user.domain.models.user import USER_TYPE_HUMAN, USER_TYPE_SERVICE, User

TENANT_ID = 1
HUMAN_ID = 80001
SERVICE_ID = 80002

_SUBJECT_MODULE = "bisheng.tenant.domain.services.f048_permission_subject"
_GRANT_SUBJECT_MODULE = "bisheng.permission.domain.services.grant_subject_service"


@pytest.fixture()
async def subject_db(monkeypatch):
    """A tiny user / tenant / department database bound into ``grant_subject_service``."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.database.models.tenant import UserTenant

    importlib.import_module("bisheng.database.models.department")
    importlib.import_module("bisheng.database.models.tenant")
    importlib.import_module("bisheng.user.domain.models.user")

    wanted = ("user", "user_tenant", "department", "user_department")
    tables = [SQLModel.metadata.tables[name] for name in wanted if name in SQLModel.metadata.tables]
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables))

    @asynccontextmanager
    async def _session():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    monkeypatch.setattr(f"{_GRANT_SUBJECT_MODULE}.get_async_db_session", _session)

    async with _session() as session:
        session.add(User(user_id=HUMAN_ID, user_name="alice", password="x", user_type=USER_TYPE_HUMAN, delete=0))
        session.add(
            User(
                user_id=SERVICE_ID,
                user_name="ci-bot",
                password="x",
                user_type=USER_TYPE_SERVICE,
                source="service_account",
                delete=0,
            )
        )
        await session.flush()
        for user_id in (HUMAN_ID, SERVICE_ID):
            session.add(UserTenant(user_id=user_id, tenant_id=TENANT_ID, status="active", is_active=1))
        await session.commit()

    yield _session
    await engine.dispose()


# ---------------------------------------------------------------------------
# Picker query
# ---------------------------------------------------------------------------


async def test_list_candidate_users_excludes_service(subject_db):
    """AC-16: the resource-side grant dialog runs its own query — it must filter too (pit 9)."""
    candidates = await list_candidate_users(
        GrantSubjectScope(tenant_id=TENANT_ID, department_path=None),
        keyword="",
        page=1,
        page_size=50,
    )
    assert [row["user_id"] for row in candidates] == [HUMAN_ID]

    # …including when the admin types the account's exact name.
    by_name = await list_candidate_users(
        GrantSubjectScope(tenant_id=TENANT_ID, department_path=None),
        keyword="ci-bot",
        page=1,
        page_size=50,
    )
    assert by_name == []


async def test_display_names_still_resolves_service_account():
    """AC-16 "displayable, not selectable": an already-granted account must render its name."""
    directory = TenantPermissionSubjectDirectory()
    rows = [
        User(user_id=SERVICE_ID, user_name="ci-bot", password="x", user_type=USER_TYPE_SERVICE),
        User(user_id=HUMAN_ID, user_name="alice", password="x", user_type=USER_TYPE_HUMAN),
    ]
    with patch(f"{_SUBJECT_MODULE}.UserDao") as user_dao:
        user_dao.aget_user_by_ids = AsyncMock(return_value=rows)
        names = await directory.display_names((("user", str(SERVICE_ID)), ("user", str(HUMAN_ID))))
    assert names[("user", str(SERVICE_ID))] == "ci-bot"
    assert names[("user", str(HUMAN_ID))] == "alice"


# ---------------------------------------------------------------------------
# Subject validation layer
# ---------------------------------------------------------------------------


def _active_tenant_rows(user_id: int):
    return [type("Row", (), {"tenant_id": TENANT_ID, "status": "active", "is_active": 1, "user_id": user_id})()]


async def _canonical(user_id: int, user_type: str, **kwargs):
    directory = TenantPermissionSubjectDirectory()
    row = User(user_id=user_id, user_name="x", password="x", user_type=user_type)
    with (
        patch(f"{_SUBJECT_MODULE}.UserTenantDao") as tenant_dao,
        patch(f"{_SUBJECT_MODULE}.UserDao") as user_dao,
    ):
        tenant_dao.aget_user_tenants = AsyncMock(return_value=_active_tenant_rows(user_id))
        user_dao.aget_user = AsyncMock(return_value=row)
        return await directory.canonical_source(
            tenant_id=TENANT_ID,
            source_id=1,
            subject_type="user",
            subject_id=str(user_id),
            userset_relation=None,
            include_children=False,
            **kwargs,
        )


async def test_canonical_source_rejects_service_account_subject_26029():
    """INV-29: the resource side can never author a grant for a service account."""
    with pytest.raises(ServiceAccountNotGrantSubjectError) as excinfo:
        await _canonical(SERVICE_ID, USER_TYPE_SERVICE)
    assert excinfo.value.code == 26029

    # Natural persons are untouched by the new condition.
    record = await _canonical(HUMAN_ID, USER_TYPE_HUMAN)
    assert record.subject_id == str(HUMAN_ID) and record.source_type == "DIRECT"


async def test_canonical_source_allows_when_explicit_flag():
    """The subject-side page (T065) opts in explicitly — the only sanctioned path."""
    record = await _canonical(SERVICE_ID, USER_TYPE_SERVICE, allow_service_account_subject=True)
    assert record.subject_type == "user" and record.subject_id == str(SERVICE_ID)
    assert record.source_type == "DIRECT"


async def test_mutate_grants_forwards_the_explicit_flag():
    """D6 W2: the flag travels application layer → Port → ``canonical_source``, defaulting to off."""
    from bisheng.permission.application.resource_api import F048ResourcePermissionApi
    from bisheng.permission.domain.schemas.f048 import (
        GrantMutationChange,
        GrantMutationOperation,
        GrantMutationRequest,
        GrantSubjectInput,
    )
    from bisheng.permission.domain.services.grant_source_service import GrantSourceService

    seen: list[bool] = []
    sources = GrantSourceService()

    class _Subjects:
        async def canonical_source(self, *, allow_service_account_subject: bool = False, **kwargs):
            seen.append(allow_service_account_subject)
            return sources.canonicalize_source(
                source_id=kwargs["source_id"],
                subject_type=kwargs["subject_type"],
                subject_id=kwargs["subject_id"],
                source_type="DIRECT",
                userset_relation=kwargs["userset_relation"],
                include_children=kwargs["include_children"],
            )

        async def actor_projected_subjects(self, actor):
            return frozenset()

        async def display_names(self, subjects):
            return {}

        async def resource_display_names(self, resources):
            return {}

    class _Runtime:
        async def allocate_source_ids(self, count):
            return list(range(1, count + 1))

        async def mutate_grants(self, **kwargs):
            # ``grants`` drives the response projection; an empty roster is
            # enough — this test is about what reaches ``canonical_source``.
            return type("Outcome", (), {"grants": (), "resource_version": 1})()

    class _Resources:
        async def resolve(self, **kwargs):
            return type("Target", (), {"tenant_id": TENANT_ID, "resource_type": "knowledge_library"})()

    api = F048ResourcePermissionApi(resources=_Resources(), runtime=_Runtime(), subjects=_Subjects())
    request = GrantMutationRequest(
        idempotency_key="k1",
        expected_resource_version=0,
        expected_catalog_release_id=1,
        changes=(
            GrantMutationChange(
                op=GrantMutationOperation.ADD,
                model_key="editor",
                subject=GrantSubjectInput(type="user", id=str(SERVICE_ID)),
            ),
        ),
    )
    actor = type("Actor", (), {"user_id": 1, "current_tenant_id": TENANT_ID})()

    await api.mutate_grants(resource_type="knowledge_library", resource_id="7", actor=actor, request=request)
    assert seen == [False], "the resource side must never opt in"

    await api.mutate_grants(
        resource_type="knowledge_library",
        resource_id="7",
        actor=actor,
        request=request,
        allow_service_account_subject=True,
    )
    assert seen == [False, True]
