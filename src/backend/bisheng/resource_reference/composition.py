"""Process composition root; the reference core depends only on Owner ports.

Both API and worker bootstrap call register. Construction does no SQL, FGA or
migration I/O; coverage remains a separate, persistent fail-closed gate.
"""

from bisheng.knowledge.application.reference_legacy_evidence import KnowledgeLegacyReferenceEvidence
from bisheng.knowledge.application.reference_target_owner import KnowledgeReferenceTargetOwner
from bisheng.llm.application.reference_target_owner import ModelReferenceTargetOwner
from bisheng.resource_reference.application.access import configure_reference_binding_runtime
from bisheng.resource_reference.application.contracts import TargetType
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository

_runtime: ReferenceBindingRuntime | None = None


def register() -> None:
    from bisheng.resource_reference.read_composition import register as register_source_reads

    global _runtime
    if _runtime is None:
        evidence = KnowledgeLegacyReferenceEvidence()
        knowledge = KnowledgeReferenceTargetOwner(legacy_evidence=evidence)
        model = ModelReferenceTargetOwner(legacy_evidence=evidence)
        verifier = ReferenceTargetVerifier(
            {TargetType.MODEL: model, TargetType.KNOWLEDGE_SPACE: knowledge, TargetType.KNOWLEDGE_FILE: knowledge}
        )
        _runtime = ReferenceBindingRuntime(ReferenceRepository(verifier=verifier), verifier)
    configure_reference_binding_runtime(_runtime)
    register_source_reads()
