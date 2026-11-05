"""Read immutable migration proof for an already indexed original target."""

import re

from sqlmodel import select

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.knowledge.domain.models.knowledge_unification_run import FROZEN_BASELINE_PHASES, KnowledgeUnificationRun
from bisheng.resource_reference.application.contracts import SourceKey, TargetKey
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference


class KnowledgeLegacyEvidenceRepository:
    @staticmethod
    def _check_tenant(source_key: SourceKey) -> None:
        tenant_id = _resolve_tenant_id()
        if is_tenant_filter_bypassed() or type(tenant_id) is not int or tenant_id != source_key.tenant_id:
            raise ResourceReferenceInvalidError(reason="legacy_evidence_source_tenant_mismatch")

    @staticmethod
    def _original(source_key, target):
        return (
            select(BusinessResourceReference)
            .where(
                BusinessResourceReference.source_type == source_key.source_type.value,
                BusinessResourceReference.source_id == source_key.source_id,
                BusinessResourceReference.source_version == source_key.source_version,
                BusinessResourceReference.target_type == target.target_type.value,
                BusinessResourceReference.target_id == target.target_id,
            )
            .execution_options(populate_existing=True)
        )

    @staticmethod
    def _run(run_id):
        return (
            select(KnowledgeUnificationRun)
            .where(KnowledgeUnificationRun.run_id == run_id)
            .execution_options(populate_existing=True)
        )

    @staticmethod
    def _check_original(rows, source_key, run_id, evidence_key):
        if not rows or any(
            row.tenant_id != source_key.tenant_id
            or row.legacy_invalid_reason != "target_missing"
            or row.legacy_run_id != run_id
            or row.legacy_evidence_key != evidence_key
            for row in rows
        ):
            raise ResourceReferenceInvalidError(reason="legacy_evidence_original_mismatch")

    @staticmethod
    def _descriptor(value, digest):
        if not isinstance(value, dict) or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            return False
        key = value.get("object_key")
        return (
            isinstance(key, str)
            and bool(key.strip())
            and not key.startswith(("/", "file:"))
            and "://" not in key
            and value.get("sha256") == digest
        )

    @classmethod
    def _facts(cls, run, source_key, run_id, evidence_key):
        if (
            run is None
            or run.tenant_id != source_key.tenant_id
            or run.origin != "migration"
            or run.phase not in FROZEN_BASELINE_PHASES
            or not cls._descriptor(run.baseline_ref, run.baseline_hash)
            or not cls._descriptor(run.plan_ref, run.plan_hash)
        ):
            raise ReferenceCoverageNotReadyError(reason="legacy_baseline_not_frozen")
        return run_id, run.baseline_hash, evidence_key

    def load(self, session, source_key: SourceKey, target: TargetKey, *, run_id: str, evidence_key: str):
        self._check_tenant(source_key)
        with strict_tenant_filter():
            rows = tuple(session.execute(self._original(source_key, target)).scalars().all())
            self._check_original(rows, source_key, run_id, evidence_key)
            run = session.execute(self._run(run_id)).scalar_one_or_none()
        return self._facts(run, source_key, run_id, evidence_key)

    async def aload(self, session, source_key: SourceKey, target: TargetKey, *, run_id: str, evidence_key: str):
        self._check_tenant(source_key)
        with strict_tenant_filter():
            result = await session.execute(self._original(source_key, target))
            rows = tuple(result.scalars().all())
            self._check_original(rows, source_key, run_id, evidence_key)
            result = await session.execute(self._run(run_id))
            run = result.scalar_one_or_none()
        return self._facts(run, source_key, run_id, evidence_key)
