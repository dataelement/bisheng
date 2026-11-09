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
    SourceBindingChange,
    SourceKey,
    SourceType,
    TargetKey,
    TargetType,
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

    async def arefresh_file_target_ownership(self, session, *, receipts, expected_space_id):
        """Refresh derived File space ownership, never source configuration."""
        if self.repository.verifier is not self.verifier:
            raise ResourceReferenceInvalidError(reason="reference_target_verifier_mismatch")
        transaction = TransactionIdentity.capture(session)
        tenant = self.repository.current_tenant_id()
        targets = self.verifier.validate_owner_receipts(session, receipts)
        if (
            type(expected_space_id) is not int
            or expected_space_id <= 0
            or not targets
            or any(
                target.key.target_type != TargetType.KNOWLEDGE_FILE
                or target.state != ReferenceState.VALID
                or target.target_tenant_id != tenant
                or target.target_space_id is None
                for target in targets
            )
            or len({target.target_space_id for target in targets}) != 1
            or targets[0].target_space_id == str(expected_space_id)
        ):
            raise ResourceReferenceInvalidError(reason="reference_file_owner_invalid")
        scope = self.repository.target_owner_scope(session, receipts)
        count = await self.repository.aupdate_file_target_ownership(
            session, scope=scope, expected_space_id=expected_space_id
        )
        transaction.assert_current(session)
        if self.repository.current_tenant_id() != tenant:
            raise ResourceReferenceInvalidError(reason="reference_file_owner_context_changed")
        self.verifier.validate_owner_receipts(session, receipts)
        return count

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
        root = self.repository.get_root_guard(session, key, for_update=lock)
        if root is None and self.repository.has_source_sets_for_root(session, key, for_update=lock):
            raise ReferenceCoverageNotReadyError(reason="source_root_guard_missing")
        return self._snapshot(
            root,
            self.repository.get_source_set(session, key, for_update=lock),
            self.repository.list_source_references(session, key, for_update=lock),
        )

    async def _aread(self, session, key, *, lock=False):
        root = await self.repository.aget_root_guard(session, key, for_update=lock)
        if root is None and await self.repository.ahas_source_sets_for_root(session, key, for_update=lock):
            raise ReferenceCoverageNotReadyError(reason="source_root_guard_missing")
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

    async def aprepare_mixed_source_bindings(
        self, session: AsyncSession, changes: tuple[SourceBindingChange, ...]
    ) -> tuple[PreparedSourceBindings, ...]:
        """Prepare independent roots after one complete physical model lock plan."""
        if (
            not isinstance(changes, tuple)
            or not changes
            or any(not isinstance(c, SourceBindingChange) for c in changes)
        ):
            raise ResourceReferenceInvalidError(reason="reference_mixed_sources_required")
        tenant_id = self.repository.current_tenant_id()
        if len({c.source_key for c in changes}) != len(changes) or any(
            c.source_key.tenant_id != tenant_id
            or c.source_key.source_type not in (SourceType.MODEL_DEFAULT, SourceType.KNOWLEDGE)
            or c.source_key.source_version != "current"
            or (c.source_key.source_type == SourceType.MODEL_DEFAULT and not c.effective)
            or any(ref.target.target_type != TargetType.MODEL for ref in c.references)
            for c in changes
        ):
            raise ResourceReferenceInvalidError(reason="reference_mixed_source_scope_invalid")
        ordered = sorted(
            changes, key=lambda c: (c.source_key.source_type.value, c.source_key.source_id, c.source_key.source_version)
        )
        candidates = []
        for change in ordered:
            candidate = await self._aread(session, change.source_key)
            normalized, targets = self._inputs(
                candidate, change.references, change.new_source, change.effective, change.lock_source_root
            )
            candidates.append((change, candidate, normalized, targets))
        receipts = await self.verifier.averify_mixed_source_targets(
            session, tuple((change.source_key, targets) for change, _, _, targets in candidates)
        )
        for values in receipts.values():
            self._check_deleting(values)
        prepared = []
        for change, candidate, references, targets in candidates:
            result = change.lock_source_root(session)
            if not inspect.isawaitable(result):
                raise TypeError("async preparation requires an asynchronous root lock")
            await result
            locked = await self._aread(session, change.source_key, lock=True)
            prepared.append(
                self._prepared(
                    session,
                    change.source_key,
                    candidate,
                    locked,
                    references,
                    receipts[change.source_key],
                    targets,
                    change.extractor_version,
                    change.effective,
                )
            )
        return tuple(prepared)

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
        if any(
            receipt.target.state != ReferenceState.VALID or not receipt.target.new_binding_allowed
            for receipt in receipts
        ):
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
