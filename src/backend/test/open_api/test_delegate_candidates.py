"""Candidate filtering and writes must agree, including inactive membership rows."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.open_api import OpenApiDelegateConfigurationInvalidError
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import UserTenant
from bisheng.open_api.api.dependencies import get_service_account_admin
from bisheng.open_api.api.endpoints.service_account_keys import router
from bisheng.open_api.domain.models.service_account import ServiceAccount
from bisheng.open_api.domain.schemas.credential import DelegateScopeInput
from bisheng.open_api.domain.services.delegate_scope_service import DelegateScopeService
from bisheng.user.domain.models.user import User


@pytest.fixture
async def candidates_db(open_api_db):
    async with open_api_db() as session:
        # 1 is valid; 2/3 are disabled/deleted; 4 has no tenant; 5/6 have an
        # inactive/historical membership; 7 belongs to a different tenant.
        for user_id in range(1, 8):
            session.add(
                User(user_id=user_id, user_name=f"user-{user_id}", password="x", delete={2: 1, 3: 2}.get(user_id, 0))
            )
            if user_id != 4:
                session.add(
                    UserTenant(
                        user_id=user_id,
                        tenant_id=2 if user_id == 7 else 1,
                        status="disabled" if user_id == 5 else "active",
                        is_active=None if user_id == 6 else 1,
                    )
                )
        # An active historical tenant row must not override the current tenant.
        session.add(UserTenant(user_id=7, tenant_id=1, status="active", is_active=None))
        for department_id in range(1, 5):
            session.add(
                Department(
                    id=department_id,
                    dept_id=f"dept-{department_id}",
                    name=f"Department {department_id}",
                    tenant_id=2 if department_id == 4 else 1,
                    status="archived" if department_id == 2 else "active",
                    is_deleted=int(department_id == 3),
                )
            )
        session.add(ServiceAccount(id=3, name="candidate-test", tenant_id=1, resource_owner_user_id=1))
        await session.commit()
    return open_api_db


@pytest.mark.parametrize(
    ("kind", "subject_id", "valid"),
    [("user", i, i == 1) for i in range(1, 9)] + [("department", i, i == 1) for i in range(1, 6)],
)
async def test_candidate_eligibility_matches_save(candidates_db, kind, subject_id, valid):
    entries = [DelegateScopeInput(subject_type=kind, subject_id=subject_id)]
    filtered = await DelegateScopeService.filter_entries(tenant_id=1, entries=entries)
    assert filtered == (((kind, subject_id),) if valid else ())
    if valid:
        assert await DelegateScopeService.validate_entries(tenant_id=1, entries=entries) == filtered
    else:
        with pytest.raises(OpenApiDelegateConfigurationInvalidError):
            await DelegateScopeService.validate_entries(tenant_id=1, entries=entries)


async def test_mixed_candidate_request_uses_account_tenant_and_deduplicates(candidates_db):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    # A global administrator's own tenant must not determine candidate eligibility.
    app.dependency_overrides[get_service_account_admin] = lambda: SimpleNamespace(tenant_id=2)
    entries = [{"subject_type": "user", "subject_id": i} for i in range(1, 9)]
    entries += [{"subject_type": "department", "subject_id": i} for i in range(1, 6)]
    entries += [entries[0]]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/service-accounts/3/delegate-candidates:filter", json=entries)
    assert response.status_code == 200
    assert response.json()["data"] == [
        {"subject_type": "user", "subject_id": 1},
        {"subject_type": "department", "subject_id": 1},
    ]


async def test_save_rechecks_state_after_candidates_were_loaded(candidates_db):
    entries = [DelegateScopeInput(subject_type="user", subject_id=1)]
    assert await DelegateScopeService.filter_entries(tenant_id=1, entries=entries) == (("user", 1),)
    async with candidates_db() as session:
        user = await session.get(User, 1)
        user.delete = 1
        await session.commit()
    with pytest.raises(OpenApiDelegateConfigurationInvalidError):
        await DelegateScopeService.validate_entries(tenant_id=1, entries=entries)


async def test_many_valid_users_across_query_batches_remain_selectable(candidates_db):
    async with candidates_db() as session:
        for user_id in range(100, 601):
            session.add(User(user_id=user_id, user_name=f"user-{user_id}", password="x", delete=0))
            session.add(UserTenant(user_id=user_id, tenant_id=1, status="active", is_active=1))
        await session.commit()
    entries = [DelegateScopeInput(subject_type="user", subject_id=i) for i in range(100, 601)]
    assert len(await DelegateScopeService.validate_entries(tenant_id=1, entries=entries)) == 501
