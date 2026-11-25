"""Version deletion and copy/import respect the saved source lifecycle.

覆盖 AC: AC-68, AC-87, AC-88, AC-89, AC-91, AC-92.
"""

import pytest

from bisheng.api.services import flow as flow_service
from bisheng.api.v1.schemas import FlowVersionCreate
from bisheng.common.errcode.flow import CurVersionDelError
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.database.models.flow_version import FlowVersion
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


async def delete(context, version_id=2):
    return await flow_service.FlowService.delete_version(context.user, version_id)


async def test_delete_only_one_version_releases_only_its_set_and_preserves_definition(configured):
    old = next(row for row in rows(configured, "business_reference_set") if row["source_version"] == "1")
    assert (await delete(configured)).status_code == 200
    await save_fixtures.refresh(configured)
    assert {(row["source_version"], row["slot_key"]) for row in rows(configured, "business_resource_reference")} == {
        ("1", "node:old-current.model_id")
    }
    current_set = next(row for row in rows(configured, "business_reference_set") if row["source_version"] == "1")
    assert current_set["digest"] == old["digest"]
    assert not [row for row in rows(configured, "business_reference_set") if row["source_version"] == "2"]
    async with configured.session_factory() as session:
        version = await session.get(FlowVersion, 2)
        assert version.is_delete == 1 and version.data["nodes"]


async def test_delete_version_does_not_call_legacy_binding_writer(configured, monkeypatch):
    from unittest.mock import AsyncMock

    before_refs = rows(configured, "business_resource_reference")
    before_sets = rows(configured, "business_reference_set")
    binding = AsyncMock(side_effect=RuntimeError("binding delete failed"))
    monkeypatch.setattr(configured.runtime, "aapply_source_bindings", binding)
    assert (await delete(configured)).status_code == 200
    assert next(row for row in rows(configured, "flowversion") if row["id"] == 2)["is_delete"] == 1
    assert rows(configured, "business_resource_reference") == before_refs
    assert rows(configured, "business_reference_set") == before_sets
    binding.assert_not_awaited()


async def test_current_version_delete_keeps_original_business_restriction(configured):
    before = rows(configured, "business_resource_reference")
    assert (await delete(configured, 1)).status_code == CurVersionDelError.Code
    assert rows(configured, "business_resource_reference") == before


async def test_original_deleted_target_can_be_unbound_by_deleting_its_source_version(configured):
    await current_fixtures.force_delete_model(configured)
    assert (await delete(configured)).status_code == 200
    await save_fixtures.refresh(configured)
    assert [(row["source_version"], row["target_id"]) for row in rows(configured, "business_resource_reference")] == [
        ("1", "7")
    ]


async def test_delete_version_ignores_stale_auxiliary_index(configured):
    async with configured.session_factory() as session, session.begin():
        version = await session.get(FlowVersion, 2)
        version.data = graph(node("drift", "llm", model_id=7))
    assert (await delete(configured)).status_code == 200
    assert next(row for row in rows(configured, "flowversion") if row["id"] == 2)["is_delete"] == 1


async def test_copy_version_cannot_borrow_original_source_deleted_target_evidence(configured):
    await current_fixtures.force_delete_model(configured)
    with pytest.raises(ResourceReferenceInvalidError):
        await flow_service.FlowService.create_new_version(
            configured.user,
            "wf",
            FlowVersionCreate(name="copy", original_version_id=2, data=graph(node("a", "llm", model_id=7))),
        )
    assert {row["id"] for row in rows(configured, "flowversion")} == {1, 2, 3}


async def test_imported_new_root_cannot_borrow_original_source_deleted_target_evidence(configured):
    await current_fixtures.force_delete_model(configured)
    before = rows(configured, "flow")
    with pytest.raises(ResourceReferenceInvalidError):
        await create_fixtures.create(configured, name="import", saved_data=graph(node("a", "llm", model_id=7)))
    assert rows(configured, "flow") == before


async def test_restoring_deleted_version_must_reverify_historical_slots_as_new_bindings(configured):
    await current_fixtures.force_delete_model(configured)
    async with configured.session_factory() as session, session.begin():
        version = await session.get(FlowVersion, 3)
        version.data = graph(node("historical", "llm", model_id=7))
    with pytest.raises(ResourceReferenceInvalidError):
        await save_fixtures.save(configured, 3, None)
    assert next(row for row in rows(configured, "flowversion") if row["id"] == 3)["is_delete"] == 1
