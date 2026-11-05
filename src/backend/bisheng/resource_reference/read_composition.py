"""Actual source read graph shared by the existing API and worker hooks.

Construction performs no business/permission I/O. Readiness and source
authorization remain explicit at each admitted operation.
"""

from bisheng.assistant.application.reference_source_owner import AssistantReferenceSourceOwner
from bisheng.knowledge.application.reference_read_legacy_evidence import KnowledgeReferenceReadLegacyEvidence
from bisheng.knowledge.application.source_read_target_owner import KnowledgeSourceReadTargetOwner
from bisheng.llm.application.source_read_target_owner import ModelSourceReadTargetOwner
from bisheng.resource_reference.application.contracts import SourceType, TargetType
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
from bisheng.resource_reference.application.source_access import configure_reference_read_runtime
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository
from bisheng.workflow.application.reference_source_owner import WorkflowReferenceSourceOwner

_runtime: ReferenceSourceReadRuntime | None = None


def register() -> None:
    global _runtime
    if _runtime is None:
        verifier = SourceReadVerifier(
            {
                SourceType.WORKFLOW_VERSION: WorkflowReferenceSourceOwner(),
                SourceType.ASSISTANT: AssistantReferenceSourceOwner(),
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
