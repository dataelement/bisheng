"""F118 Catalog SQL snapshot round trips. 覆盖 AC: AC-78, AC-80, AC-81, AC-83."""

from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.permission.application import control_state
from bisheng.permission.application.catalog_api import SqlCatalogState
from bisheng.permission.domain.models import AuthorizationModelRelease, PermissionCatalogRelease, PermissionModel
from bisheng.permission.domain.schemas.f048 import CatalogChangeRequest
from bisheng.permission.domain.services.model_policy import CustomModelSelection, derive_permission_models
from test.knowledge_unification.test_perm_policy import action_release


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    metadata = sa.MetaData()
    for name in (
        "authorization_model_release",
        "permission_catalog_release",
        "permission_action",
        "permission_action_resource_scope",
        "permission_model",
        "permission_model_action",
    ):
        table = SQLModel.metadata.tables[name].to_metadata(metadata)
        table.c.id.type = sa.Integer()
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    yield factory
    await engine.dispose()


async def seed(factory):
    actions = action_release()
    models = derive_permission_models(
        actions,
        custom_models=(
            CustomModelSelection(
                "legacy", "Legacy", ("download",), visibility_only_resource_types=("tool",), visibility_level=3
            ),
        ),
    )
    async with factory() as session:
        auth = AuthorizationModelRelease(
            environment="test",
            store_id="s1",
            model_version="f118",
            model_id="m1",
            model_checksum="a" * 64,
            required_relations_checksum="b" * 64,
            openfga_version="1.15.1",
            status="ACTIVE",
        )
        session.add(auth)
        await session.flush()
        release = PermissionCatalogRelease(
            release_key="r1",
            version=1,
            status="CURRENT",
            required_authorization_model_release_id=auth.id,
            draft_owner_id=1,
            idempotency_key="initial",
            checksum="a" * 64,
        )
        session.add(release)
        await session.flush()
        await SqlCatalogState._replace_children(
            session, release_id=release.id, action_release=actions, model_release=models
        )
        await session.commit()
        return release.id, actions, models


async def test_catalog_sql_roundtrip_preserves_metadata_and_checksum(session_factory):
    release_id, actions, models = await seed(session_factory)
    async with session_factory() as session:
        loaded = await SqlCatalogState._load_models(session, release_id, actions)
        row = (await session.execute(select(PermissionModel).where(PermissionModel.model_key == "legacy"))).scalar_one()
        assert row.visibility_only_resource_types == ["tool"] and row.visibility_level == 3
    assert loaded.checksum == models.checksum
    assert next(model for model in loaded.models if model.model_key == "legacy").visibility_level == 3


async def test_current_catalog_loads_target_metadata_and_dynamic_action_scopes(session_factory, monkeypatch):
    await seed(session_factory)
    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)
    catalog = await control_state.SqlPermissionControlState().current_catalog()
    raw = next(model.snapshot for model in catalog.models if model.snapshot.model_key == "legacy")
    assert raw.visibility_only_resource_types == ("tool",) and raw.visibility_level == 3
    scoped = catalog.model_for_target(raw, resource_type="tool")
    assert scoped.visibility_only and scoped.derived_level == 3 and scoped.action_codes == ()
    viewer = next(model.snapshot for model in catalog.models if model.snapshot.model_key == "viewer")
    assert catalog.model_for_target(viewer, resource_type="tool").visibility_only


async def test_old_null_metadata_loads_as_empty(session_factory):
    release_id, actions, _ = await seed(session_factory)
    async with session_factory() as session:
        row = (await session.execute(select(PermissionModel).where(PermissionModel.model_key == "legacy"))).scalar_one()
        row.visibility_only_resource_types = None
        row.visibility_level = None
        await session.commit()
        loaded = await SqlCatalogState._load_models(session, release_id, actions)
    legacy = next(model for model in loaded.models if model.model_key == "legacy")
    assert legacy.visibility_only_resource_types == () and legacy.visibility_level is None


def test_http_marker_fields_remain_server_owned():
    with pytest.raises(ValidationError):
        CatalogChangeRequest(
            type="CREATE_MODEL",
            name="Fake",
            action_codes=(),
            visibility_only_resource_types=["tool"],
            visibility_level=4,
        )


def test_all_current_presets_use_registered_actions_only():
    from bisheng.permission.application.catalog_api import F048CatalogApi
    from bisheng.permission.domain.services.catalog_policy import REGISTERED_ACTION_CODES

    for preset in F048CatalogApi.PRESETS:
        assert set(preset["action_codes"]) <= set(REGISTERED_ACTION_CODES)
