"""Migration-backed proof injected into both knowledge and model target Owners."""

from bisheng.knowledge.domain.repositories.reference_legacy_evidence_repository import KnowledgeLegacyEvidenceRepository
from bisheng.resource_reference.application.contracts import LegacyEvidence


class KnowledgeLegacyReferenceEvidence:
    def __init__(self, repository: KnowledgeLegacyEvidenceRepository | None = None):
        self.repository = repository or KnowledgeLegacyEvidenceRepository()

    def resolve(self, session, source_key, target, *, run_id, evidence_key) -> LegacyEvidence:
        return LegacyEvidence(
            *self.repository.load(session, source_key, target, run_id=run_id, evidence_key=evidence_key)
        )

    async def aresolve(self, session, source_key, target, *, run_id, evidence_key) -> LegacyEvidence:
        return LegacyEvidence(
            *await self.repository.aload(session, source_key, target, run_id=run_id, evidence_key=evidence_key)
        )
