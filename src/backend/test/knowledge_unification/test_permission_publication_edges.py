"""Real parent/context facts, exact schema, source provenance and tail guards."""

import json

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.context.tenant import current_tenant_id
from bisheng.knowledge.application.unification_permissions import PermissionPublicationApplication
from bisheng.permission.domain.models import PermissionGrantAssignee, ResourcePermissionMode
from bisheng.permission.domain.repositories.f118_resource_write_repository import F118ResourceWriteRepository
from test.knowledge_unification.test_permission_publication_application import (
    app,
)
from test.knowledge_unification.test_permission_publication_application import (
    complete as complete,
)
from test.knowledge_unification.test_permission_publication_application import (
    native as native,
)
from test.knowledge_unification.test_permission_publication_application import (
    published_input as published_input,
)
from test.knowledge_unification.test_permission_publication_application import (
    raw_resource_native as raw_resource_native,
)
from test.knowledge_unification.test_permission_publication_application import (
    resource_native as resource_native,
)
from test.knowledge_unification.test_permission_publication_application import (
    transport as transport,
)


@pytest.mark.parametrize("published_input", [{"parent": True, "contexts": True}], indirect=True)
async def test_existing_parent_context_system_shared_and_source_identity_survive(published_input):
    value = published_input
    async with value.sessions() as session, session.begin():
        old_sources = [
            row.model_dump()
            for row in (
                await session.execute(sa.select(PermissionGrantAssignee).order_by(PermissionGrantAssignee.id))
            ).scalars()
        ]
    assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete
    for relation in ("visible", "system_download_marker", "system_use_marker"):
        assert ("user:*", relation, "knowledge_space:9000") in value.store.tuples
    assert ("tenant:202", "shared_with", "workflow:context-flow") in value.store.tuples
    assert ("knowledge_space:9000", "parent", "knowledge_file:1") in value.store.tuples
    assert ("knowledge_library:9000", "parent", "knowledge_file:1") not in value.store.tuples
    async with value.sessions() as session, session.begin():
        sources = [
            row.model_dump()
            for row in (
                await session.execute(sa.select(PermissionGrantAssignee).order_by(PermissionGrantAssignee.id))
            ).scalars()
        ]
        assert sources == old_sources
        child = (
            await session.execute(sa.select(ResourcePermissionMode).where(ResourcePermissionMode.id == 1))
        ).scalar_one()
        assert (child.resource_type, child.parent_type, child.parent_id, child.version) == (
            "knowledge_file",
            "knowledge_space",
            "9000",
            1,
        )


@pytest.mark.parametrize(
    "published_input",
    [
        {"raw_edge": ("tenant:202", "shared_with", "knowledge_library:9000")},
        {"raw_edge": ("user:*", "public_reader", "knowledge_library:9000")},
        {"raw_edge": ("knowledge_library:9000#reader", "member", "tenant:202")},
        {"raw_edge": ("user:7", "rename", "knowledge_library:9000")},
    ],
    indirect=True,
)
async def test_frozen_unknown_or_business_ineligible_namespace_edges_never_become_grants(published_input):
    value = published_input
    with pytest.raises(BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    assert value.store.writes == 0
    assert not any(
        request.method == "POST" and request.url.path.endswith("/authorization-models")
        for request in value.store.requests
    )


@pytest.mark.parametrize("fault", ["tenant", "source_pin", "target_pin"])
async def test_actual_transport_await_drift_stops_with_original_pending_intent(published_input, monkeypatch, fault):
    value = published_input
    from bisheng.permission.application.f118_permission_publish import F118PermissionPublisher

    original = F118PermissionPublisher.__aenter__
    active = None

    async def enter(self):
        nonlocal active
        active = await original(self)
        return active

    monkeypatch.setattr(F118PermissionPublisher, "__aenter__", enter)
    token = None
    fired = False

    async def drift(request):
        nonlocal token, fired
        if request.url.path.endswith("/write") and not fired:
            fired = True
            if fault == "tenant":
                token = current_tenant_id.set(202)
            elif fault == "source_pin":
                active.source._model_id = "untrusted-model"
            else:
                active.target._model_id = "untrusted-model"

    value.store.on_request = drift
    try:
        with pytest.raises(BaseErrorCode):
            await app(value).arun_permissions(**value.input, operator_id=7)
        assert fired
    finally:
        if token is not None:
            current_tenant_id.reset(token)
    value.sessions.assert_closed()
    value.store.on_request = None
    assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete


async def test_sql_after_is_rechecked_inside_final_pointer_transaction(published_input, monkeypatch):
    value = published_input
    original = F118ResourceWriteRepository.alist_resources
    seen_final = False

    async def corrupt(self, session, *, lock=False):
        nonlocal seen_final
        if lock and not seen_final:
            seen_final = True
            await session.execute(
                sa.update(ResourcePermissionMode.__table__)
                .where(ResourcePermissionMode.__table__.c.id == 9000)
                .values(version=99)
            )
        return await original(self, session, lock=lock)

    monkeypatch.setattr(F118ResourceWriteRepository, "alist_resources", corrupt)
    with pytest.raises(BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    assert seen_final
    # The malicious final transaction itself rolls back, so the same genuine
    # Run resumes from its acknowledged pointer and completes without new FGA.
    writes = value.store.writes
    assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete
    assert value.store.writes == writes


async def test_actual_pin_fields_in_checkpoint_cannot_repin_transport(published_input, monkeypatch):
    value = published_input
    original = PermissionPublicationApplication._get

    async def tamper(self, frozen, key):
        result = await original(self, frozen, key)
        if key == "permission_catalog" and result is not None:
            cursor = json.loads(result["cursor"])
            cursor["authorization"]["required_relations_checksum"] = "f" * 64
            return self._value(cursor, 0, complete=True)
        return result

    value.store.fail_write = 1
    with pytest.raises(BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    value.store.fail_write = None
    writes = value.store.writes
    monkeypatch.setattr(PermissionPublicationApplication, "_get", tamper)
    with pytest.raises(BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    assert value.store.writes == writes


@pytest.mark.parametrize("published_input", [{"same": True, "history": True}], indirect=True)
async def test_earlier_retired_same_checksum_cannot_steal_original_active_pin(published_input):
    value = published_input
    from bisheng.permission.domain.models import AuthorizationModelRelease

    async with value.sessions() as session, session.begin():
        before = (
            (
                await session.execute(
                    sa.select(AuthorizationModelRelease.__table__).order_by(AuthorizationModelRelease.__table__.c.id)
                )
            )
            .mappings()
            .all()
        )
    assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete
    async with value.sessions() as session, session.begin():
        after = (
            (
                await session.execute(
                    sa.select(AuthorizationModelRelease.__table__).order_by(AuthorizationModelRelease.__table__.c.id)
                )
            )
            .mappings()
            .all()
        )
    assert before == after and [row["id"] for row in after] == [1, 3]
    assert value.before.authorization.id == 3
    assert not any(
        request.method == "POST" and request.url.path.endswith("/authorization-models")
        for request in value.store.requests
    )


async def test_new_foreign_source_after_freeze_is_not_hidden_by_tenant_filter(published_input):
    value = published_input
    async with value.sessions() as session, session.begin():
        await session.execute(
            sa.update(PermissionGrantAssignee.__table__)
            .where(PermissionGrantAssignee.__table__.c.id == 101)
            .values(tenant_id=202)
        )
    with pytest.raises(BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    assert value.store.writes == 0
    assert not any(
        request.method == "POST" and request.url.path.endswith("/authorization-models")
        for request in value.store.requests
    )


@pytest.mark.parametrize("published_input", [True], indirect=True)
async def test_same_active_auth_full_raw_tail_cannot_be_changed_by_catalog_trigger(published_input):
    value = published_input
    async with value.database.engine.begin() as connection:
        await connection.exec_driver_sql(
            f"CREATE TRIGGER f118_auth_tail AFTER UPDATE OF status ON permission_catalog_release WHEN NEW.status='CURRENT' BEGIN UPDATE authorization_model_release SET create_time='2099-01-01 00:00:00' WHERE id={value.before.authorization.id}; END"
        )
    with pytest.raises(BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    writes = value.store.writes
    async with value.database.engine.begin() as connection:
        await connection.exec_driver_sql("DROP TRIGGER f118_auth_tail")
    assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete
    assert value.store.writes == writes


async def test_bounded_real_catalog_snapshot_preserves_original_publication_payload(published_input):
    value = published_input
    from bisheng.core.openfga.authorization_model_f048 import (
        authorization_model_checksum,
        build_authorization_model_f048,
    )
    from bisheng.permission.application.catalog_api import SqlCatalogState
    from bisheng.permission.application.f118_permission_publish import F118PermissionPublisher
    from bisheng.permission.domain.models import PermissionCatalogRelease
    from bisheng.permission.domain.repositories.f118_catalog_write_repository import F118CatalogWriteRepository
    from bisheng.permission.migration.f118_plan import ResourceRetirementPlanner, build_catalog_retirement_plan

    value.store.fail_write = 1
    with pytest.raises(BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    planner = ResourceRetirementPlanner(
        catalog_plan=build_catalog_retirement_plan(
            run_id=value.frozen.run_id,
            writer_contract_version=value.frozen.writer_contract_version,
            before=value.before,
            target_model_checksum=authorization_model_checksum(build_authorization_model_f048()),
            namespace_type_mappings=(("knowledge_library", "knowledge_space"),),
        )
    )
    async with value.sessions() as session, session.begin():
        row = (
            await session.execute(sa.select(PermissionCatalogRelease).where(PermissionCatalogRelease.status == "DRAFT"))
        ).scalar_one()
        actual = await F118CatalogWriteRepository().averify_staged_catalog(
            session,
            permission_planner=planner,
            draft_id=row.id,
            target_authorization_release_id=row.required_authorization_model_release_id,
            operator_id=7,
            idempotency_key=row.idempotency_key,
        )
    original = await SqlCatalogState(session_factory=value.sessions).load_snapshot(row.id)
    assert (
        F118PermissionPublisher(catalog_plan=planner.catalog_plan, session_factory=value.sessions).stage_snapshot(
            actual
        )
        == original
    )
