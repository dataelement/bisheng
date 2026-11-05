"""Target-first reference preparation inside the business Owner's transaction.

Candidates are immutable values: a later current read must not mutate the
snapshot through SQLAlchemy's identity map. No method starts or commits a
transaction. Source Owners supply their real repository-backed root lock.
"""

import inspect
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    KnowledgeProcessingConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.resource_reference.application.bindings import ReferenceBindings
from bisheng.resource_reference.application.contracts import (
    BindingWriteContext,
    ReferenceSpec,
    ReferenceState,
    SourceKey,
    TargetKey,
    TransactionIdentity,
    VerifiedReferenceSet,
    normalize_references,
    reference_set_digest,
)
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository


@dataclass(frozen=True, slots=True)
class PreparedSourceBindings:
    source_key: SourceKey
    expected_revision: int | None
    new_revision: int
    verified: VerifiedReferenceSet
    effective: bool


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    root_revision: int
    source_revision: int | None
    references: tuple[ReferenceSpec, ...]
    effective: bool

    @property
    def digest(self) -> str:
        return reference_set_digest(self.references)


class ReferenceBindingRuntime:
    def __init__(self, repository: ReferenceRepository, verifier: ReferenceTargetVerifier):
        self.repository = repository
        self.verifier = verifier
        self.bindings = ReferenceBindings(repository, verifier)

    @staticmethod
    def _snapshot(root, current, rows) -> _SourceSnapshot:
        old = normalize_references(
            tuple(ReferenceSpec(row.slot_key, TargetKey(row.target_type, row.target_id)) for row in rows)
        )
        if current is None:
            if rows:
                raise ReferenceCoverageNotReadyError(reason="source_set_missing")
        elif (
            not current.ready
            or current.record_kind != "source"
            or current.digest != reference_set_digest(old)
            or any(row.source_revision != current.source_revision for row in rows)
        ):
            raise ReferenceCoverageNotReadyError(reason="source_set_inconsistent")
        return _SourceSnapshot(
            root.source_revision if root is not None else 0,
            current.source_revision if current is not None else None,
            old,
            bool(current.effective) if current is not None else False,
        )

    def _read(self, session, key, *, lock=False):
        return self._snapshot(
            self.repository.get_root_guard(session, key, for_update=lock),
            self.repository.get_source_set(session, key, for_update=lock),
            self.repository.list_source_references(session, key, for_update=lock),
        )

    async def _aread(self, session, key, *, lock=False):
        root = await self.repository.aget_root_guard(session, key, for_update=lock)
        current = await self.repository.aget_source_set(session, key, for_update=lock)
        rows = await self.repository.alist_source_references(session, key, for_update=lock)
        return self._snapshot(root, current, rows)

    @staticmethod
    def _inputs(candidate, references, new_source, effective, lock_source_root):
        if type(new_source) is not bool or type(effective) is not bool or not callable(lock_source_root):
            raise ValueError("trusted source lifecycle and root-lock callback are required")
        if candidate.source_revision is None and not new_source:
            raise ReferenceCoverageNotReadyError(reason="source_not_indexed")
        if candidate.source_revision is not None and new_source:
            raise ResourceReferenceInvalidError(reason="new_source_already_indexed")
        normalized = normalize_references(tuple(references))
        if not effective and normalized:
            raise ResourceReferenceInvalidError(reason="ineffective_source_has_references")
        targets = tuple(sorted({r.target for r in candidate.references + normalized}, key=lambda t: t.lock_order_key))
        return normalized, targets

    @staticmethod
    def _check_deleting(receipts):
        if any(receipt.target.state == ReferenceState.DELETING for receipt in receipts):
            raise KnowledgeProcessingConflictError(reason="reference_target_deleting")

    @staticmethod
    def _prepared(session, key, candidate, locked, references, receipts, targets, extractor_version, effective):
        if candidate != locked:
            raise KnowledgeOperationPlanConflictError(reason="reference_lock_plan_changed")
        context = BindingWriteContext(
            key,
            candidate.root_revision,
            locked.root_revision,
            targets,
            candidate.digest,
            receipts,
            TransactionIdentity.capture(session),
        )
        verified = VerifiedReferenceSet(references, extractor_version, context)
        revision = candidate.source_revision + 1 if candidate.source_revision is not None else 1
        return PreparedSourceBindings(key, candidate.source_revision, revision, verified, effective)

    def prepare_source_bindings(
        self,
        session: Session,
        source_key: SourceKey,
        references: Iterable[ReferenceSpec],
        *,
        extractor_version: str,
        lock_source_root: Callable[[Session], Any],
        new_source: bool = False,
        effective: bool = True,
    ) -> PreparedSourceBindings:
        candidate = self._read(session, source_key)
        normalized, targets = self._inputs(candidate, references, new_source, effective, lock_source_root)
        receipts = self.verifier.verify_targets(session, source_key, targets)
        self._check_deleting(receipts)
        result = lock_source_root(session)
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise TypeError("synchronous preparation requires a synchronous root lock")
        locked = self._read(session, source_key, lock=True)
        return self._prepared(
            session, source_key, candidate, locked, normalized, receipts, targets, extractor_version, effective
        )

    async def aprepare_source_bindings(
        self,
        session: AsyncSession,
        source_key: SourceKey,
        references: Iterable[ReferenceSpec],
        *,
        extractor_version: str,
        lock_source_root: Callable[[AsyncSession], Any],
        new_source: bool = False,
        effective: bool = True,
    ) -> PreparedSourceBindings:
        candidate = await self._aread(session, source_key)
        normalized, targets = self._inputs(candidate, references, new_source, effective, lock_source_root)
        receipts = await self.verifier.averify_targets(session, source_key, targets)
        self._check_deleting(receipts)
        result = lock_source_root(session)
        if not inspect.isawaitable(result):
            raise TypeError("async preparation requires an asynchronous root lock")
        await result
        locked = await self._aread(session, source_key, lock=True)
        return self._prepared(
            session, source_key, candidate, locked, normalized, receipts, targets, extractor_version, effective
        )

    def apply_source_bindings(self, session: Session, prepared: PreparedSourceBindings):
        return self.bindings.replace_source_bindings(
            session,
            prepared.source_key,
            prepared.expected_revision,
            prepared.new_revision,
            prepared.verified,
            prepared.effective,
        )

    async def aapply_source_bindings(self, session: AsyncSession, prepared: PreparedSourceBindings):
        return await self.bindings.areplace_source_bindings(
            session,
            prepared.source_key,
            prepared.expected_revision,
            prepared.new_revision,
            prepared.verified,
            prepared.effective,
        )

    @staticmethod
    def _execution(candidate, references):
        if candidate.source_revision is None:
            raise ReferenceCoverageNotReadyError(reason="source_not_indexed")
        if not candidate.effective:
            raise ResourceReferenceInvalidError(reason="reference_source_inactive")
        if references is not None and reference_set_digest(tuple(references)) != candidate.digest:
            raise ReferenceCoverageNotReadyError(reason="source_configuration_drift")
        return tuple(sorted({r.target for r in candidate.references}, key=lambda t: t.lock_order_key))

    @staticmethod
    def _require_valid(receipts):
        if any(receipt.target.state != ReferenceState.VALID for receipt in receipts):
            raise ResourceReferenceInvalidError(reason="reference_target_invalid")

    def require_source_valid(self, session: Session, source_key: SourceKey, *, references=None) -> None:
        candidate = self._read(session, source_key)
        targets = self._execution(candidate, references)
        receipts = self.verifier.verify_targets(session, source_key, targets)
        self._require_valid(receipts)

    async def arequire_source_valid(self, session: AsyncSession, source_key: SourceKey, *, references=None) -> None:
        candidate = await self._aread(session, source_key)
        targets = self._execution(candidate, references)
        receipts = await self.verifier.averify_targets(session, source_key, targets)
        self._require_valid(receipts)
