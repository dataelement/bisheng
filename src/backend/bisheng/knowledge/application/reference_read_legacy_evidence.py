"""Injectable read-only legacy evidence; never guess missing target ownership."""

from bisheng.knowledge.domain.repositories.reference_read_legacy_evidence_repository import (
    KnowledgeReadLegacyEvidenceRepository,
)
from bisheng.resource_reference.application.contracts import LegacyEvidence


class KnowledgeReferenceReadLegacyEvidence:
    def __init__(self, verifier, repository=None):
        self.repository = repository if repository is not None else KnowledgeReadLegacyEvidenceRepository(verifier)
        if self.repository.verifier is not verifier:
            raise ValueError("legacy and source reads must use the same authority")

    async def aresolve(self, session, scope, target, *, run_id, evidence_key, identity):
        return LegacyEvidence(
            *await self.repository.aload(
                session, scope, target, run_id=run_id, evidence_key=evidence_key, identity=identity
            )
        )

    def resolve(self, session, scope, target, *, run_id, evidence_key, identity):
        return LegacyEvidence(
            *self.repository.load(session, scope, target, run_id=run_id, evidence_key=evidence_key, identity=identity)
        )
