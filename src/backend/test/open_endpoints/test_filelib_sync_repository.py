import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.open_endpoints.domain.repositories.implementations import filelib_sync_repository_impl as repository_module
from bisheng.open_endpoints.domain.repositories.implementations.filelib_sync_repository_impl import (
    FilelibSyncRepositoryImpl,
)


class LookupUser(SQLModel, table=True):
    __tablename__ = "filelib_lookup_user"

    user_id: int = Field(primary_key=True)
    user_name: str
    external_id: str | None = None
    external_code: str | None = None
    delete: int = 0


class LookupUserTenant(SQLModel, table=True):
    __tablename__ = "filelib_lookup_user_tenant"

    user_id: int = Field(primary_key=True)
    tenant_id: int = Field(primary_key=True)
    status: str
    is_active: int | None = None


@pytest.mark.parametrize("field", ["external_id", "external_code"])
async def test_responsible_user_lookup_preserves_active_tenant_scope(field: str, monkeypatch):
    # Shared test setup mocks User; execute the real repository query against isolated tables.
    monkeypatch.setattr(repository_module, "User", LookupUser)
    monkeypatch.setattr(repository_module, "UserTenant", LookupUserTenant)
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(LookupUser.__table__.create)
            await connection.run_sync(LookupUserTenant.__table__.create)
        async with AsyncSession(engine) as session:
            for user_id, tenant_id, deleted, status, active in [
                (1, 1, 0, "active", 1),
                (2, 2, 0, "active", 1),
                (3, 1, 1, "active", 1),
                (4, 1, 0, "disabled", 1),
                (5, 1, 0, "active", None),
                (6, 1, 0, "active", 1),
            ]:
                session.add(
                    LookupUser(
                        user_id=user_id,
                        user_name=f"user-{user_id}",
                        delete=deleted,
                        **{field: "EMP001"},
                    )
                )
                session.add(LookupUserTenant(user_id=user_id, tenant_id=tenant_id, status=status, is_active=active))
            await session.commit()
            repository = FilelibSyncRepositoryImpl(session)
            lookup = getattr(repository, f"find_users_by_{field}")

            matches = await lookup(" EMP001 ", tenant_id=1)

            assert {user.user_id for user in matches} == {1, 6}
            assert await lookup("missing", tenant_id=1) == []
    finally:
        await engine.dispose()
