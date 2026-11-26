"""HTTP regression tests for multi-tenant Kunlian API key account disambiguation."""

from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import create_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.flow import Flow
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.open_api.application.kunlian_access import KunlianAccessService
from bisheng.open_api.domain.services.kunlian_credential import KunlianCredentialService
from bisheng.open_endpoints.api.endpoints.kunlian_workflow_api import router
from bisheng.sso_sync.domain.models.kunlian import KunlianConnectionState, KunlianIdentityBinding, KunlianTenantBinding
from bisheng.sso_sync.domain.repositories.kunlian import KunlianDirectoryRepository
from bisheng.user.application.kunlian_account import KunlianAccountApplication
from bisheng.user.domain.models.user import User
from bisheng.user.domain.repositories.kunlian_account import KunlianAccountRepository
from test.open_api.test_kunlian_credential import Store


@pytest.fixture
async def multi_tenant_kunlian_http(tmp_path):
    db_file = tmp_path / "kunlian_multi_tenant.db"
    async_url = f"sqlite+aiosqlite:///{db_file}"
    sync_url = f"sqlite:///{db_file}"

    async_engine = create_async_engine(async_url)
    sync_engine = create_engine(sync_url)
    tables = (
        User.__table__,
        Tenant.__table__,
        UserTenant.__table__,
        KunlianConnectionState.__table__,
        KunlianTenantBinding.__table__,
        KunlianIdentityBinding.__table__,
        Flow.__table__,
    )
    async with async_engine.begin() as conn:
        for table in tables:
            await conn.run_sync(table.create)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(async_engine, expire_on_commit=False) as session:
            yield session

    async with sessions() as session:
        session.add(KunlianConnectionState(connection_id="kunlian", enabled=True))
        session.add(Tenant(id=10, tenant_code="ten-a", tenant_name="Tenant A", parent_tenant_id=1, status="active"))
        session.add(Tenant(id=20, tenant_code="ten-b", tenant_name="Tenant B", parent_tenant_id=1, status="active"))
        session.add(Tenant(id=30, tenant_code="ten-c", tenant_name="Tenant C", parent_tenant_id=1, status="active"))
        session.add(
            KunlianTenantBinding(
                connection_id="kunlian",
                external_tenant_id="ext-a",
                external_tenant_name="Ext A",
                local_tenant_id=10,
                enabled=True,
                materialized=True,
                revision=1,
            )
        )
        session.add(
            KunlianTenantBinding(
                connection_id="kunlian",
                external_tenant_id="ext-b",
                external_tenant_name="Ext B",
                local_tenant_id=20,
                enabled=True,
                materialized=True,
                revision=1,
            )
        )
        session.add(User(user_id=101, user_name="alice", password="", delete=0, source="kunlian"))
        session.add(User(user_id=202, user_name="alice", password="", delete=0, source="kunlian"))
        session.add(UserTenant(user_id=101, tenant_id=10, status="active", is_active=1))
        session.add(UserTenant(user_id=202, tenant_id=20, status="active", is_active=1))
        session.add(
            KunlianIdentityBinding(
                identity_key="a" * 64,
                connection_id="kunlian",
                issuer="issuer",
                subject="sub-a",
                external_tenant_id="ext-a",
                member_id="mem-a",
                local_user_id=101,
                admission_status="ACTIVE",
                projection_status="SUCCEEDED",
                source_revision="r" * 64,
                projected_revision="r" * 64,
            )
        )
        session.add(
            KunlianIdentityBinding(
                identity_key="b" * 64,
                connection_id="kunlian",
                issuer="issuer",
                subject="sub-b",
                external_tenant_id="ext-b",
                member_id="mem-b",
                local_user_id=202,
                admission_status="ACTIVE",
                projection_status="SUCCEEDED",
                source_revision="r" * 64,
                projected_revision="r" * 64,
            )
        )
        session.add(Flow(id="wf_b_111111111111111111111111111", name="WF B", tenant_id=20, flow_type=10))
        session.add(Flow(id="wf_c_222222222222222222222222222", name="WF C", tenant_id=30, flow_type=10))
        await session.commit()

    credentials = KunlianCredentialService(Store())
    accounts = KunlianAccountApplication(KunlianAccountRepository(sessions), KunlianDirectoryRepository(sessions))

    tenant_by_subject = {("ext-a", "sub-a"): (101, 10), ("ext-b", "sub-b"): (202, 20)}

    async def resolve_identity(*, connection_id, external_tenant_id, external_user_id):
        uid, tid = tenant_by_subject[(external_tenant_id, external_user_id)]
        return SimpleNamespace(user_id=uid, tenant_id=tid)

    identities = SimpleNamespace(resolve=AsyncMock(side_effect=resolve_identity))

    async def list_workflows(user, **kwargs):
        return {"data": [{"tenant_id": user.tenant_id, "user_id": user.user_id}], "has_more": False}

    async def detail_workflow(user, workflow_id, *, for_edit=False):
        return {"workflow_id": workflow_id, "tenant_id": user.tenant_id, "user_id": user.user_id}

    async def resolve_wf_tenant(workflow_id):
        from sqlmodel import Session

        from bisheng.workflow.application import kunlian_workflow_api as wf_api_module
        from bisheng.workflow.domain.repositories import platform_agent as pa_module

        @contextmanager
        def _sync_ctx():
            with Session(sync_engine, expire_on_commit=False) as s:
                yield s

        original_repo = pa_module.PlatformAgentRepository

        class TestRepo(original_repo):
            def __init__(self):
                super().__init__(sessions=_sync_ctx)

        pa_module.PlatformAgentRepository = TestRepo
        try:
            return await wf_api_module.resolve_kunlian_workflow_tenant_id(workflow_id)
        finally:
            pa_module.PlatformAgentRepository = original_repo

    app = FastAPI()
    app.state.kunlian_access_service = KunlianAccessService(
        credentials,
        identities,
        account_resolver=accounts,
        privilege_reader=AsyncMock(return_value=(False, False)),
    )
    app.state.kunlian_request_limiter = AsyncMock()
    app.state.kunlian_audit_service = SimpleNamespace(begin=AsyncMock(return_value="audit"), finish=AsyncMock())
    app.state.kunlian_workflow_api = SimpleNamespace(list=list_workflows, detail=detail_workflow)
    app.state.kunlian_workflow_tenant_resolver = resolve_wf_tenant
    app.include_router(router)
    try:
        yield app, credentials
    finally:
        sync_engine.dispose()
        await async_engine.dispose()


async def test_scoped_key_disambiguates_same_user_without_header(multi_tenant_kunlian_http):
    app, credentials = multi_tenant_kunlian_http
    issued = await credentials.issue(
        is_global_super=True,
        created_by=1,
        connection_id="kunlian",
        integration_id="e2e-mt",
        tenant_ids=["ext-b"],
        capabilities=["read"],
    )
    headers = {"Authorization": "Bearer " + issued["api_key"]}
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        res = await client.get("/api/v2/kunlian/workflows", headers=headers, params={"user_account": "alice"})
        assert res.status_code == 200
        assert res.json()["data"]["data"] == [{"tenant_id": 20, "user_id": 202}]


async def test_wildcard_key_uses_workflow_id_and_optional_header(multi_tenant_kunlian_http):
    app, credentials = multi_tenant_kunlian_http
    issued = await credentials.issue(
        is_global_super=True,
        created_by=1,
        connection_id="kunlian",
        integration_id="e2e-mt",
        tenant_ids=["*"],
        capabilities=["read"],
    )
    headers = {"Authorization": "Bearer " + issued["api_key"]}
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        # List without X-Kunlian-Tenant-Id fails closed when multiple tenants match.
        ambiguous = await client.get("/api/v2/kunlian/workflows", headers=headers, params={"user_account": "alice"})
        assert ambiguous.status_code == 403

        # List with X-Kunlian-Tenant-Id targets exact external tenant.
        by_header = await client.get(
            "/api/v2/kunlian/workflows",
            headers={**headers, "X-Kunlian-Tenant-Id": "ext-a"},
            params={"user_account": "alice"},
        )
        assert by_header.status_code == 200
        assert by_header.json()["data"]["data"] == [{"tenant_id": 10, "user_id": 101}]

        # Path carrying workflow_id auto-locates tenant 20 without X-Kunlian-Tenant-Id.
        by_workflow = await client.get(
            "/api/v2/kunlian/workflows/wf_b_111111111111111111111111111",
            headers=headers,
            params={"user_account": "alice"},
        )
        assert by_workflow.status_code == 200
        assert by_workflow.json()["data"] == {
            "workflow_id": "wf_b_111111111111111111111111111",
            "tenant_id": 20,
            "user_id": 202,
        }

        # Workflow in unrelated tenant fails closed.
        other_tenant = await client.get(
            "/api/v2/kunlian/workflows/wf_c_222222222222222222222222222",
            headers=headers,
            params={"user_account": "alice"},
        )
        assert other_tenant.status_code == 403

        # Malformed header is rejected as invalid input.
        bad_header = await client.get(
            "/api/v2/kunlian/workflows",
            headers={**headers, "X-Kunlian-Tenant-Id": "   "},
            params={"user_account": "alice"},
        )
        assert bad_header.status_code == 422
