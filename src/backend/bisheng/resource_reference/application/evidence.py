"""Frozen migration proof consumed by target Owners, supplied by composition.

The exact source/target/run/key come from its previously indexed original
binding. They are never an HTTP proof or a guess from the caller's tenant.
"""

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from bisheng.resource_reference.application.contracts import LegacyEvidence, SourceKey, TargetKey


class LegacyReferenceEvidencePort(Protocol):
    def resolve(
        self, session: Session, source_key: SourceKey, target: TargetKey, *, run_id: str, evidence_key: str
    ) -> LegacyEvidence: ...

    async def aresolve(
        self, session: AsyncSession, source_key: SourceKey, target: TargetKey, *, run_id: str, evidence_key: str
    ) -> LegacyEvidence: ...
