"""Every saved APP version participates in deletion/preview. 覆盖 AC: AC-71, AC-75, AC-89, AC-91, AC-92."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_publish.domain.services import preview_instance_service as preview_module
from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation
from bisheng.app_runtime.domain.services import app_state_service as module
from bisheng.app_runtime.domain.services import runtime_delivery_coordinator as coordinator_module
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion
from bisheng.resource_reference.application.bindings import ReferenceBindings
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from test.knowledge_unification import test_app_snapshot as fixtures

ctx = fixtures.ctx
resolving = fixtures.resolving
application = fixtures.application
writing = fixtures.writing


@pytest.fixture
async def deleting(writing, monkeypatch):
    async with AsyncSession(writing.engine) as session, session.begin():
        await session.execute(sa.update(App).where(App.id == "actual-app").values(state="stopped"))
    monkeypatch.setattr(module, "get_async_db_session", fixtures.module.get_async_db_session)
    authorization = AsyncMock()
    monkeypatch.setattr(module.AppStateService, "_require_deleter", authorization)
    monkeypatch.setattr(module.AppStateService, "_audit", AsyncMock())
    monkeypatch.setattr(module.lifecycle_hooks, "on_app_deleted", AsyncMock(return_value=[]))
    adapter = SimpleNamespace(load_permission_record=AsyncMock(return_value=SimpleNamespace(id="actual-app")))
    monkeypatch.setattr(module, "get_f048_resource_adapter", AsyncMock(return_value=adapter))
    projection = AsyncMock()
    monkeypatch.setattr(module.AppStateService, "_project_delete", projection)
    monkeypatch.setattr(module, "get_reference_binding_runtime", AsyncMock(return_value=writing.runtime), raising=False)
    created = []

    class Coordinator:
        def __init__(self, repository=None, **kwargs):
            self.repo = repository
            self.wake = AsyncMock()
            self.wait = AsyncMock(return_value={})
            self.stop = AsyncMock(return_value={})
            self.submitted = []

        async def submit(self, app, *, kind, key, payload, **kwargs):
            op = RuntimeOperation(
                id=f"destroy-{app.id}",
                tenant_id=app.tenant_id,
                app_id=app.id,
                scope_key=f"{app.tenant_id}/{app.id}",
                idempotency_key=key,
                request_digest="0" * 64,
                kind=kind,
                node_id="test-control",
                deadline=datetime.utcnow() + timedelta(hours=1),
                payload=payload,
            )
            self.submitted.append(op)
            await self.repo.save(op)
            return op

    def coordinator(*args, **kwargs):
        value = Coordinator(*args, **kwargs)
        created.append(value)
        return value

    monkeypatch.setattr(coordinator_module, "RuntimeDeliveryCoordinator", coordinator)
    # This test isolates the existing route/material control plane; the actual
    # same-session destroy intent remains SQL, and reference Owners are real.
    from bisheng.app_runtime.domain.services import runtime_projection_service

    monkeypatch.setattr(runtime_projection_service.RuntimeProjectionService, "block", AsyncMock())
    return SimpleNamespace(
        **vars(writing), authorize_delete=authorization, project_delete=projection, coordinators=created
    )


async def delete(context, app_id="actual-app"):
    return await module.AppStateService.delete(app_id, actor=context.user)


async def test_root_deletion_releases_every_saved_version_but_retains_immutable_rows(deleting):
    result = await delete(deleting)
    assert result.state == "deleted"
    async with AsyncSession(deleting.engine) as session, session.begin():
        assert (await session.get(App, "actual-app")).state == "deleted"
        assert len((await session.execute(sa.select(AppVersion))).scalars().all()) == 2
        assert not (await session.execute(sa.select(BusinessResourceReference))).scalars().all()
        sets = (
            (await session.execute(sa.select(BusinessReferenceSet).where(BusinessReferenceSet.record_kind == "source")))
            .scalars()
            .all()
        )
        assert len(sets) == 2 and all(item.ready and not item.effective for item in sets)
        assert len((await session.execute(sa.select(RuntimeOperation))).scalars().all()) == 1
    control = deleting.coordinators[-1]
    control.stop.assert_not_awaited()
    control.wake.assert_awaited_once()
    control.wait.assert_awaited_once()


@pytest.mark.parametrize("corruption", ["missing_set", "orphan_raw", "unknown_set", "bad_revision"])
async def test_complete_inventory_rejects_unknown_or_incomplete_sources_before_side_effects(deleting, corruption):
    async with AsyncSession(deleting.engine) as session, session.begin():
        if corruption == "missing_set":
            await session.execute(
                sa.delete(BusinessReferenceSet).where(BusinessReferenceSet.source_version == fixtures.fixtures.HISTORY)
            )
        elif corruption == "orphan_raw":
            session.add(
                BusinessResourceReference(
                    tenant_id=101,
                    source_type="hosted_app_version",
                    source_id="actual-app",
                    source_version="unknown-version",
                    slot_key="orphan",
                    target_type="model",
                    target_id="11",
                    target_tenant_id=101,
                    source_revision=1,
                )
            )
        elif corruption == "unknown_set":
            session.add(
                BusinessReferenceSet(
                    tenant_id=101,
                    source_type="hosted_app_version",
                    source_id="actual-app",
                    source_version="unknown-version",
                    source_revision=1,
                    extractor_version="hosted-app-v1",
                    digest="0" * 64,
                    ready=True,
                )
            )
        else:
            await session.execute(sa.update(BusinessResourceReference).values(source_revision=99))
    before = await fixtures.snapshot(deleting.engine)
    with pytest.raises(ReferenceCoverageNotReadyError):
        await delete(deleting)
    assert await fixtures.snapshot(deleting.engine) == before
    deleting.project_delete.assert_not_awaited()
    assert not deleting.coordinators or not deleting.coordinators[-1].submitted


async def test_second_source_apply_failure_rolls_back_all_versions_root_and_intent(deleting, monkeypatch):
    before = await fixtures.snapshot(deleting.engine)
    real = ReferenceBindings.areplace_source_bindings
    count = 0

    async def failed(self, *args, **kwargs):
        nonlocal count
        result = await real(self, *args, **kwargs)
        count += 1
        if count == 2:
            raise RuntimeError("second source failed")
        return result

    monkeypatch.setattr(ReferenceBindings, "areplace_source_bindings", failed)
    with pytest.raises(RuntimeError, match="second source failed"):
        await delete(deleting)
    assert await fixtures.snapshot(deleting.engine) == before
    async with AsyncSession(deleting.engine) as session:
        assert not (await session.execute(sa.select(RuntimeOperation))).scalars().all()
    if deleting.coordinators:
        deleting.coordinators[-1].wake.assert_not_awaited()


async def test_projection_failure_prevents_sql_finalize_and_wakeup(deleting):
    before = await fixtures.snapshot(deleting.engine)
    deleting.project_delete.side_effect = RuntimeError("FGA unavailable")
    with pytest.raises(RuntimeError, match="FGA unavailable"):
        await delete(deleting)
    assert await fixtures.snapshot(deleting.engine) == before
    if deleting.coordinators:
        deleting.coordinators[-1].wake.assert_not_awaited()


async def test_zero_version_draft_deletion_does_not_invent_a_source(deleting):
    async with AsyncSession(deleting.engine) as session, session.begin():
        session.add(App(id="empty-app", tenant_id=101, name="empty", slug="empty", owner_user_id=4, state="draft"))
    assert (await delete(deleting, "empty-app")).state == "deleted"
    async with AsyncSession(deleting.engine) as session:
        assert (
            not (
                await session.execute(
                    sa.select(BusinessReferenceSet).where(BusinessReferenceSet.source_id == "empty-app")
                )
            )
            .scalars()
            .all()
        )


async def test_historical_preview_requires_full_saved_source_before_manager_io(writing, monkeypatch):
    from contextlib import asynccontextmanager

    from bisheng.app_publish.domain.services.preview_access_service import PreviewQualification

    qualification = PreviewQualification(101, "actual-app", fixtures.fixtures.HISTORY, 4, "management")

    @asynccontextmanager
    async def qualified(*args, **kwargs):
        yield qualification

    monkeypatch.setattr(preview_module, "qualified_scope", qualified)
    monkeypatch.setattr(
        preview_module.VersionService, "get_version", AsyncMock(return_value=SimpleNamespace(terminal_state=None))
    )
    from bisheng.app_publish.application import release_tenancy

    monkeypatch.setattr(release_tenancy, "require_release_eligible", AsyncMock())
    runtime = SimpleNamespace(
        verifier=SimpleNamespace(aissue_scope=AsyncMock()),
        arequire_source_valid=AsyncMock(side_effect=ResourceReferenceInvalidError(reason="reference_target_invalid")),
    )
    monkeypatch.setattr(
        preview_module, "get_hosted_app_user_reference_runtime", AsyncMock(return_value=runtime), raising=False
    )
    monkeypatch.setattr(preview_module, "get_async_db_session", fixtures.module.get_async_db_session, raising=False)
    start = AsyncMock()
    monkeypatch.setattr(preview_module, "start_preview", start)
    monkeypatch.setattr(preview_module, "by_reference", AsyncMock(return_value=None))
    with pytest.raises(ResourceReferenceInvalidError):
        await preview_module.PreviewInstanceService.start(
            "actual-app", fixtures.fixtures.HISTORY, actor=writing.user, purpose="management"
        )
    start.assert_not_awaited()


async def test_publish_checks_complete_stored_version_before_constructing_manager(deleting, monkeypatch):
    from bisheng.app_runtime.domain.constants import AppAuditAction
    from bisheng.app_runtime.domain.services.runtime_authorization_service import RuntimeAuthorizationService
    from bisheng.open_api.domain.context import reset_current_open_api_principal, set_current_open_api_principal

    app = SimpleNamespace(
        id="actual-app",
        tenant_id=101,
        owner_user_id=4,
        state="stopped",
        current_version_id=fixtures.fixtures.VERSION,
        pending_version_id=fixtures.fixtures.HISTORY,
    )
    version = SimpleNamespace(id=fixtures.fixtures.HISTORY, tier_id="light")
    monkeypatch.setattr(module.AppStateService, "_load_version", AsyncMock(return_value=version))
    monkeypatch.setattr(module.AppStateService, "_resolve_tier", AsyncMock(return_value={"cpu": 1, "mem": 512}))
    frozen = {"target": {"tenant_id": 101, "app_id": app.id, "version_id": version.id}, "purpose": "approved_start"}
    monkeypatch.setattr(RuntimeAuthorizationService, "capture_user", AsyncMock(return_value=frozen))
    monkeypatch.setattr(RuntimeAuthorizationService, "validate_user", AsyncMock())
    runtime = SimpleNamespace(
        verifier=SimpleNamespace(aissue_scope=AsyncMock()),
        arequire_source_valid=AsyncMock(side_effect=ResourceReferenceInvalidError(reason="invalid_saved_model")),
    )
    get_runtime = AsyncMock(return_value=runtime)
    monkeypatch.setattr(module, "get_hosted_app_user_reference_runtime", get_runtime, raising=False)
    monkeypatch.setattr(
        coordinator_module,
        "RuntimeDeliveryCoordinator",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("manager before reference admission")),
    )
    token = set_current_open_api_principal(None)
    try:
        with pytest.raises(ResourceReferenceInvalidError):
            await module.AppStateService._start_authorized(
                app, actor=deleting.user, audit_action=AppAuditAction.PUBLISH, shortage_state=None
            )
        assert get_runtime.await_args.args[0] is frozen
        assert runtime.verifier.aissue_scope.await_args.args[2] is deleting.user
    finally:
        reset_current_open_api_principal(token)
