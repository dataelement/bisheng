"""F118 fresh-install Catalog metadata. 覆盖 AC: AC-78, AC-80, AC-81, AC-83."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlmodel import select

from bisheng.permission.application import catalog_bootstrap as bootstrap
from bisheng.permission.domain.models import PermissionCatalogRelease, PermissionModel
from bisheng.permission.domain.services.model_policy import derive_permission_models
from test.knowledge_unification.test_perm_control_snapshot import seed, session_factory  # noqa: F401
from test.knowledge_unification.test_perm_policy import action_release


async def seed_fresh(monkeypatch, factory):
    monkeypatch.setattr(bootstrap, "get_async_db_session", factory)
    actions = action_release()
    models = derive_permission_models(actions)
    await bootstrap._seed_control_plane(
        store_id="s1",
        model_id="m1",
        model_checksum="a" * 64,
        environment="test",
        catalog_checksum="b" * 64,
        relations_checksum="c" * 64,
        action_release=actions,
        model_release=models,
    )


async def test_fresh_bootstrap_persists_viewer_pure_visibility(monkeypatch, session_factory):
    await seed_fresh(monkeypatch, session_factory)
    async with session_factory() as session:
        viewer = (
            await session.execute(select(PermissionModel).where(PermissionModel.model_key == "viewer"))
        ).scalar_one()
        assert {"tool", "linsight_skill"} <= set(viewer.visibility_only_resource_types or ())
        assert viewer.visibility_level == 1


async def test_bootstrap_never_republishes_existing_current_catalog(monkeypatch, session_factory):
    release_id, _, _ = await seed(session_factory)
    monkeypatch.setattr(bootstrap, "get_async_db_session", session_factory)
    client = SimpleNamespace(write_tuples=AsyncMock())
    assert not await bootstrap.seed_initial_permission_catalog(
        client, store_id="s1", model_id="new-model", model_checksum="d" * 64, environment="test"
    )
    client.write_tuples.assert_not_called()
    async with session_factory() as session:
        current = (
            (
                await session.execute(
                    select(PermissionCatalogRelease).where(PermissionCatalogRelease.status == "CURRENT")
                )
            )
            .scalars()
            .all()
        )
        assert len(current) == 1 and current[0].id == release_id and current[0].checksum == "a" * 64
