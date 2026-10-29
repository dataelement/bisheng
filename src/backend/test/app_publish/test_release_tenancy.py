"""F113: frozen deployment ownership and persistent approval provenance."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.app_publish.application.release_tenancy import qualify_approved_release, require_release_eligible
from bisheng.app_publish.domain.services import release_tenancy_service as service
from bisheng.common.errcode.app_publish import AppVersionNotFoundError
from bisheng.common.errcode.open_api import ServiceAccountOwnerTenantMismatchError


def records():
    app = SimpleNamespace(id="app", tenant_id=1, owner_user_id=21, state="online")
    deployment = SimpleNamespace(
        id="dep", app_id="app", version_id="v1", tenant_id=1, owner_user_id=21, approval_instance_id=9
    )
    version = SimpleNamespace(id="v1", app_id="app")
    return SimpleNamespace(app=app, deployment=deployment, version=version)


def snapshot():
    return {"app_id": "app", "version_id": "v1", "deployment_id": "dep", "tenant_id": 1, "owner_user_id": 21}


@pytest.fixture
def sources(monkeypatch):
    rows = records()
    approval = SimpleNamespace(
        id=9,
        tenant_id=1,
        scenario_code="app_publish_request",
        business_resource_type="app",
        business_resource_id="app",
        business_key="dep",
        applicant_user_id=21,
        status="approved",
        payload_snapshot=snapshot(),
    )
    monkeypatch.setattr(service.ReleaseTenancyRepository, "load", AsyncMock(return_value=rows))
    owner = AsyncMock()
    monkeypatch.setattr(service, "require_owner_tenant", owner)
    monkeypatch.setattr(service, "get_business_approval", AsyncMock(return_value=approval))
    return rows, approval, owner


async def test_valid_source_uses_frozen_owner_and_produces_an_immutable_internal_value(sources):
    _rows, _approval, owner = sources
    value = await qualify_approved_release(9, snapshot())
    assert (value.app_id, value.version_id, value.tenant_id, value.owner_user_id) == ("app", "v1", 1, 21)
    owner.assert_awaited_once_with(21, 1)
    with pytest.raises((AttributeError, TypeError)):
        value.owner_user_id = 22


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", 2),
        ("owner_user_id", 22),
        ("app_id", "other"),
        ("version_id", "v2"),
        ("deployment_id", "other"),
    ],
)
async def test_callback_snapshot_cannot_replace_persistent_references(sources, field, value):
    bad = {**snapshot(), field: value}
    with pytest.raises(AppVersionNotFoundError):
        await qualify_approved_release(9, bad)


@pytest.mark.parametrize("status", ["pending", "cancelled", "rejected", "withdrawn", "exception"])
async def test_nonapproved_decision_is_not_an_execution_source(sources, status):
    sources[1].status = status
    with pytest.raises(AppVersionNotFoundError):
        await qualify_approved_release(9, snapshot())


@pytest.mark.parametrize("field,value", [("tenant_id", 2), ("approval_instance_id", 8), ("owner_user_id", 22)])
async def test_deployment_must_match_app_and_approval(sources, field, value):
    setattr(sources[0].deployment, field, value)
    with pytest.raises(AppVersionNotFoundError):
        await qualify_approved_release(9, snapshot())


async def test_frozen_owner_tenant_failure_propagates_without_changing_version_pointers(sources):
    rows, _approval, owner = sources
    rows.app.current_version_id = "old"
    rows.app.pending_version_id = "pending"
    owner.side_effect = ServiceAccountOwnerTenantMismatchError()
    with pytest.raises(ServiceAccountOwnerTenantMismatchError):
        await require_release_eligible("app", deployment_id="dep")
    assert (rows.app.current_version_id, rows.app.pending_version_id) == ("old", "pending")


async def test_worker_eligibility_does_not_require_a_version_before_it_is_recorded(sources):
    sources[0].version = None
    await require_release_eligible("app", deployment_id="dep")
    with pytest.raises(AppVersionNotFoundError):
        await require_release_eligible("app", version_id="v1")


async def test_missing_or_ambiguous_deployment_is_not_fabricated_from_audit(sources, monkeypatch):
    monkeypatch.setattr(service.ReleaseTenancyRepository, "load", AsyncMock(return_value=None))
    with pytest.raises(AppVersionNotFoundError):
        await require_release_eligible("app", version_id="v1")


async def test_repository_reads_real_version_and_refuses_duplicate_sources(
    publish_db, app_factory, deployment_factory, monkeypatch
):
    from bisheng.app_publish.domain.repositories import release_tenancy_repository as repository

    monkeypatch.setattr(repository, "get_async_db_session", publish_db)
    app, version = await app_factory()
    deployment = await deployment_factory(app_id=app.id, version_id=version.id)
    rows = await repository.ReleaseTenancyRepository.load(app.id, version_id=version.id)
    assert rows.deployment.id == deployment.id and rows.version.id == version.id
    assert await repository.ReleaseTenancyRepository.load("foreign", version_id=version.id) is None
    await deployment_factory(app_id=app.id, version_id=version.id)
    assert await repository.ReleaseTenancyRepository.load(app.id, version_id=version.id) is None


async def test_accept_qualification_precedes_package_and_draft_writes(monkeypatch, tmp_path):
    from bisheng.app_publish.domain.services import publish_pipeline_service as pipeline

    monkeypatch.setattr(pipeline.settings.app_runtime, "enabled", True)
    monkeypatch.setattr(
        pipeline, "revalidate_service_account", AsyncMock(side_effect=ServiceAccountOwnerTenantMismatchError())
    )
    create = AsyncMock()
    store = AsyncMock()
    enqueue = AsyncMock()
    monkeypatch.setattr(pipeline.PublishPipelineService, "_create_draft", create)
    monkeypatch.setattr(pipeline.package_service, "store_package", store)
    monkeypatch.setattr(pipeline, "enqueue_pipeline", enqueue)
    with pytest.raises(ServiceAccountOwnerTenantMismatchError):
        await pipeline.PublishPipelineService.accept(
            package_path=tmp_path / "never-read.tar.gz", principal=object(), tenant_id=1
        )
    create.assert_not_awaited()
    store.assert_not_awaited()
    enqueue.assert_not_awaited()


@pytest.mark.parametrize("stage", ["_update_meta", "_record_version"])
async def test_preapproval_qualification_precedes_metadata_and_version_side_effects(monkeypatch, stage):
    from bisheng.app_publish.domain.services import publish_pipeline_service as pipeline

    monkeypatch.setattr(
        pipeline, "require_release_eligible", AsyncMock(side_effect=ServiceAccountOwnerTenantMismatchError())
    )
    icon = AsyncMock()
    version = AsyncMock()
    monkeypatch.setattr(pipeline.PublishPipelineService, "_store_icon", icon)
    monkeypatch.setattr(pipeline.VersionService, "record_version", version)
    with pytest.raises(ServiceAccountOwnerTenantMismatchError):
        await getattr(pipeline.PublishPipelineService, stage)(SimpleNamespace(id="dep", app_id="app"), {})
    icon.assert_not_awaited()
    version.assert_not_awaited()


async def test_worker_qualification_precedes_materialization_and_records_failure(
    publish_db, deployment_factory, monkeypatch
):
    from bisheng.app_publish.domain.services import publish_pipeline_service as pipeline

    deployment = await deployment_factory(app_id="app", version_id="v1")
    monkeypatch.setattr(pipeline.AppManifest, "model_validate", lambda _manifest: SimpleNamespace())
    refused = ServiceAccountOwnerTenantMismatchError()
    monkeypatch.setattr(pipeline, "require_release_eligible", AsyncMock(side_effect=refused))
    materialize = AsyncMock()
    fail = AsyncMock()
    monkeypatch.setattr(pipeline.PublishPipelineService, "_materialise_snapshot", materialize)
    monkeypatch.setattr(pipeline.PublishPipelineService, "_fail", fail)
    await pipeline.PublishPipelineService.run_pipeline(deployment.id)
    materialize.assert_not_awaited()
    assert fail.await_args.args[1] is refused


async def test_preview_qualification_only_blocks_new_execution(monkeypatch):
    from bisheng.app_publish.application import release_tenancy
    from bisheng.app_publish.domain.services.preview_instance_service import PreviewInstanceService

    row = SimpleNamespace(id="app", tenant_id=1)
    monkeypatch.setattr(PreviewInstanceService, "_require_access", AsyncMock(return_value=(row, "approver")))
    qualify = AsyncMock(side_effect=ServiceAccountOwnerTenantMismatchError())
    monkeypatch.setattr(release_tenancy, "require_release_eligible", qualify)
    insert = AsyncMock()
    monkeypatch.setattr(PreviewInstanceService, "_insert_session", insert)
    with pytest.raises(ServiceAccountOwnerTenantMismatchError):
        await PreviewInstanceService.start("app", "v1", actor=SimpleNamespace(user_id=21))
    insert.assert_not_awaited()
    monkeypatch.setattr(PreviewInstanceService, "_load_version", AsyncMock(return_value=object()))
    monkeypatch.setattr(PreviewInstanceService, "reclaim_expired", AsyncMock())
    monkeypatch.setattr(PreviewInstanceService, "_current_session", AsyncMock(return_value=None))
    monkeypatch.setattr(PreviewInstanceService, "_not_runnable_reason", lambda _version: None)
    monkeypatch.setattr(PreviewInstanceService, "_payload", lambda *_args, **_kwargs: {"status": "absent"})
    assert await PreviewInstanceService.describe("app", "v1", actor=SimpleNamespace(user_id=21)) == {"status": "absent"}
    assert qualify.await_count == 1


async def test_human_metadata_keeps_existing_persistence_and_has_no_none_actor_bypass(
    publish_db, app_factory, monkeypatch
):
    from bisheng.app_runtime.domain.services import app_meta_service as metadata
    from bisheng.common.errcode.app_factory import AppNotFoundError

    monkeypatch.setattr(metadata, "get_async_db_session", publish_db)
    monkeypatch.setattr(metadata.AuditLogDao, "ainsert_v2", AsyncMock())
    app, _version = await app_factory()
    actor = SimpleNamespace(user_id=app.owner_user_id, tenant_id=app.tenant_id, is_global_super=False)
    actual = await metadata.AppMetaService.update_meta(app_id=app.id, name="F113 renamed", actor=actor)
    assert actual.name == "F113 renamed"
    with pytest.raises(AppNotFoundError):
        await metadata.AppMetaService.update_meta(app_id=app.id, name="must not persist")
    async with publish_db() as session:
        stored = await session.get(type(app), app.id)
        assert stored.name == "F113 renamed"
