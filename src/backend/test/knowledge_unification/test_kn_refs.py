"""Knowledge impact uses real closure, Owner, inbound stream and privacy routing."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import update

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.application.reference_target_owner import KnowledgeReferenceTargetOwner
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services import knowledge_reference_service as module
from bisheng.permission.application.identity import PermissionActor
from bisheng.resource_reference.application import read_identity
from bisheng.resource_reference.application.contracts import SourceType
from bisheng.resource_reference.application.source_disclosure import SourceDisclosure, SourceDisclosureRuntime
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_direct_delete_reference_query as native

deletion_tenant, db, context = native.deletion_tenant, native.db, native.context


class MetadataTransport:
    def __init__(self):
        self.calls = []

    async def adisclose_sources(self, session, *, identity, source_keys):
        assert session.in_transaction()
        self.calls.append(source_keys)
        return tuple(
            None
            if key.source_id.startswith("hidden")
            else SourceDisclosure(key, "name-" + key.source_id, key.source_version, "/source/" + key.source_id)
            for key in source_keys
        )


@pytest.fixture
def service(context, monkeypatch):
    actor = PermissionActor(user_id=7, current_tenant_id=101, super_admin=True)
    monkeypatch.setattr(read_identity, "resolve_permission_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(read_identity, "get_current_open_api_principal", lambda: None)
    monkeypatch.setattr(read_identity, "get_current_public_api_principal", lambda: None)
    monkeypatch.setattr(module, "require_business_action", AsyncMock())

    async def permitted(identity, *, resource_type, resource_ids, actions):
        return {str(ident): set(actions) for ident in resource_ids}

    monkeypatch.setattr(module, "batch_check_business_actions", permitted)
    owner = KnowledgeReferenceTargetOwner()
    verifier = ReferenceTargetVerifier({"knowledge_space": owner, "knowledge_file": owner})
    runtime = ReferenceBindingRuntime(ReferenceRepository(verifier=verifier), verifier)
    metadata = MetadataTransport()
    result = module.KnowledgeReferenceService(
        coverage_factory=context.factory,
        runtime=runtime,
        disclosure_runtime=SourceDisclosureRuntime(dict.fromkeys(SourceType, metadata)),
        session_factory=context.db.sessions,
    )
    result.user = UserPayload(user_id=7, user_name="operator", tenant_id=101, user_role=[], is_global_super=True)
    result.metadata = metadata
    return result


async def test_whole_space_includes_root_directory_history_and_cross_tenant_facts_without_disclosure(context, service):
    await native.seed(
        context,
        (1, 101, "workflow_version", "space", "1", "space", "knowledge_space"),
        (31, 101, "assistant", "visible", "current", "history"),
        (20, 101, "workflow_version", "hidden-dir", "1", "directory"),
        (30, 202, "assistant", "foreign-secret", "current", "file"),
    )
    direct = await service.ainspect(
        identity=service.user, space_id=1, selections=native.selections(("knowledge_file", 31))
    )
    assert sum(dict(direct.slot_counts).values()) == 1
    whole = await service.ainspect(identity=service.user, space_id=1, whole_space=True)
    assert whole.blocked and sum(dict(whole.slot_counts).values()) == 4
    assert sum(dict(whole.restricted_counts).values()) == 2
    assert all(key.tenant_id == 101 for batch in service.metadata.calls for key in batch)
    from bisheng.knowledge.api.endpoints.references import inspection_response

    public = inspection_response(whole)
    assert "foreign-secret" not in repr(public)
    assert "facts" not in public and "scope" not in public and "source_counts" in public
    assert "hidden-dir" not in repr(public)


async def test_empty_space_still_checks_coverage_and_current_root(context, service):
    actual = await service.ainspect(identity=service.user, space_id=2, whole_space=True)
    assert not actual.blocked and not actual.facts.scope.resources
    assert actual.facts.scope.cleanup_identity["id"] == 2
    context.failure = "global"
    with pytest.raises(ReferenceCoverageNotReadyError):
        await service.ainspect(identity=service.user, space_id=2, whole_space=True)


async def test_source_cursor_ignores_only_trace_and_rejects_changed_physical_scope(context, service):
    await native.seed(
        context, (31, 101, "assistant", "a", "current", "one"), (31, 101, "assistant", "b", "current", "two")
    )
    selections = native.selections(("knowledge_file", 31))
    first = await service.ainspect(identity=service.user, space_id=1, selections=selections, source_page_size=1)
    token = read_identity.trace_id_var.set("new-request-trace")
    try:
        page = await service.alist_sources(
            identity=service.user, space_id=1, selections=selections, cursor=first.source_page.next_cursor, page_size=1
        )
        assert len(page.data) == 1 and page.data[0].disclosure.source.source_id == "b"
        async with context.db.sessions() as session, session.begin():
            await session.execute(update(KnowledgeFile).where(KnowledgeFile.id == 31).values(file_name="changed"))
        with pytest.raises(ResourceReferenceInvalidError):
            await service.alist_sources(
                identity=service.user,
                space_id=1,
                selections=selections,
                cursor=first.source_page.next_cursor,
                page_size=1,
            )
    finally:
        read_identity.trace_id_var.reset(token)


async def test_whole_space_retains_known_legacy_missing_but_rejects_new_unexplained_missing_target(context, service):
    await native.seed(context, (999, 101, "assistant", "legacy", "current", "missing"))
    with pytest.raises(ReferenceCoverageNotReadyError):
        await service.ainspect(identity=service.user, space_id=1, whole_space=True)
    async with context.db.sessions() as session, session.begin():
        await session.execute(
            update(BusinessResourceReference).values(
                target_tenant_id=None,
                legacy_invalid_reason="target_missing",
                legacy_run_id="frozen-run",
                legacy_evidence_key="original-evidence",
            )
        )
    result = await service.ainspect(identity=service.user, space_id=1, whole_space=True)
    assert result.blocked and sum(dict(result.slot_counts).values()) == 1


async def test_space_inventory_does_not_hide_foreign_owner_files_under_the_actual_root(context, service):
    async with context.db.sessions() as session, session.begin():
        with bypass_tenant_filter():
            await session.execute(update(KnowledgeFile).where(KnowledgeFile.id == 60).values(tenant_id=202))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await service.ainspect(identity=service.user, space_id=1, whole_space=True)
