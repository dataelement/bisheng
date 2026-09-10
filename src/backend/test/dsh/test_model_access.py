"""Model-centric administration: scoped SQL projections and authenticated API wiring."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine
from sqlmodel import Session

from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.model_access import DshModelAccessRepository
from bisheng.dsh.domain.services.admin import DshManagementService
from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.user.domain.models.user import User
from bisheng.user.domain.repositories.dsh_profile import UserDshProfileRepository


@pytest.fixture
def model_access_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'model-access.db'}")
    for model in (Tenant, User, UserTenant, DshUserPolicy):
        model.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(
            Tenant.__table__.insert(),
            [
                {
                    "id": tenant,
                    "tenant_code": f"e2e-dsh-{tenant}",
                    "tenant_name": f"Tenant {tenant}",
                    "status": "active",
                }
                for tenant in (2, 3)
            ],
        )
        connection.execute(
            User.__table__.insert(),
            [
                {"user_id": user, "user_name": name, "password": "not-a-login-credential", "delete": int(user == 25)}
                for user, name in [
                    (20, "e2e-dsh-first-login"),
                    (21, "e2e-dsh-existing"),
                    (22, "foreign"),
                    (23, "inactive"),
                    (24, "historical"),
                    (25, "disabled"),
                    (26, "e2e-dsh-percent%"),
                ]
            ],
        )
        connection.execute(
            UserTenant.__table__.insert(),
            [
                {
                    "user_id": user,
                    "tenant_id": 3 if user == 22 else 2,
                    "is_active": None if user == 24 else 1,
                    "status": "disabled" if user == 23 else "active",
                }
                for user in range(20, 27)
            ],
        )
        connection.execute(
            DshUserPolicy.__table__.insert(),
            [
                {
                    "tenant_id": tenant,
                    "user_id": 21,
                    "updated_by": 90,
                    "version": 3,
                    "model_id": model,
                    "monthly_token_limit": 900,
                    "enabled": 1,
                }
                for tenant, model in [(2, 7), (3, 999)]
            ],
        )
    yield engine
    engine.dispose()


def test_users_with_and_without_policy_are_listed_independently_of_dsh_sessions(model_access_db):
    with Session(model_access_db) as session, profile_scope(2):
        repository = DshModelAccessRepository(session)
        first = repository.users(model_id=7, rows=UserDshProfileRepository.access_users(session, limit=1), limit=1)
        assert first["items"] == [
            {
                "user_id": 20,
                "user_name": "e2e-dsh-first-login",
                "version": 0,
                "enabled": False,
                "monthly_token_limit": 0,
                "pending_operation_id": None,
            }
        ]
        assert first["has_more"] and first["next_cursor"] == "20"
        second = repository.users(
            model_id=7, rows=UserDshProfileRepository.access_users(session, after_user_id=20), limit=20
        )
        assert [row["user_id"] for row in second["items"]] == [21, 26]
        assert second["items"][0]["monthly_token_limit"] == 900
        assert not second["has_more"] and second["next_cursor"] is None
        assert (
            repository.users(model_id=7, rows=UserDshProfileRepository.access_users(session, keyword="first-login"))[
                "items"
            ]
            == first["items"]
        )
        assert [
            row["user_id"]
            for row in repository.users(model_id=7, rows=UserDshProfileRepository.access_users(session, keyword="%"))[
                "items"
            ]
        ] == [26]
    with Session(model_access_db) as session, profile_scope(3):
        assert [
            row["user_id"]
            for row in DshModelAccessRepository(session).users(
                UserDshProfileRepository.access_users(session), model_id=7
            )["items"]
        ] == [22]


async def test_model_users_service_authorizes_tenant_before_any_query():
    from bisheng.core.context.tenant import get_current_tenant_id

    async def view(model_id, **kwargs):
        assert get_current_tenant_id() == 2
        assert model_id == 7 and kwargs == {
            "after_user_id": 20,
            "limit": 10,
            "keyword": "test",
            "authorized_only": False,
        }
        return {"tenant_id": 2}

    authorize = AsyncMock(return_value=({}, 2))
    reader = AsyncMock(side_effect=view)
    service = DshManagementService(
        repository_scope=None,
        gateway=None,
        authorize=authorize,
        profiles=None,
        policy=None,
        policy_view=None,
        now=None,
        model_users_view=reader,
    )
    with profile_scope(1):
        assert await service.model_users(90, 7, tenant_id=2, cursor="20", limit=10, keyword="test") == {"tenant_id": 2}
    authorize.assert_awaited_once_with(90, 2)
    authorize.side_effect = HTTPException(403, "Denied")
    with pytest.raises(HTTPException) as denied:
        await service.model_users(91, 7, tenant_id=3)
    assert denied.value.status_code == 403 and reader.await_count == 1


async def test_model_users_route_uses_verified_actor_and_validates_query():
    from bisheng.dsh.api.endpoints import admin

    app = FastAPI()
    app.include_router(admin.router, prefix="/api/v1")
    service = SimpleNamespace(model_users=AsyncMock(return_value={"items": []}))
    app.dependency_overrides[admin.admin_user] = lambda: SimpleNamespace(user_id=90)
    app.dependency_overrides[admin.get_management] = lambda: service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/dsh/admin/models/7/users?tenant_id=2&keyword=first&limit=20")
        assert response.status_code == 200 and response.json()["status_code"] == 200
        assert set(response.json()) >= {"status_code", "status_message", "data"}
        service.model_users.assert_awaited_once_with(
            90, 7, tenant_id=2, cursor=None, limit=20, keyword="first", authorized_only=False
        )
        for query in ("limit=101", "cursor=-1", "cursor=invalid", "cursor=9223372036854775808"):
            assert (await client.get("/api/v1/dsh/admin/models/7/users?" + query)).status_code == 422
        assert service.model_users.await_count == 1

        async def denied():
            raise HTTPException(403, "Tenant administrator required")

        app.dependency_overrides[admin.admin_user] = denied
        assert (await client.get("/api/v1/dsh/admin/models/7/users")).status_code == 403
        assert service.model_users.await_count == 1


def test_authorized_model_query_uses_only_enabled_rows_and_model_prefix_index(model_access_db):
    from sqlalchemy import inspect

    with Session(model_access_db) as session, profile_scope(2):
        repo = DshModelAccessRepository(session)
        assert repo.authorized_user_ids(7) == [21]
        assert repo.authorized_user_ids(999) == []
        assert repo.authorized_user_ids(7, after_user_id=21) == []
    indexes = inspect(model_access_db).get_indexes("dsh_user_policy")
    assert any(index["column_names"] == ["tenant_id", "model_id", "enabled", "user_id"] for index in indexes)
