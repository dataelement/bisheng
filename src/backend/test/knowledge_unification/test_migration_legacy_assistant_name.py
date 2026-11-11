"""Preserve unresolved old model names, knowledge guards and explicit repair."""

from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.api.services.assistant import AssistantService
from bisheng.assistant.application import reference_source_owner as owner_module
from bisheng.assistant.application.reference_source_owner import AssistantReferenceSourceOwner
from bisheng.assistant.domain.services.reference_extractor import (
    ASSISTANT_REFERENCE_EXTRACTOR_VERSION,
    extract_assistant_references,
    extract_legacy_assistant_knowledge_references,
    legacy_assistant_name_version,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.database.models.assistant import Assistant, AssistantLink
from bisheng.knowledge.application.source_read_target_owner import KnowledgeSourceReadTargetOwner
from bisheng.resource_reference.application.contracts import TargetKey, reference_set_digest
from bisheng.resource_reference.application.source_contracts import ReadIdentityFacts, SourceReadRequest
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository
from test.knowledge_unification import test_as_bindings as bindings
from test.knowledge_unification.test_migration_references_application import (
    app,
)
from test.knowledge_unification.test_migration_references_application import (
    complete as complete,
)
from test.knowledge_unification.test_migration_references_application import (
    native as native,
)
from test.knowledge_unification.test_migration_references_application import (
    published_input as published_input,
)
from test.knowledge_unification.test_migration_references_application import (
    raw_resource_native as raw_resource_native,
)
from test.knowledge_unification.test_migration_references_application import (
    resource_native as resource_native,
)
from test.knowledge_unification.test_migration_references_application import (
    transport as transport,
)

assistant_business = bindings.assistant_business
assistant_tenant = bindings.assistant_tenant
NAME = "gpt-4-0125-preview"


async def seed_legacy(database):
    from sqlmodel.ext.asyncio.session import AsyncSession

    async with AsyncSession(database.engine) as session, session.begin():
        session.add(Assistant(id="legacy-name", tenant_id=101, user_id=7, name="original", status=2, model_name=NAME))
        session.add(AssistantLink(tenant_id=101, assistant_id="legacy-name", knowledge_id=9000))


class Identity:
    async def acapture(self, identity):
        return ReadIdentityFacts(101, ("user", identity.user_id))


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_legacy}], indirect=True)
async def test_real_m4_retains_name_and_knowledge_guard_and_runtime_inspects_but_cannot_execute(
    published_input, monkeypatch
):
    value = published_input
    result = await app(value).arun_references(**value.input, operator_id=7)
    assert result.complete
    monkeypatch.setattr(owner_module, "require_business_action", AsyncMock())
    verifier = SourceReadVerifier({"assistant": AssistantReferenceSourceOwner()}, Identity())
    runtime = ReferenceSourceReadRuntime(
        verifier, SourceReadRepository(verifier), {"knowledge_space": KnowledgeSourceReadTargetOwner(verifier)}
    )
    user = UserPayload(user_id=7, tenant_id=101, user_name="owner", user_role=[])
    async with value.sessions() as session, session.begin():
        row = (
            (await session.execute(sa.select(Assistant.__table__).where(Assistant.id == "legacy-name")))
            .mappings()
            .one()
        )
        assert row["model_name"] == NAME and row["status"] == 2
        inbound = await ReferenceRepository().alist_inbound_targets(session, (TargetKey("knowledge_space", 9000),))
        assert any(ref.source_id == "legacy-name" for ref in inbound)
        source = (
            (
                await session.execute(
                    sa.select(BusinessReferenceSet.__table__).where(
                        BusinessReferenceSet.source_id == "legacy-name", BusinessReferenceSet.record_kind == "source"
                    )
                )
            )
            .mappings()
            .one()
        )
        assert (
            source["extractor_version"] == legacy_assistant_name_version(NAME)
            and source["ready"]
            and source["effective"]
        )
        scope = await verifier.aissue_scope(
            session, SourceReadRequest("assistant", "legacy-name", purpose="inspect"), user
        )
        inspected = await runtime.ainspect_source(session, scope, user)
        assert inspected.snapshot.invalid_reason == "assistant_legacy_model_name_unresolved"
        assert len(inspected.target_states) == 1 and inspected.target_states[0].is_valid
        scope = await verifier.aissue_scope(session, SourceReadRequest("assistant", "legacy-name"), user)
        with pytest.raises(ResourceReferenceInvalidError) as error:
            await runtime.arequire_source_valid(session, scope, user)
        assert error.value.kwargs["reason"] == "assistant_legacy_model_name_unresolved"
    assert await app(value).arun_references(**value.input, operator_id=7) == result


async def convert_seed_to_retained(context):
    await bindings.seed(context)
    references = extract_legacy_assistant_knowledge_references(model_name=NAME, knowledge_ids=[10])
    async with context.sessions() as session, session.begin():
        await session.execute(sa.update(Assistant).where(Assistant.id == "assistant-a").values(model_name=NAME))
        await session.execute(
            sa.delete(BusinessResourceReference).where(BusinessResourceReference.target_type == "model")
        )
        await session.execute(
            sa.update(BusinessReferenceSet)
            .where(BusinessReferenceSet.record_kind == "source")
            .values(extractor_version=legacy_assistant_name_version(NAME), digest=reference_set_digest(references))
        )


async def test_existing_marker_allows_same_name_edits_and_explicit_id_repair_but_not_publish_or_name_guess(
    assistant_business,
):
    ctx = assistant_business
    await convert_seed_to_retained(ctx)
    await AssistantService._persist_assistant_changes("assistant-a", ctx.user, changes={"prompt": "changed"})
    row, _links, refs, source = await bindings.inspect_business(ctx)
    assert row.model_name == NAME and source.extractor_version == legacy_assistant_name_version(NAME)
    assert {ref.target_id for ref in refs} == {"10"}
    with pytest.raises(ResourceReferenceInvalidError):
        await AssistantService._persist_assistant_changes(
            "assistant-a", ctx.user, changes={"status": 2}, action="publish", require_valid=True
        )
    with pytest.raises(ResourceReferenceInvalidError):
        await AssistantService._persist_assistant_changes(
            "assistant-a", ctx.user, changes={"model_name": "another-name"}
        )
    await AssistantService._persist_assistant_changes("assistant-a", ctx.user, changes={"model_name": "2"})
    row, _links, refs, source = await bindings.inspect_business(ctx)
    assert row.model_name == "2" and source.extractor_version == ASSISTANT_REFERENCE_EXTRACTOR_VERSION
    assert {ref.target_id for ref in refs} == {"2", "10"}


def test_names_never_enter_normal_new_or_copy_extraction():
    with pytest.raises(ValueError):
        extract_assistant_references(model_name=NAME, knowledge_ids=[10])
    assert legacy_assistant_name_version(NAME) != legacy_assistant_name_version("gpt-4o")


def test_assistant_details_expose_source_failure_without_a_fabricated_model_id():
    from bisheng.api.v1.schemas import AssistantInfo

    value = AssistantInfo(
        id="legacy",
        model_name=NAME,
        source_invalid_reason="assistant_legacy_model_name_unresolved",
        reference_states=[],
    )
    assert value.source_invalid_reason and value.model_name == NAME and not value.reference_states
    foreign = AssistantInfo(
        id="foreign",
        model_name="800",
        reference_states=[
            {
                "slot_key": "model_name",
                "target_type": "model",
                "target_id": "800",
                "state": "invalid_scope",
                "is_valid": False,
            }
        ],
    )
    assert foreign.reference_states[0].state == "invalid_scope"


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_legacy}], indirect=True)
async def test_changed_name_after_freeze_cannot_reuse_the_old_marker(published_input):
    value = published_input
    async with value.sessions() as session, session.begin():
        await session.execute(
            sa.update(Assistant).where(Assistant.id == "legacy-name").values(model_name="different-name")
        )
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await app(value).arun_references(**value.input, operator_id=7)


async def test_old_name_without_exact_registered_marker_cannot_be_saved(assistant_business):
    ctx = assistant_business
    await bindings.seed(ctx)
    async with ctx.sessions() as session, session.begin():
        await session.execute(sa.update(Assistant).where(Assistant.id == "assistant-a").values(model_name=NAME))
    with pytest.raises(ResourceReferenceInvalidError):
        await AssistantService._persist_assistant_changes("assistant-a", ctx.user, changes={"prompt": "changed"})


async def seed_legacy_with_known_model_binding(database):
    from sqlmodel.ext.asyncio.session import AsyncSession

    await seed_legacy(database)
    async with AsyncSession(database.engine) as session, session.begin():
        session.add(
            BusinessResourceReference(
                tenant_id=101,
                source_type="assistant",
                source_id="legacy-name",
                source_version="current",
                slot_key="model_name",
                target_type="model",
                target_id="11",
                target_tenant_id=1,
                source_revision=1,
            )
        )


async def test_legacy_name_retention_does_not_discard_a_known_original_model_binding(complete, transport, monkeypatch):
    from test.knowledge_unification.test_migration_source_lifecycle import freeze

    with pytest.raises(KnowledgeOperationPlanConflictError) as error:
        await freeze(complete, transport, monkeypatch, seed_legacy_with_known_model_binding)
    assert error.value.kwargs["reason"] == "unification_sources_legacy_assistant_existing_model_binding"


async def seed_legacy_missing_creator(database):
    from sqlmodel.ext.asyncio.session import AsyncSession

    await seed_legacy(database)
    async with AsyncSession(database.engine) as session, session.begin():
        await session.execute(sa.update(Assistant).where(Assistant.id == "legacy-name").values(user_id=999))


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_legacy_missing_creator}], indirect=True)
async def test_unusable_original_name_configuration_keeps_its_missing_owner_without_granting_a_new_one(published_input):
    value = published_input
    assert (await app(value).arun_references(**value.input, operator_id=7)).complete
    async with value.sessions() as session, session.begin():
        row = (
            (await session.execute(sa.select(Assistant.__table__).where(Assistant.id == "legacy-name")))
            .mappings()
            .one()
        )
        assert row["user_id"] == 999 and row["model_name"] == NAME
        from bisheng.permission.domain.models import PermissionGrant

        assert not (
            await session.execute(sa.select(PermissionGrant.id).where(PermissionGrant.resource_id == "legacy-name"))
        ).all()


async def seed_normal_missing_creator(database):
    from sqlmodel.ext.asyncio.session import AsyncSession

    await seed_legacy_missing_creator(database)
    async with AsyncSession(database.engine) as session, session.begin():
        await session.execute(sa.update(Assistant).where(Assistant.id == "legacy-name").values(model_name="11"))


async def test_another_source_cannot_borrow_invalid_name_creator_retention(complete, transport, monkeypatch):
    from test.knowledge_unification.test_migration_source_lifecycle import freeze

    with pytest.raises(KnowledgeOperationPlanConflictError) as error:
        await freeze(complete, transport, monkeypatch, seed_normal_missing_creator)
    assert error.value.kwargs["reason"] == "migration_inventory_source_creator_missing"


async def seed_inactive_deleted_model(database):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.permission.domain.models import PermissionGrant

    async with AsyncSession(database.engine) as session, session.begin():
        session.add(
            PermissionGrant(
                id=991,
                tenant_id=101,
                resource_type="knowledge_library",
                resource_id="9000",
                model_key="deleted-definition",
                state="INACTIVE",
                version=1,
                projection_state="CURRENT",
            )
        )


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_inactive_deleted_model}], indirect=True)
async def test_inert_missing_model_definition_survives_full_native_m2_m3_m4(published_input):
    from bisheng.permission.domain.models import PermissionGrant, PermissionModel

    value = published_input
    assert (await app(value).arun_references(**value.input, operator_id=7)).complete
    async with value.sessions() as session, session.begin():
        row = (
            (await session.execute(sa.select(PermissionGrant.__table__).where(PermissionGrant.id == 991)))
            .mappings()
            .one()
        )
        assert row["model_key"] == "deleted-definition" and row["state"] == "INACTIVE"
        assert not (
            await session.execute(
                sa.select(PermissionModel.id).where(PermissionModel.model_key == "deleted-definition")
            )
        ).all()
