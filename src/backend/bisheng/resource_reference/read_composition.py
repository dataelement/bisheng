"""Actual source read graph shared by the existing API and worker hooks.

Construction performs no business/permission I/O. Readiness and source
authorization remain explicit at each admitted operation.
"""

from bisheng.app_publish.application.reference_source_owner import HostedAppReferenceSourceOwner
from bisheng.assistant.application.reference_source_owner import AssistantReferenceSourceOwner
from bisheng.channel.application.reference_source_owner import ChannelReferenceSourceOwner
from bisheng.knowledge.application.model_reference_read import (
    KnowledgeModelReadRuntime,
    configure_knowledge_model_read_runtime,
)
from bisheng.knowledge.application.reference_read_identity import KnowledgeModelReadIdentityPort
from bisheng.knowledge.application.reference_read_legacy_evidence import KnowledgeReferenceReadLegacyEvidence
from bisheng.knowledge.application.reference_source_owner import KnowledgeReferenceSourceOwner
from bisheng.knowledge.application.source_read_target_owner import KnowledgeSourceReadTargetOwner
from bisheng.llm.application.model_default_read import ModelDefaultReadRuntime, configure_model_default_read_runtime
from bisheng.llm.application.model_default_read_identity import ModelDefaultReadIdentityPort
from bisheng.llm.application.model_default_source_owner import ModelDefaultSourceOwner
from bisheng.llm.application.source_read_target_owner import ModelSourceReadTargetOwner
from bisheng.resource_reference.application.contracts import SourceType, TargetType
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
from bisheng.resource_reference.application.source_access import configure_reference_read_runtime
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository
from bisheng.workflow.application.reference_source_owner import WorkflowReferenceSourceOwner

_runtime: ReferenceSourceReadRuntime | None = None
_knowledge_model_runtime: KnowledgeModelReadRuntime | None = None
_model_default_runtime: ModelDefaultReadRuntime | None = None


def _model_graph(owner, identity_port, source_type):
    verifier = SourceReadVerifier({source_type: owner}, identity_port)
    legacy = KnowledgeReferenceReadLegacyEvidence(verifier)
    model = ModelSourceReadTargetOwner(verifier, legacy_evidence=legacy)
    return ReferenceSourceReadRuntime(verifier, SourceReadRepository(verifier), {TargetType.MODEL: model})


def register() -> None:
    global _runtime, _knowledge_model_runtime, _model_default_runtime
    if _runtime is None:
        verifier = SourceReadVerifier(
            {
                SourceType.WORKFLOW_VERSION: WorkflowReferenceSourceOwner(),
                SourceType.ASSISTANT: AssistantReferenceSourceOwner(),
                SourceType.HOSTED_APP_VERSION: HostedAppReferenceSourceOwner(),
                SourceType.CHANNEL_SYNC: ChannelReferenceSourceOwner(),
                SourceType.KNOWLEDGE: KnowledgeReferenceSourceOwner(),
            },
            AuthenticatedSourceReadIdentity(),
        )
        legacy = KnowledgeReferenceReadLegacyEvidence(verifier)
        knowledge = KnowledgeSourceReadTargetOwner(verifier, legacy_evidence=legacy)
        model = ModelSourceReadTargetOwner(verifier, legacy_evidence=legacy)
        _runtime = ReferenceSourceReadRuntime(
            verifier,
            SourceReadRepository(verifier),
            {TargetType.MODEL: model, TargetType.KNOWLEDGE_SPACE: knowledge, TargetType.KNOWLEDGE_FILE: knowledge},
        )
    configure_reference_read_runtime(_runtime)
    if _knowledge_model_runtime is None:
        identity = KnowledgeModelReadIdentityPort()
        owner = KnowledgeReferenceSourceOwner(identity_port=identity)
        _knowledge_model_runtime = KnowledgeModelReadRuntime(
            _model_graph(owner, identity, SourceType.KNOWLEDGE), identity
        )
    if _model_default_runtime is None:
        identity = ModelDefaultReadIdentityPort()
        owner = ModelDefaultSourceOwner(identity_port=identity)
        _model_default_runtime = ModelDefaultReadRuntime(
            _model_graph(owner, identity, SourceType.MODEL_DEFAULT), identity
        )
    configure_knowledge_model_read_runtime(_knowledge_model_runtime)
    configure_model_default_read_runtime(_model_default_runtime)
