"""Fresh-install seeding contract for the F048 permission Catalog.

Covers the gap where a brand-new deployment (no legacy data, so the forward-only
data migration never runs) would otherwise start with zero CURRENT
``permission_catalog_release`` rows and fail the permission runtime with
"Permission Catalog must have exactly one CURRENT release".
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.permission.application import catalog_bootstrap
from bisheng.permission.application import control_state as control_state_module
from bisheng.permission.application import sql_runtime as sql_runtime_module
from bisheng.permission.application.catalog_bootstrap import (
    normalize_environment,
    seed_initial_permission_catalog,
)
from bisheng.permission.application.sql_runtime import SqlCatalogDecisionState
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionAction,
    PermissionCatalogRelease,
    PermissionModel,
    PermissionModelAction,
)
from bisheng.permission.migration.f048_coordinator import (
    INITIAL_CATALOG_RELEASE_KEY,
)

TABLE_NAMES = (
    "authorization_model_release",
    "permission_catalog_release",
    "permission_action",
    "permission_action_resource_scope",
    "permission_model",
    "permission_model_action",
)

STORE_ID = "store-fresh"
MODEL_ID = "model-fresh"
MODEL_CHECKSUM = "a" * 64


class FakeFGA:
    """Minimal OpenFGA write surface with the seeder's exact call shape."""

    store_id = STORE_ID
    model_id = MODEL_ID

    def __init__(self) -> None:
        self.tuples: set[tuple[str, str, str]] = set()
        self.write_calls = 0

    async def write_tuples(
        self,
        writes: list[dict] | None = None,
        deletes: list[dict] | None = None,
        *,
        ignore_duplicate_writes: bool = False,
    ) -> None:
        assert ignore_duplicate_writes is True
        self.write_calls += 1
        for row in writes or ():
            self.tuples.add((row["user"], row["relation"], row["object"]))


@pytest.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata = sa.MetaData()
    for name in TABLE_NAMES:
        cloned = SQLModel.metadata.tables[name].to_metadata(metadata)
        # BigInteger does not autoincrement on sqlite; use Integer for the PK.
        cloned.c.id.type = sa.Integer()
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    yield factory
    await engine.dispose()


@pytest.fixture(autouse=True)
def _bind_session(session_factory, monkeypatch):
    for module in (catalog_bootstrap, control_state_module, sql_runtime_module):
        monkeypatch.setattr(module, "get_async_db_session", session_factory)
    return session_factory


async def _count(session_factory, model) -> int:
    async with session_factory() as session:
        rows = (await session.execute(select(model))).scalars().all()
    return len(rows)


@pytest.mark.asyncio
async def test_seed_creates_single_current_catalog_on_fresh_install(session_factory):
    fga = FakeFGA()

    seeded = await seed_initial_permission_catalog(
        fga,
        store_id=STORE_ID,
        model_id=MODEL_ID,
        model_checksum=MODEL_CHECKSUM,
        environment="prod",
    )

    assert seeded is True

    async with session_factory() as session:
        releases = (await session.execute(select(PermissionCatalogRelease))).scalars().all()
        auth = (await session.execute(select(AuthorizationModelRelease))).scalars().all()

    assert len(releases) == 1
    release = releases[0]
    assert release.release_key == INITIAL_CATALOG_RELEASE_KEY
    assert release.status == "CURRENT"
    assert release.write_fenced is False

    assert len(auth) == 1
    assert auth[0].status == "ACTIVE"
    assert auth[0].store_id == STORE_ID
    assert auth[0].model_id == MODEL_ID
    assert auth[0].activated_at is not None
    assert release.required_authorization_model_release_id == auth[0].id

    # 12 registered actions, 4 standard models, and the catalog graph in FGA.
    assert await _count(session_factory, PermissionAction) == 12
    assert await _count(session_factory, PermissionModel) == 4
    assert await _count(session_factory, PermissionModelAction) > 0
    assert ("user:*", "active", f"permission_catalog_release:{INITIAL_CATALOG_RELEASE_KEY}") in fga.tuples


@pytest.mark.asyncio
async def test_seed_makes_runtime_ready(session_factory):
    """The seeded state satisfies the exact checks that raised at startup."""

    await seed_initial_permission_catalog(
        FakeFGA(),
        store_id=STORE_ID,
        model_id=MODEL_ID,
        model_checksum=MODEL_CHECKSUM,
        environment="prod",
    )

    decision = SqlCatalogDecisionState(
        expected_store_id=STORE_ID,
        expected_model_id=MODEL_ID,
    )
    # Previously raised PermissionPublishNotReadyError("... exactly one CURRENT release").
    await decision.ensure_runtime_ready()

    snapshot = await control_state_module.SqlPermissionControlState().current_catalog()
    assert snapshot.store_id == STORE_ID
    assert snapshot.model_id == MODEL_ID


@pytest.mark.asyncio
async def test_seed_is_idempotent(session_factory):
    fga = FakeFGA()
    first = await seed_initial_permission_catalog(
        fga,
        store_id=STORE_ID,
        model_id=MODEL_ID,
        model_checksum=MODEL_CHECKSUM,
        environment="prod",
    )
    second = await seed_initial_permission_catalog(
        fga,
        store_id=STORE_ID,
        model_id=MODEL_ID,
        model_checksum=MODEL_CHECKSUM,
        environment="prod",
    )

    assert first is True
    assert second is False
    # No duplicate control-plane rows after the second run.
    assert await _count(session_factory, PermissionCatalogRelease) == 1
    assert await _count(session_factory, AuthorizationModelRelease) == 1
    assert await _count(session_factory, PermissionAction) == 12
    assert await _count(session_factory, PermissionModel) == 4


@pytest.mark.asyncio
async def test_seed_skips_when_release_already_present(session_factory):
    """An upgrade-migrated environment already has the release: no-op, no writes."""

    async with session_factory() as session:
        async with session.begin():
            auth = AuthorizationModelRelease(
                environment="prod",
                store_id=STORE_ID,
                model_version="f048-v2",
                model_id=MODEL_ID,
                model_checksum=MODEL_CHECKSUM,
                required_relations_checksum="b" * 64,
                openfga_version="1.15.1",
                status="ACTIVE",
            )
            session.add(auth)
            await session.flush()
            session.add(
                PermissionCatalogRelease(
                    release_key=INITIAL_CATALOG_RELEASE_KEY,
                    version=1,
                    status="CURRENT",
                    write_fenced=False,
                    required_authorization_model_release_id=int(auth.id),
                    draft_owner_id=0,
                    idempotency_key="f048-migration-1",
                    checksum="c" * 64,
                )
            )

    fga = FakeFGA()
    seeded = await seed_initial_permission_catalog(
        fga,
        store_id=STORE_ID,
        model_id=MODEL_ID,
        model_checksum=MODEL_CHECKSUM,
        environment="prod",
    )

    assert seeded is False
    assert fga.write_calls == 0
    assert await _count(session_factory, PermissionCatalogRelease) == 1


@pytest.mark.asyncio
async def test_seed_returns_false_without_a_valid_pin(session_factory):
    fga = FakeFGA()
    seeded = await seed_initial_permission_catalog(
        fga,
        store_id="",
        model_id=MODEL_ID,
        model_checksum=MODEL_CHECKSUM,
        environment="prod",
    )
    assert seeded is False
    assert fga.write_calls == 0
    assert await _count(session_factory, PermissionCatalogRelease) == 0


def test_normalize_environment_matches_migration_runtime():
    assert normalize_environment({"name": "prod"}) == "prod"
    assert normalize_environment({"mode": "staging"}) == "staging"
    assert normalize_environment(None) == "dev"
    assert normalize_environment("") == "dev"
    assert len(normalize_environment("x" * 200)) == 64
