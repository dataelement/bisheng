"""AC-14: a missing historical identity affects only its requested capability."""

import pytest
from sqlalchemy import delete
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_publish.domain.services import capability_bus_service as bus
from bisheng.app_publish.domain.services.saved_bindings import saved_bindings
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from test.knowledge_unification import test_app_saved_capabilities as fixtures

saved, writing, application = fixtures.saved, fixtures.writing, fixtures.application
ctx, resolving = fixtures.ctx, fixtures.resolving


async def test_legacy_model_binding_missing_keeps_knowledge_and_management_read(saved):
    async with AsyncSession(saved.engine) as session, session.begin():
        await session.execute(delete(BusinessResourceReference).where(BusinessResourceReference.target_type == "model"))
    rows = await bus.inspect_saved_capabilities("actual-app", fixtures.VERSION, saved.user)
    assert next(row for row in rows if row.kind == "model").reason == bus.REASON_UNRESOLVABLE
    assert next(row for row in rows if row.kind == "knowledge").reason == bus.REASON_OK


def test_explicit_knowledge_call_does_not_require_unrelated_unknown_binding():
    declaration = bus.EffectiveDeclaration(
        "app",
        101,
        "v",
        knowledge=(bus.DeclaredKnowledge("7", 7), bus.DeclaredKnowledge("old name", reason=bus.REASON_UNRESOLVABLE)),
    )
    bus.CapabilityBusService._assert_targets_declared(declaration, [7])
    with pytest.raises(ResourceReferenceInvalidError):
        _ = declaration.knowledge_whitelist


def test_new_snapshot_keeps_original_id_without_hint_rows():
    # Use the actual extractor's canonical slot, never a name lookup.
    from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration
    from bisheng.app_publish.domain.services.reference_extractor import extract_app_reference_requests

    slot = extract_app_reference_requests(CapabilityDeclaration.model_validate({"models": [{"name": "alpha"}]}))[
        0
    ].slot_key
    _, references, missing = saved_bindings(
        {"models": [{"name": "alpha"}]}, {"resource_bindings": {slot: {"target_type": "model", "target_id": "11"}}}
    )
    assert references[0].target.target_id == "11" and not missing


async def test_actual_model_call_accepts_known_binding_and_rejects_only_unknown_slot(writing, monkeypatch):
    application = writing
    from contextlib import asynccontextmanager

    from bisheng.app_publish import composition
    from bisheng.database.models.app_version import AppVersion
    from bisheng.llm.domain.services.model_catalog import ResolvedModel
    from test.knowledge_unification.test_app_source_owner import VERSION

    async with AsyncSession(application.engine) as session, session.begin():
        version = await session.get(AppVersion, VERSION)
        version.capabilities = {**version.capabilities, "models": [{"name": "alpha"}, {"name": "beta"}]}

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(application.engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(bus, "get_async_db_session", sessions)
    composition.register()
    resolved = ResolvedModel(11, 1, "alpha", "own", "openai", "own/alpha")
    await bus.HostedAppDeclarationAdapter().assert_model_binding(application.identity, "alpha", resolved)
    with pytest.raises(ResourceReferenceInvalidError) as error:
        await bus.HostedAppDeclarationAdapter().assert_model_binding(application.identity, "beta", resolved)
    assert error.value.kwargs["reason"] == "app_model_binding_unresolved"
