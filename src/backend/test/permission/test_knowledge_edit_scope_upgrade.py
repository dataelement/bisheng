"""Native old-Catalog publication and real action runtime regressions."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionImpactExpiredError,
    PermissionProjectionFailedError,
    PermissionVersionConflictError,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
    build_authorization_model_f048,
)
from bisheng.permission.application import catalog_bootstrap, sql_runtime
from bisheng.permission.application.catalog_api import OpenFGACatalogProjector, SqlCatalogState, _utc_now_naive
from bisheng.permission.application.knowledge_edit_scope_upgrade import (
    EDIT_TYPES,
    KnowledgeEditScopeUpgrade,
    publication_key,
)
from bisheng.permission.domain.models import (
    PermissionCatalogRelease,
    PermissionModel,
    ResourcePermissionMode,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.catalog_policy import derive_action_release
from bisheng.permission.domain.services.permission_action_service import F048PermissionService, PermissionActor
from bisheng.permission.migration.f048_model_mapper import build_initial_action_release
from test.permission.test_f048_authorization_model import ModelEvaluator, _resource_grant_tuples
from test.permission.test_f048_catalog_runtime import FakeCatalogMarker, InMemoryCatalogFGA
from test.permission.test_f048_catalog_runtime import session_factory as session_factory


@pytest.fixture(autouse=True)
def request_tenant():
    from bisheng.core.context.tenant import current_tenant_id

    token = current_tenant_id.set(101)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


class Transport(InMemoryCatalogFGA):
    async def write_tuples(self, writes=None, deletes=None, **kwargs):
        await super().write_tuples(writes, deletes)

    async def check(self, *, user, relation, object, consistency=None):
        return ModelEvaluator(build_authorization_model_f048(), self.tuples).check(user, relation, object)


async def setup_catalog(factory, monkeypatch, *, old=True, customs=(), action_transform=None):
    from bisheng.permission.domain.services.model_policy import derive_permission_models

    fga = Transport()
    actions = build_initial_action_release()
    if old:
        actions = derive_action_release(
            replace(row, resource_types=row.resource_types - EDIT_TYPES) if row.code == "edit" else row
            for row in actions.actions
        )
    if action_transform is not None:
        actions = action_transform(actions)
    monkeypatch.setattr(
        catalog_bootstrap, "derive_permission_models", lambda a: derive_permission_models(a, custom_models=customs)
    )
    monkeypatch.setattr(catalog_bootstrap, "get_async_db_session", factory)
    monkeypatch.setattr(catalog_bootstrap, "build_initial_action_release", lambda: actions)
    monkeypatch.setattr(sql_runtime, "get_async_db_session", factory)
    assert await catalog_bootstrap.seed_initial_permission_catalog(
        fga,
        store_id=fga.store_id,
        model_id=fga.model_id,
        model_checksum=authorization_model_checksum(build_authorization_model_f048()),
        environment="test",
    )
    # Fresh-install seeding normally creates standards only. This fixture also
    # represents controlled migration provenance already stored in live SQL.
    with bypass_tenant_filter():
        async with factory() as session, session.begin():
            for custom in customs:
                if custom.retired_use_level_floor is not None:
                    await session.execute(
                        sa.update(PermissionModel)
                        .where(PermissionModel.model_key == custom.model_key)
                        .values(retired_use_level_floor=custom.retired_use_level_floor)
                    )
    state = SqlCatalogState(session_factory=factory)
    projector = OpenFGACatalogProjector(client=fga, marker=FakeCatalogMarker(), session_factory=factory)
    return SimpleNamespace(
        factory=factory,
        fga=fga,
        state=state,
        projector=projector,
        upgrade=KnowledgeEditScopeUpgrade(state=state, projector=projector),
    )


@pytest.fixture
async def legacy(session_factory, monkeypatch):
    return await setup_catalog(session_factory, monkeypatch)


async def apply(value, *, key="upgrade-1"):
    plan = await value.upgrade.plan()
    return await value.upgrade.apply(plan_digest=plan["plan_digest"], operator_id=7, idempotency_key=key)


async def resource(
    value, *, kind="knowledge_file", ident="201", parent_type="folder", parent_id="99", model="editor", mode="INHERIT"
):
    with bypass_tenant_filter():
        async with value.factory() as session, session.begin():
            session.add(
                ResourcePermissionMode(
                    tenant_id=101,
                    resource_type=kind,
                    resource_id=ident,
                    mode=mode,
                    parent_type=parent_type,
                    parent_id=parent_id,
                    version=1,
                    projection_state="CURRENT",
                )
            )
    root = "knowledge_space:9700"
    folder = "folder:99"
    value.fga.tuples |= _resource_grant_tuples(
        resource=root, grant="permission_grant:space", model_key="viewer", subject="user:7"
    )
    value.fga.tuples |= _resource_grant_tuples(
        resource=folder, grant="permission_grant:folder", model_key=model, subject="user:7"
    )
    value.fga.tuples.add((root, "parent", folder))
    if kind == "knowledge_file":
        value.fga.tuples.update(
            {
                (folder, "parent", f"{kind}:{ident}"),
                ("user:*", "permission_enabled", f"{kind}:{ident}"),
                ("user:*", "inherit_mode" if mode == "INHERIT" else "custom_mode", f"{kind}:{ident}"),
            }
        )
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=101,
        resource_type=kind,
        resource_id=ident,
        resource_version=1,
        context_version="test-v1",
        parent_type=parent_type,
        parent_id=parent_id,
    )


def decisions(value):
    return F048PermissionService(
        catalog=sql_runtime.SqlCatalogDecisionState(
            expected_store_id=value.fga.store_id, expected_model_id=value.fga.model_id
        ),
        scope_fence=sql_runtime.SqlPermissionScopeFence(),
        marker=SimpleNamespace(consistency_for=AsyncMock(return_value="HIGHER_CONSISTENCY")),
        fga=value.fga,
        list_policy=None,
    )


async def test_old_environment_reproduces_25001_then_real_inherited_edit_is_allowed(legacy):
    target = await resource(legacy)
    runtime = decisions(legacy)
    actor = PermissionActor(user_id=7, tenant_id=101)
    with pytest.raises(InvalidCatalogActionError):
        await runtime.check_action(actor, target, "edit")
    before_tuples = set(legacy.fga.tuples)
    result = await apply(legacy)
    assert result["event"] == "verified"
    assert await runtime.check_action(actor, target, "edit")
    assert not ModelEvaluator(build_authorization_model_f048(), legacy.fga.tuples).check(
        "user:7", "can_edit", "knowledge_space:9700"
    )
    # Publication adds only a new Catalog graph; existing resource grants stay.
    assert {
        row for row in before_tuples if row[2].startswith(("knowledge_file:", "folder:", "permission_grant:"))
    } <= legacy.fga.tuples


@pytest.mark.parametrize(
    "model,mode,allowed",
    [
        ("editor", "INHERIT", True),
        ("manager", "INHERIT", True),
        ("viewer", "INHERIT", False),
        ("editor", "CUSTOM", False),
    ],
)
async def test_standard_roles_and_explicit_file_boundary_are_preserved(legacy, model, mode, allowed):
    target = await resource(legacy, model=model, mode=mode)
    await apply(legacy)
    assert await decisions(legacy).check_action(PermissionActor(user_id=7, tenant_id=101), target, "edit") is allowed


async def test_fresh_install_exposes_both_actions_without_upgrade(session_factory, monkeypatch):
    value = await setup_catalog(session_factory, monkeypatch, old=False)
    assert (await value.upgrade.plan())["event"] == "noop"
    assert (await value.upgrade.verify())["event"] == "verified"


async def test_folder_edit_and_cross_tenant_denial(legacy):
    folder = await resource(legacy, kind="folder", ident="99", parent_type="knowledge_space", parent_id="9700")
    await apply(legacy)
    runtime = decisions(legacy)
    assert await runtime.check_action(PermissionActor(user_id=7, tenant_id=101), folder, "edit")
    assert not await runtime.check_action(PermissionActor(user_id=7, tenant_id=102), folder, "edit")


async def test_plan_is_read_only_and_apply_noop_creates_no_new_release(legacy):
    writes = len(legacy.fga.write_calls)
    first = await legacy.upgrade.plan()
    assert first == await legacy.upgrade.plan()
    assert first["missing_scopes"] == [["edit", "folder"], ["edit", "knowledge_file"]]
    assert len(legacy.fga.write_calls) == writes
    await apply(legacy)
    writes = len(legacy.fga.write_calls)
    current = await legacy.state.current_release()
    await apply(legacy)
    assert (await legacy.state.current_release()).id == current.id
    assert len(legacy.fga.write_calls) == writes


async def test_stale_plan_blocks_before_draft_reservation(legacy):
    with pytest.raises(PermissionVersionConflictError):
        await legacy.upgrade.apply(plan_digest="wrong", operator_id=7, idempotency_key="stale")
    assert await legacy.state.release_for_idempotency(publication_key("stale")) is None


async def test_crash_after_reservation_can_resume_same_key(legacy):
    plan = await legacy.upgrade.plan()
    await legacy.state.reserve_draft(
        base_release_id=plan["base_release_id"],
        operator_id=7,
        idempotency_key=publication_key("interrupted"),
        expires_at=_utc_now_naive() + timedelta(minutes=10),
    )
    result = await legacy.upgrade.apply(plan_digest=plan["plan_digest"], operator_id=7, idempotency_key="interrupted")
    assert result["event"] == "verified"


async def test_expired_draft_never_commits_unverified_staging(legacy, monkeypatch):
    async def crash(context):
        raise RuntimeError("process died after PROJECTING")

    monkeypatch.setattr(legacy.projector, "stage_model_releases", crash)
    with pytest.raises(PermissionProjectionFailedError):
        await apply(legacy, key="expired")
    row = await legacy.state.release_for_idempotency(publication_key("expired"))
    with bypass_tenant_filter():
        async with legacy.factory() as session, session.begin():
            await session.execute(
                sa.update(PermissionCatalogRelease)
                .where(PermissionCatalogRelease.id == row.id)
                .values(status="PROJECTING", expires_at=_utc_now_naive() - timedelta(seconds=1))
            )
    writes = len(legacy.fga.write_calls)
    with pytest.raises(PermissionImpactExpiredError):
        await legacy.upgrade.resume(draft_id=row.id, operator_id=7, idempotency_key="expired")
    assert len(legacy.fga.write_calls) == writes


async def test_unknown_commit_ack_resumes_same_draft_without_duplicate_release(legacy, monkeypatch):
    original = legacy.state.mark_committed

    async def crash(*args, **kwargs):
        raise RuntimeError("SQL ACK lost after FGA commit")

    monkeypatch.setattr(legacy.state, "mark_committed", crash)
    with pytest.raises(PermissionProjectionFailedError):
        await apply(legacy, key="ack")
    row = await legacy.state.release_for_idempotency(publication_key("ack"))
    monkeypatch.setattr(legacy.state, "mark_committed", original)
    result = await legacy.upgrade.resume(draft_id=row.id, operator_id=7, idempotency_key="ack")
    assert result["catalog_release_id"] == row.id


async def test_wrong_operator_cannot_resume_another_maintenance_publication(legacy):
    await apply(legacy)
    with pytest.raises(PermissionVersionConflictError):
        await legacy.upgrade.apply(plan_digest="unused", operator_id=8, idempotency_key="upgrade-1")


@pytest.mark.parametrize(
    "actions,active,allowed", [(("rename",), True, False), (("edit",), True, True), (("edit",), False, True)]
)
async def test_custom_selection_is_preserved_without_inferring_edit(
    session_factory, monkeypatch, actions, active, allowed
):
    from bisheng.permission.domain.services.model_policy import CustomModelSelection

    custom = CustomModelSelection(model_key="custom-edit", name="Custom", action_codes=actions, active=active)
    value = await setup_catalog(session_factory, monkeypatch, customs=(custom,))
    before = await value.state.load_snapshot((await value.state.current_release()).id)
    target = await resource(value, model=custom.model_key)
    await apply(value)
    after = await value.state.load_snapshot((await value.state.current_release()).id)
    assert before.model_release.models == after.model_release.models
    # Catalog model active controls new assignment; existing Grants retain
    # their selected actions, matching the ordinary permission runtime.
    assert await decisions(value).check_action(PermissionActor(user_id=7, tenant_id=101), target, "edit") is allowed


async def test_cancelled_partial_staging_is_rebuilt_before_commit(legacy, monkeypatch):
    import asyncio

    stage = legacy.projector.stage_model_releases

    async def interrupted(draft):
        raise asyncio.CancelledError()

    monkeypatch.setattr(legacy.projector, "stage_model_releases", interrupted)
    with pytest.raises(asyncio.CancelledError):
        await apply(legacy, key="cancelled")
    row = await legacy.state.release_for_idempotency(publication_key("cancelled"))
    assert row.status == "PROJECTING"
    monkeypatch.setattr(legacy.projector, "stage_model_releases", stage)
    assert (await legacy.upgrade.resume(draft_id=row.id, operator_id=7, idempotency_key="cancelled"))[
        "event"
    ] == "verified"


async def test_disabled_edit_policy_is_not_enabled_by_upgrade(session_factory, monkeypatch):
    value = await setup_catalog(
        session_factory,
        monkeypatch,
        action_transform=lambda release: derive_action_release(
            replace(row, active=False) if row.code == "edit" else row for row in release.actions
        ),
    )
    result = await apply(value)
    assert result["edit_active"] is False


async def test_controlled_visibility_provenance_survives_upgrade(session_factory, monkeypatch):
    from bisheng.permission.domain.services.model_policy import CustomModelSelection

    custom = CustomModelSelection(
        "legacy-floor",
        "Legacy",
        ("download",),
        visibility_only_resource_types=("tool",),
        visibility_level=3,
        retired_use_level_floor=3,
    )
    value = await setup_catalog(session_factory, monkeypatch, customs=(custom,))
    await apply(value)
    snapshot = await value.state.load_snapshot((await value.state.current_release()).id)
    model = next(row for row in snapshot.model_release.models if row.model_key == custom.model_key)
    assert model.retired_use_level_floor == model.visibility_level == model.derived_level == 3
    assert model.visibility_only_resource_types == ("tool",)
    assert model.selected_action_codes == ("download",)


async def test_scope_metadata_does_not_change_authorization_model_checksum(monkeypatch):
    from bisheng.core.openfga import authorization_model_f048 as schema

    current = authorization_model_checksum(build_authorization_model_f048())
    old = dict(schema.RESOURCE_ACTION_SCOPES)
    old["edit"] = old["edit"] - EDIT_TYPES
    monkeypatch.setattr(schema, "RESOURCE_ACTION_SCOPES", old)
    assert authorization_model_checksum(build_authorization_model_f048()) == current


@pytest.mark.parametrize("size", [240, 480])
async def test_full_upgrade_cost_scales_with_grants_and_sources(legacy, monkeypatch, size):
    import json
    import time
    import tracemalloc

    from bisheng.permission.domain.models import PermissionGrant, PermissionGrantAssignee
    from bisheng.permission.domain.repositories.catalog_impact_repository import CatalogImpactRepository

    metrics = {"grant_rows": 0, "source_grants": 0}
    original_pages = CatalogImpactRepository.agrant_pages
    original_sources = CatalogImpactRepository.asource_summaries

    async def pages(self, keys):
        async for batch in original_pages(self, keys):
            assert len(batch) <= 200
            metrics["grant_rows"] += len(batch)
            yield batch

    async def sources(self, ids):
        assert len(ids) <= 200
        metrics["source_grants"] += len(ids)
        return await original_sources(self, ids)

    monkeypatch.setattr(CatalogImpactRepository, "agrant_pages", pages)
    monkeypatch.setattr(CatalogImpactRepository, "asource_summaries", sources)
    reports = []
    with bypass_tenant_filter():
        async with legacy.factory() as session, session.begin():
            for ident in range(1, size + 1):
                session.add(
                    PermissionGrant(
                        id=ident,
                        tenant_id=101 + ident % 2,
                        resource_type="knowledge_file",
                        resource_id=str(ident),
                        model_key="editor",
                        state="ACTIVE",
                        projection_state="CURRENT",
                    )
                )
                for member in range(3):
                    session.add(
                        PermissionGrantAssignee(
                            tenant_id=101 + ident % 2,
                            grant_id=ident,
                            subject_type="user",
                            subject_id=str(member),
                            source_type="DIRECT",
                            source_ref=str(member),
                            source_locator=str(member),
                            source_fingerprint=f"{ident * 10 + member:064x}",
                            projected_subject=f"user:{member}",
                            state="ACTIVE",
                        )
                    )
    statements = []
    async with legacy.factory() as session:
        engine = session.bind.sync_engine

    def sql(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    sa.event.listen(engine, "before_cursor_execute", sql)
    tracemalloc.start()
    started = time.monotonic()
    try:
        plan = await legacy.upgrade.plan()
        assert plan["impact"]["grant_count"] == size
        assert plan["impact"]["resource_count"] == size
        assert plan["impact"]["assignee_count"] == size * 3
        assert plan["impact"]["expansion_count"] == size * 3
        await legacy.upgrade.apply(plan_digest=plan["plan_digest"], operator_id=7, idempotency_key="scale")
        await legacy.upgrade.verify()
        scanned = dict(metrics)
        writes = len(legacy.fga.write_calls)
        await apply(legacy, key="repeat")
        assert metrics == scanned  # no-op does not scan resource membership
        assert len(legacy.fga.write_calls) == writes
        assert metrics["grant_rows"] == size * 5
        reports.append(
            dict(
                size=size,
                sql=len(statements),
                fga_writes=writes,
                **metrics,
                peak_bytes=tracemalloc.get_traced_memory()[1],
                seconds=time.monotonic() - started,
            )
        )
    finally:
        tracemalloc.stop()
        sa.event.remove(engine, "before_cursor_execute", sql)
    print("UPGRADE_SCALE=" + json.dumps(reports))
