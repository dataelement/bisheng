"""F004 root deletion releases every live version in one SQL unit.

覆盖 AC: AC-87, AC-88, AC-89. The actual DELETE endpoint is invoked. SQL
targets, binding sets and definitions remain real; permission projection is an
observed transport boundary, never an alternate reference Owner.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa

from bisheng.api.services import flow as flow_service
from bisheng.api.v1 import flows as endpoint
from bisheng.api.v1.schemas import FlowVersionCreate
from bisheng.core.context.tenant import current_tenant_id, management_tenant_scope, set_current_tenant_id
from bisheng.database.models.flow_version import FlowVersion
from bisheng.resource_reference.application.bindings import ReferenceBindings
from bisheng.resource_reference.application.contracts import reference_set_digest
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.workflow.domain.repositories.workflow_version_repository import WorkflowVersionRepository
from test.knowledge_unification import test_wf_create as create_fixtures
from test.knowledge_unification import test_wf_current as current_fixtures
from test.knowledge_unification import test_wf_save as save_fixtures
from test.knowledge_unification.test_wf_extract import graph, node

store = create_fixtures.store
tenant = create_fixtures.tenant
bindings = create_fixtures.bindings
saved = save_fixtures.saved
configured = current_fixtures.configured
rows = create_fixtures.rows


@pytest.fixture
async def deleting(configured, monkeypatch):
    configured.cleanup_projection = AsyncMock()
    configured.delete_receipt = (SimpleNamespace(cleanup_deleted=configured.cleanup_projection), object(), object())
    configured.delete_projection = AsyncMock(return_value=configured.delete_receipt)
    monkeypatch.setattr(flow_service.FlowService, "project_flow_delete", configured.delete_projection)
    monkeypatch.setattr(flow_service.FlowService, "delete_flow_hook", Mock())
    return configured


async def delete(context):
    return await endpoint.delete_flow(request=context.request, flow_id="wf", login_user=context.user)


async def test_actual_root_delete_preserves_all_definitions_and_releases_all_live_versions(deleting):
    blank = await flow_service.FlowService.create_new_version(
        deleting.user, "wf", FlowVersionCreate(name="blank", data={})
    )
    before_ids = {row["id"] for row in rows(deleting, "flowversion")}
    assert blank.data.id in before_ids
    result = await delete(deleting)
    assert result.status_code == 200
    assert next(row for row in rows(deleting, "flow") if row["id"] == "wf")["is_delete"] == 1
    assert {row["id"] for row in rows(deleting, "flowversion")} == before_ids
    assert all(row["is_delete"] == 1 for row in rows(deleting, "flowversion"))
    await save_fixtures.refresh(deleting)
    assert not rows(deleting, "business_resource_reference")
    deleting.cleanup_projection.assert_awaited_once()
    sources = [row for row in rows(deleting, "business_reference_set") if row["record_kind"] == "source"]
    assert not sources
    deleting.delete_projection.assert_awaited_once()


async def test_root_delete_never_calls_legacy_binding_writer(deleting, monkeypatch):
    binding = AsyncMock(side_effect=RuntimeError("source binding failed"))
    monkeypatch.setattr(ReferenceBindings, "areplace_source_bindings", binding)
    before = rows(deleting, "business_resource_reference")
    assert (await delete(deleting)).status_code == 200
    assert rows(deleting, "business_resource_reference") == before
    assert all(row["is_delete"] == 1 for row in rows(deleting, "flowversion"))
    binding.assert_not_awaited()
    deleting.delete_projection.assert_awaited_once()


async def test_missing_live_version_index_does_not_block_business_delete(deleting):
    async with deleting.session_factory() as session, session.begin():
        await session.execute(
            sa.delete(BusinessReferenceSet).where(
                BusinessReferenceSet.source_id == "wf", BusinessReferenceSet.source_version == "2"
            )
        )
    assert (await delete(deleting)).status_code == 200
    assert next(row for row in rows(deleting, "flow") if row["id"] == "wf")["is_delete"] == 1
    deleting.delete_projection.assert_awaited_once()


async def test_stale_version_index_does_not_block_business_delete(deleting):
    async with deleting.session_factory() as session, session.begin():
        version = await session.get(FlowVersion, 2)
        version.data = graph(node("drift", "llm", model_id=7))
    assert (await delete(deleting)).status_code == 200
    assert next(row for row in rows(deleting, "flow") if row["id"] == "wf")["is_delete"] == 1
    deleting.delete_projection.assert_awaited_once()


async def test_permission_projection_sees_existing_committed_root_before_final_sql_delete(deleting):
    async def before_commit(user, root):
        assert any(row["id"] == root.id and row["is_delete"] == 0 for row in rows(deleting, "flow"))
        assert len(rows(deleting, "business_resource_reference")) == 3
        return deleting.delete_receipt

    deleting.delete_projection.side_effect = before_commit
    await delete(deleting)
    await save_fixtures.refresh(deleting)
    assert not rows(deleting, "business_resource_reference")


async def test_projection_failure_rolls_back_all_root_and_source_changes(deleting):
    before = {
        table: rows(deleting, table)
        for table in ("flow", "flowversion", "business_reference_set", "business_resource_reference")
    }
    deleting.delete_projection.side_effect = RuntimeError("projection failed")
    with pytest.raises(RuntimeError, match="projection failed"):
        await delete(deleting)
    for table, expected in before.items():
        assert rows(deleting, table) == expected


async def test_root_delete_can_release_original_invalid_references_with_real_tombstone(deleting):
    await current_fixtures.force_delete_model(deleting)
    assert (await delete(deleting)).status_code == 200
    await save_fixtures.refresh(deleting)
    assert not rows(deleting, "business_resource_reference")


@pytest.mark.parametrize("effective", [True, False])
async def test_orphan_indexed_source_does_not_block_root_delete(deleting, effective):
    async with deleting.session_factory() as session, session.begin():
        session.add(
            BusinessReferenceSet(
                tenant_id=101,
                source_type="workflow_version",
                source_id="wf",
                source_version="999",
                source_revision=1,
                extractor_version="workflow-version-v1",
                digest=reference_set_digest(()),
                record_kind="source",
                ready=True,
                effective=effective,
            )
        )
    assert (await delete(deleting)).status_code == 200
    assert next(row for row in rows(deleting, "flow") if row["id"] == "wf")["is_delete"] == 1
    deleting.delete_projection.assert_awaited_once()


@pytest.mark.parametrize("corruption", ["active", "unready", "nonempty_digest"])
async def test_stale_terminal_index_does_not_block_root_delete(deleting, corruption):
    async with deleting.session_factory() as session, session.begin():
        source = await session.scalar(
            sa.select(BusinessReferenceSet).where(
                BusinessReferenceSet.source_id == "wf", BusinessReferenceSet.source_version == "3"
            )
        )
        if source is None:
            source = BusinessReferenceSet(
                tenant_id=101,
                source_type="workflow_version",
                source_id="wf",
                source_version="3",
                source_revision=1,
                extractor_version="workflow-version-v1",
                digest=reference_set_digest(()),
                ready=True,
                effective=False,
            )
            session.add(source)
        if corruption == "active":
            source.effective = True
        elif corruption == "unready":
            source.ready = False
        else:
            source.digest = "f" * 64
    assert (await delete(deleting)).status_code == 200
    assert next(row for row in rows(deleting, "flow") if row["id"] == "wf")["is_delete"] == 1
    deleting.delete_projection.assert_awaited_once()


async def test_root_delete_keeps_pinned_management_tenant_separate_from_identity_home(deleting):
    deleting.user.tenant_id = 1
    token = set_current_tenant_id(1)
    try:
        with management_tenant_scope(101):
            assert (await delete(deleting)).status_code == 200
    finally:
        current_tenant_id.reset(token)
    assert deleting.user.tenant_id == 1
    assert all(row["tenant_id"] == 101 for row in rows(deleting, "business_reference_set"))
    await save_fixtures.refresh(deleting)
    assert not rows(deleting, "business_resource_reference")


async def test_root_delete_includes_version_committed_before_root_lock(deleting, monkeypatch):
    original = WorkflowVersionRepository.alock_root
    added = []

    async def concurrent_create_before_root_lock(session, flow_id, tenant_id):
        if not added:
            added.append(None)
            result = await flow_service.FlowService.create_new_version(
                deleting.user, "wf", FlowVersionCreate(name="concurrent", data={})
            )
            added[0] = result.data.id
        return await original(session, flow_id, tenant_id)

    monkeypatch.setattr(WorkflowVersionRepository, "alock_root", concurrent_create_before_root_lock)
    assert (await delete(deleting)).status_code == 200
    assert added[0] is not None
    assert next(row for row in rows(deleting, "flowversion") if row["id"] == added[0])["is_delete"] == 1
    assert next(row for row in rows(deleting, "flow") if row["id"] == "wf")["is_delete"] == 1
    deleting.delete_projection.assert_awaited_once()


@pytest.mark.parametrize("corruption", ["deleted_without_set", "unknown_without_set", "terminal_with_raw_row"])
async def test_orphan_reference_does_not_block_business_delete_and_is_refreshed(deleting, corruption):
    source_version = "999" if corruption == "unknown_without_set" else "3"
    async with deleting.session_factory() as session, session.begin():
        if corruption == "deleted_without_set":
            await session.execute(
                sa.delete(BusinessReferenceSet).where(
                    BusinessReferenceSet.source_type == "workflow_version",
                    BusinessReferenceSet.source_id == "wf",
                    BusinessReferenceSet.source_version == "3",
                )
            )
        session.add(
            BusinessResourceReference(
                tenant_id=101,
                source_type="workflow_version",
                source_id="wf",
                source_version=source_version,
                slot_key="node:orphan.model_id",
                target_type="model",
                target_id="7",
                target_tenant_id=101,
                source_revision=1,
            )
        )
    assert (await delete(deleting)).status_code == 200
    await save_fixtures.refresh(deleting)
    assert not rows(deleting, "business_resource_reference")
    deleting.delete_projection.assert_awaited_once()


async def test_legacy_deleted_version_without_set_or_raw_references_does_not_get_new_index(deleting):
    async with deleting.session_factory() as session, session.begin():
        await session.execute(
            sa.delete(BusinessReferenceSet).where(
                BusinessReferenceSet.source_id == "wf", BusinessReferenceSet.source_version == "3"
            )
        )
    assert (await delete(deleting)).status_code == 200
    assert not any(row["source_version"] == "3" for row in rows(deleting, "business_reference_set"))
    await save_fixtures.refresh(deleting)
    assert not rows(deleting, "business_resource_reference")


async def test_root_reference_inventory_is_exact_tenant_type_root_and_stably_ordered(deleting, monkeypatch):
    from sqlmodel import Session

    from bisheng.core.database import tenant_filter
    from test.knowledge_unification.test_wf_save import key

    # The isolated workflow fixture creates only its tables; activate the real
    # C3 listener for this explicit cross-tenant query regression.
    names = tenant_filter._tenant_aware_tables | {BusinessResourceReference.__tablename__}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    tenant_filter.register_tenant_filter_events()
    async with deleting.session_factory() as session, session.begin():
        for tenant_id, source_type, source_id, version, slot in (
            (101, "workflow_version", "wf", "10", "node:z.model_id"),
            (101, "workflow_version", "wf", "10", "node:a.model_id"),
            (101, "workflow_version", "other", "10", "node:a.model_id"),
            (101, "assistant", "wf", "10", "node:a.model_id"),
            (202, "workflow_version", "wf", "10", "node:a.model_id"),
        ):
            session.add(
                BusinessResourceReference(
                    tenant_id=tenant_id,
                    source_type=source_type,
                    source_id=source_id,
                    source_version=version,
                    slot_key=slot,
                    target_type="model",
                    target_id="7",
                    target_tenant_id=101,
                    source_revision=1,
                )
            )
    async with deleting.session_factory() as session:
        actual = await deleting.repository.alist_source_references_for_root(session, key(1), for_update=True)
        identities = [(row.source_version, row.slot_key, row.target_type, row.target_id) for row in actual]
        assert identities == sorted(identities)
        assert len(actual) == 5
        assert all((row.tenant_id, row.source_type, row.source_id) == (101, "workflow_version", "wf") for row in actual)
    with Session(deleting.sync_engine) as session:
        actual_sync = deleting.repository.list_source_references_for_root(session, key(1), for_update=True)
        assert [(row.source_version, row.slot_key, row.target_type, row.target_id) for row in actual_sync] == identities
