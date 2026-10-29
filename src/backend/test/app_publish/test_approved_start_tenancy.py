"""F113: approval provenance and human admission precede migration or instance work."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.app_publish.application.release_tenancy import ApprovedReleaseSource
from bisheng.app_publish.domain.services.publish_online_service import PublishOnlineService
from bisheng.app_runtime.application.approved_release import start_approved_release
from bisheng.app_runtime.domain.services.app_state_service import AppStateService
from bisheng.common.errcode.app_factory import AppNotFoundError, AppStateConflictError
from bisheng.common.errcode.open_api import ServiceAccountOwnerTenantMismatchError


def source():
    return ApprovedReleaseSource(9, "dep", "app", "v1", 1, 21)


def app():
    return SimpleNamespace(
        id="app",
        tenant_id=1,
        owner_user_id=21,
        state="pending_capacity",
        pending_version_id="v1",
        current_version_id=None,
    )


@pytest.mark.parametrize("wrong", [False, True])
async def test_approved_start_uses_verified_source_without_an_owner_login(monkeypatch, wrong):
    row = app()
    if wrong:
        row.pending_version_id = "other"
    monkeypatch.setattr(AppStateService, "_load", AsyncMock(return_value=row))
    forbidden = AsyncMock(side_effect=AssertionError("Approval borrowed a human operator"))
    monkeypatch.setattr(AppStateService, "_require_operator", forbidden)
    start = AsyncMock(return_value="started")
    monkeypatch.setattr(AppStateService, "_start_authorized", start, raising=False)
    if wrong:
        with pytest.raises(AppStateConflictError):
            await start_approved_release(source())
        start.assert_not_awaited()
    else:
        assert await start_approved_release(source()) == "started"
        assert start.await_args.kwargs["actor"] == source()
    forbidden.assert_not_awaited()


async def test_manual_publish_refuses_moved_owner_before_legacy_migration(monkeypatch):
    from bisheng.app_publish.domain.services import publish_online_service as online

    monkeypatch.setattr(PublishOnlineService, "_load_app", AsyncMock(return_value=app()))
    migrate = AsyncMock(side_effect=AssertionError("Migration ran before human tenancy admission"))
    monkeypatch.setattr(online.schema_evolution_service, "migrate_for_release", migrate)
    actor = SimpleNamespace(user_id=21, tenant_id=2, is_global_super=False)
    with pytest.raises(AppNotFoundError):
        await PublishOnlineService.manual_publish("app", actor=actor)
    migrate.assert_not_awaited()


async def test_failed_approval_qualification_does_not_stage_but_still_cleans_preview(monkeypatch):
    from bisheng.app_publish.domain.services import publish_online_service as online

    row = app()
    row.state = "stopped"
    monkeypatch.setattr(PublishOnlineService, "_load_app", AsyncMock(return_value=row))
    monkeypatch.setattr(online.VersionService, "get_version", AsyncMock(return_value=SimpleNamespace(id="v1")))
    qualify = AsyncMock(side_effect=ServiceAccountOwnerTenantMismatchError())
    monkeypatch.setattr(online, "qualify_approved_release", qualify, raising=False)
    monkeypatch.setattr(
        online,
        "get_business_approval",
        AsyncMock(
            return_value=SimpleNamespace(
                tenant_id=1,
                scenario_code="app_publish_request",
                business_resource_type="app",
                business_resource_id="app",
                status="approved",
                payload_snapshot={"app_id": "app", "version_id": "v1"},
            )
        ),
    )
    fail = AsyncMock()
    monkeypatch.setattr(PublishOnlineService, "_record_eligibility_failure", fail, raising=False)
    stage = AsyncMock()
    clean = AsyncMock()
    monkeypatch.setattr(AppStateService, "stage_version", stage)
    monkeypatch.setattr(online.PreviewInstanceService, "reclaim_on_release_terminal", clean)
    with pytest.raises(ServiceAccountOwnerTenantMismatchError):
        await PublishOnlineService.bring_online(9, {"app_id": "app", "version_id": "v1", "deployment_id": "dep"})
    stage.assert_not_awaited()
    clean.assert_awaited_once()
    fail.assert_awaited_once()
    assert row.pending_version_id == "v1" and row.current_version_id is None


async def test_refused_approval_persists_failure_even_when_preview_cleanup_fails(
    app_factory, deployment_factory, publish_db, monkeypatch
):
    """覆盖 AC: AC-12、AC-13、AC-14; cleanup never replaces the eligibility error."""
    from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao
    from bisheng.app_publish.domain.services import publish_online_service as online
    from bisheng.database.models.app import AppDao

    row, version = await app_factory(state="online")
    async with publish_db() as session:
        persistent = await AppDao.aget(session, row.id)
        persistent.pending_version_id = version.id
        session.add(persistent)
        await session.commit()
    deployment = await deployment_factory(
        app_id=row.id, version_id=version.id, approval_instance_id=9, stage="awaiting_approval"
    )
    payload = {"app_id": row.id, "version_id": version.id, "deployment_id": deployment.id}
    monkeypatch.setattr(
        online, "qualify_approved_release", AsyncMock(side_effect=ServiceAccountOwnerTenantMismatchError())
    )
    monkeypatch.setattr(
        online,
        "get_business_approval",
        AsyncMock(
            return_value=SimpleNamespace(
                tenant_id=row.tenant_id,
                scenario_code="app_publish_request",
                business_resource_type="app",
                business_resource_id=row.id,
                status="approved",
                payload_snapshot=payload,
            )
        ),
    )
    monkeypatch.setattr(
        online.PreviewInstanceService,
        "reclaim_on_release_terminal",
        AsyncMock(side_effect=OSError("cleanup unavailable")),
    )
    stage = AsyncMock(side_effect=AssertionError("A refused release changed the selected version"))
    monkeypatch.setattr(AppStateService, "stage_version", stage)
    with pytest.raises(ServiceAccountOwnerTenantMismatchError):
        await PublishOnlineService.bring_online(9, payload)
    async with publish_db() as session:
        failed = await AppDeploymentDao.aget(session, deployment.id)
        current = await AppDao.aget(session, row.id)
    assert failed.status == "failed" and failed.failure["code"] == 26071
    assert current.current_version_id == version.id and current.pending_version_id == version.id
    stage.assert_not_awaited()
