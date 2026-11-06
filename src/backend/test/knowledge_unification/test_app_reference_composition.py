"""APP factories use distinct real source authorities. 覆盖 AC: AC-37, AC-68, AC-71, AC-79, AC-83, AC-86, AC-87, AC-89, AC-91, AC-92."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_publish import composition
from bisheng.app_publish.application import reference_access as access
from bisheng.app_publish.application.reference_read_identity import (
    AppManagementSourceReadIdentity,
    AppSourceReadIdentity,
)
from bisheng.app_publish.application.reference_source_owner import HostedAppReferenceSourceOwner
from bisheng.app_publish.domain.services.preview_access_service import PreviewQualification
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.knowledge.application.source_read_target_owner import KnowledgeSourceReadTargetOwner
from bisheng.llm.application.source_read_target_owner import ModelSourceReadTargetOwner
from bisheng.resource_reference.application.contracts import SourceType, TargetType
from bisheng.resource_reference.application.source_contracts import SourceReadRequest
from test.knowledge_unification import test_app_snapshot as fixtures

ctx = fixtures.ctx
resolving = fixtures.resolving
application = fixtures.application
writing = fixtures.writing


@pytest.fixture(autouse=True)
def isolated_access(monkeypatch):
    monkeypatch.setattr(access, "_runtime", None)
    monkeypatch.setattr(access, "_user_factory", None)


async def test_unconfigured_factories_fail_closed():
    with pytest.raises(ReferenceCoverageNotReadyError):
        await access.get_hosted_app_reference_runtime()
    with pytest.raises(ReferenceCoverageNotReadyError):
        await access.get_hosted_app_user_reference_runtime()


async def test_actual_existing_register_installs_separate_authorities_without_io():
    composition.register()
    hosted = await access.get_hosted_app_reference_runtime()
    user = await access.get_hosted_app_user_reference_runtime()
    q = PreviewQualification(101, "actual-app", "version", 22, "approval", 1, 2)
    review = await access.get_hosted_app_user_reference_runtime(q)
    assert isinstance(hosted.verifier._identity_port, AppSourceReadIdentity)
    assert isinstance(user.verifier._identity_port, AppManagementSourceReadIdentity)
    assert review.verifier._owners[SourceType.HOSTED_APP_VERSION].authorization_context is q
    assert hosted.verifier is not user.verifier and user.verifier is not review.verifier
    for runtime in (hosted, user, review):
        verifier = runtime.verifier
        assert isinstance(verifier._owners[SourceType.HOSTED_APP_VERSION], HostedAppReferenceSourceOwner)
        model = runtime.target_owners[TargetType.MODEL]
        knowledge = runtime.target_owners[TargetType.KNOWLEDGE_SPACE]
        assert isinstance(model, ModelSourceReadTargetOwner)
        assert isinstance(knowledge, KnowledgeSourceReadTargetOwner)
        assert knowledge is runtime.target_owners[TargetType.KNOWLEDGE_FILE]
        assert model.verifier is knowledge.verifier is runtime.repository.verifier is verifier
        assert model.legacy_evidence.repository.verifier is knowledge.legacy_evidence.repository.verifier is verifier
    assert hosted.target_owners[TargetType.MODEL] is not user.target_owners[TargetType.MODEL]


async def test_actual_app_source_and_real_target_owners_pass_core_then_reject_foreign_authority(writing):
    composition.register()
    runtime = await access.get_hosted_app_reference_runtime()
    async with AsyncSession(writing.engine) as session, session.begin():
        scope = await runtime.verifier.aissue_scope(
            session, SourceReadRequest(SourceType.HOSTED_APP_VERSION, "actual-app"), writing.identity
        )
        result = await runtime.arequire_source_valid(session, scope, writing.identity)
        assert all(item.is_valid for item in result.target_states)
        assert {item.key.target_id for item in result.target_states} == {"11", "7"}
        other = await access.get_hosted_app_user_reference_runtime()
        with pytest.raises(ResourceReferenceInvalidError):
            await other.arequire_source_valid(session, scope, writing.identity)
