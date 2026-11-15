"""Atomic reference writes for multiple versions of one business root.

One complete physical target prelock precedes source-specific verification.
The business callback then locks the real root and its current version
manifest. The caller commits all business and reference changes together.
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.resource_reference.application.contracts import (
    BindingWriteContext,
    ReferenceSpec,
    SourceKey,
    TransactionIdentity,
    VerifiedReferenceSet,
    normalize_references,
)
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import PreparedSourceBindings, ReferenceBindingRuntime
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository


@dataclass(frozen=True, slots=True)
class SourceBindingRequest:
    source_key: SourceKey
    references: tuple[ReferenceSpec, ...]
    extractor_version: str
    new_source: bool = False
    effective: bool = True

    def __post_init__(self):
        if not isinstance(self.source_key, SourceKey) or not isinstance(self.references, tuple):
            raise ValueError("batch requests require a source key and immutable references")
        if type(self.new_source) is not bool or type(self.effective) is not bool:
            raise ValueError("batch lifecycle flags must be boolean")
        object.__setattr__(self, "references", normalize_references(self.references))


@dataclass(frozen=True, slots=True)
class PreparedSourceBatch:
    sources: tuple[PreparedSourceBindings, ...]
    source_keys: tuple[SourceKey, ...]
    base_root_revision: int


class BatchReferenceBindings:
    def __init__(self, repository: ReferenceRepository, verifier: ReferenceTargetVerifier):
        self.repository = repository
        self.verifier = verifier
        self.runtime = ReferenceBindingRuntime(repository, verifier)

    def _requests(self, requests, lock_source_root):
        if not isinstance(requests, tuple) or not requests or not callable(lock_source_root):
            raise ValueError("a nonempty batch and real business root-lock callback are required")
        if any(not isinstance(request, SourceBindingRequest) for request in requests):
            raise ValueError("batch requests must be SourceBindingRequest values")
        keys = tuple(request.source_key for request in requests)
        if len(set(keys)) != len(keys) or len({(key.tenant_id, key.source_type, key.source_id) for key in keys}) != 1:
            raise ResourceReferenceInvalidError(reason="reference_batch_root_mismatch")
        for key in keys:
            self.repository.assert_source_tenant(key)
        return tuple(sorted(requests, key=lambda request: request.source_key.source_version))

    def _inputs(self, requests, candidates, lock_source_root):
        if len({candidate.root_revision for candidate in candidates}) != 1:
            raise KnowledgeOperationPlanConflictError(reason="reference_lock_plan_changed")
        return tuple(
            self.runtime._inputs(candidate, request.references, request.new_source, request.effective, lock_source_root)
            for request, candidate in zip(requests, candidates, strict=True)
        )

    @staticmethod
    def _manifest(actual, expected):
        if not isinstance(actual, tuple) or any(not isinstance(key, SourceKey) for key in actual):
            raise ResourceReferenceInvalidError(reason="reference_batch_manifest_required")
        if len(actual) != len(set(actual)) or tuple(sorted(actual, key=lambda key: key.source_version)) != expected:
            raise KnowledgeOperationPlanConflictError(reason="reference_batch_manifest_changed")

    @staticmethod
    def _prepared(session, requests, candidates, locked, inputs, receipts):
        if candidates != locked:
            raise KnowledgeOperationPlanConflictError(reason="reference_lock_plan_changed")
        base = candidates[0].root_revision
        result = []
        for index, (request, candidate, (references, targets)) in enumerate(
            zip(requests, candidates, inputs, strict=True)
        ):
            context = BindingWriteContext(
                request.source_key,
                base + index,
                base + index,
                targets,
                candidate.digest,
                receipts[request.source_key],
                TransactionIdentity.capture(session),
            )
            result.append(
                PreparedSourceBindings(
                    request.source_key,
                    candidate.source_revision,
                    candidate.source_revision + 1 if candidate.source_revision is not None else 1,
                    VerifiedReferenceSet(references, request.extractor_version, context),
                    request.effective,
                )
            )
        return PreparedSourceBatch(tuple(result), tuple(request.source_key for request in requests), base)

    def prepare_source_batch(
        self,
        session: Session,
        requests: tuple[SourceBindingRequest, ...],
        *,
        lock_source_root: Callable[[Session, tuple[SourceKey, ...]], tuple[SourceKey, ...]],
    ) -> PreparedSourceBatch:
        requests = self._requests(requests, lock_source_root)
        candidates = tuple(self.runtime._read(session, request.source_key) for request in requests)
        identity = TransactionIdentity.capture(session)
        inputs = self._inputs(requests, candidates, lock_source_root)
        receipts = self.verifier.verify_batch_targets(
            session, tuple((request.source_key, data[1]) for request, data in zip(requests, inputs, strict=True))
        )
        for values in receipts.values():
            self.runtime._check_deleting(values)
        keys = tuple(request.source_key for request in requests)
        actual = lock_source_root(session, keys)
        if inspect.isawaitable(actual):
            if inspect.iscoroutine(actual):
                actual.close()
            raise TypeError("synchronous batch preparation requires a synchronous root lock")
        identity.assert_current(session)
        self._manifest(actual, keys)
        locked = tuple(self.runtime._read(session, key, lock=True) for key in keys)
        return self._prepared(session, requests, candidates, locked, inputs, receipts)

    async def aprepare_source_batch(
        self,
        session: AsyncSession,
        requests: tuple[SourceBindingRequest, ...],
        *,
        lock_source_root: Callable,
    ) -> PreparedSourceBatch:
        requests = self._requests(requests, lock_source_root)
        candidates = []
        for request in requests:
            candidates.append(await self.runtime._aread(session, request.source_key))
        candidates = tuple(candidates)
        identity = TransactionIdentity.capture(session)
        inputs = self._inputs(requests, candidates, lock_source_root)
        receipts = await self.verifier.averify_batch_targets(
            session, tuple((request.source_key, data[1]) for request, data in zip(requests, inputs, strict=True))
        )
        for values in receipts.values():
            self.runtime._check_deleting(values)
        keys = tuple(request.source_key for request in requests)
        actual = lock_source_root(session, keys)
        if not inspect.isawaitable(actual):
            raise TypeError("async batch preparation requires an asynchronous root lock")
        actual = await actual
        identity.assert_current(session)
        self._manifest(actual, keys)
        locked = []
        for key in keys:
            locked.append(await self.runtime._aread(session, key, lock=True))
        return self._prepared(session, requests, candidates, tuple(locked), inputs, receipts)

    @staticmethod
    def _check_prepared(prepared):
        if not isinstance(prepared, PreparedSourceBatch) or not prepared.sources:
            raise ResourceReferenceInvalidError(reason="reference_batch_required")
        keys = tuple(item.source_key for item in prepared.sources)
        if keys != prepared.source_keys or keys != tuple(sorted(set(keys), key=lambda key: key.source_version)):
            raise ResourceReferenceInvalidError(reason="reference_batch_order_changed")
        if len({(key.tenant_id, key.source_type, key.source_id) for key in keys}) != 1 or any(
            item.verified.context.expected_root_revision != prepared.base_root_revision + index
            or item.verified.context.locked_root_revision != prepared.base_root_revision + index
            for index, item in enumerate(prepared.sources)
        ):
            raise ResourceReferenceInvalidError(reason="reference_batch_root_mismatch")

    def apply_source_batch(self, session: Session, prepared: PreparedSourceBatch):
        self._check_prepared(prepared)
        return tuple(self.runtime.apply_source_bindings(session, item) for item in prepared.sources)

    async def aapply_source_batch(self, session: AsyncSession, prepared: PreparedSourceBatch):
        self._check_prepared(prepared)
        result = []
        for item in prepared.sources:
            result.append(await self.runtime.aapply_source_bindings(session, item))
        return tuple(result)
