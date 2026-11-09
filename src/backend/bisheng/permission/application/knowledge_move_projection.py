"""Resume only an accepted move's exact original F048 parent operations.

The knowledge Owner supplies verified business facts and current actor admission.
This bridge grants no knowledge action and never accesses knowledge persistence.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from weakref import WeakSet

from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.permission import PermissionProjectionFailedError, PermissionPublishNotReadyError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.core.database import get_async_db_session
from bisheng.permission.application.control_state import SqlPermissionControlState
from bisheng.permission.application.identity import PermissionActor
from bisheng.permission.application.runtime import F048PermissionRuntime, F048RuntimeComponents
from bisheng.permission.domain.repositories.move_projection_repository import (
    MoveOperatorCandidate,
    MoveParentState,
    MoveProjectionEvidence,
    MoveProjectionExpectation,
    MoveProjectionFact,
    MoveProjectionRepository,
    operation_key,
)
from bisheng.permission.domain.services.projection_service import ProjectionService

__all__ = [
    "KnowledgeMoveProjectionApplication",
    "MoveOperatorCandidate",
    "MoveParentState",
    "MoveProjectionEvidence",
    "MoveProjectionExpectation",
    "MoveProjectionFact",
    "MoveProjectionProgress",
]


def _blocked(reason):
    raise PermissionPublishNotReadyError(msg="Knowledge move projection: " + reason)


@dataclass(frozen=True, slots=True)
class MoveProjectionProgress:
    total_count: int
    finalized_count: int
    complete: bool


class KnowledgeMoveProjectionApplication:
    def __init__(self, *, repository=None, components=None, session_factory=None):
        if repository is not None and not isinstance(repository, MoveProjectionRepository):
            _blocked("actual native repository required")
        if session_factory is not None and not callable(session_factory):
            _blocked("native session factory required")
        self.repository = repository if repository is not None else MoveProjectionRepository()
        self.components, self.sessions = components, session_factory or get_async_db_session
        self._seen = WeakSet()

    @asynccontextmanager
    async def _session(self):
        async with self.sessions() as session:
            if not isinstance(session, AsyncSession) or session.in_transaction() or session in self._seen:
                _blocked("fresh owned native session required")
            self._seen.add(session)
            async with session.begin():
                yield session

    async def _composition(self):
        components = self.components
        if components is None:
            from bisheng.permission.application.process_runtime import get_f048_process_runtime

            try:
                runtime = await get_f048_process_runtime()
            except Exception as error:
                raise PermissionPublishNotReadyError(msg="Move permission runtime is not composed") from error
            components = getattr(runtime, "components", runtime)
        if (
            not isinstance(components, F048RuntimeComponents)
            or not isinstance(components.facade, F048PermissionRuntime)
            or not isinstance(components.projection, ProjectionService)
            or not isinstance(components.state, SqlPermissionControlState)
            or components.facade._state is not components.state
            or components.facade._projection is not components.projection
            or components.facade._marker is not components.marker
            or not callable(getattr(components.marker, "is_ready", None))
        ):
            _blocked("actual runtime, projection and marker composition required")
        if not await components.marker.is_ready():
            _blocked("permission recent-change marker is not ready")
        return components

    @staticmethod
    def _scope(tenant):
        if type(tenant) is not int or tenant <= 0 or get_current_tenant_id() != tenant or is_tenant_filter_bypassed():
            _blocked("original concrete tenant scope changed")

    async def aread_parent_states(self, session, *, targets) -> tuple[MoveParentState, ...]:
        return await self.repository.aread_parent_states(session, targets=targets)

    async def alist_operator_candidates(self, session, *, job_id, targets) -> tuple[MoveOperatorCandidate, ...]:
        return await self.repository.alist_operator_candidates(session, job_id=job_id, targets=targets)

    async def alist_owned_operations(self, session, *, expectations, lock=False) -> tuple[MoveProjectionFact, ...]:
        return await self.repository.alist_owned_operations(session, expectations=expectations, lock=lock)

    async def arequire_finalized(self, session, *, job_id, expectations) -> MoveProjectionEvidence:
        # The full Owner sequence is mandatory. Native issuance verifies every
        # page; K1 still compares all eight fields with its private prepared set.
        if not expectations:
            _blocked("full parent-change expectations required")
        return await self.repository.arequire_finalized(
            session, job_id=job_id, expectations=expectations, changes_digest=expectations[0].changes_digest
        )

    def assert_current(self, evidence, session, *, job_id, expected_changes, changes_digest) -> None:
        self.repository.assert_current(
            evidence, session, job_id=job_id, expected_changes=expected_changes, changes_digest=changes_digest
        )

    async def _recover(self, components, fact, tenant):
        preview = await components.projection.inspect_failed_closed_recovery(fact.id)
        if (
            any(
                getattr(preview, name) != getattr(fact, name)
                for name in (
                    "tenant_id",
                    "operation_type",
                    "scope_type",
                    "scope_key",
                    "expected_version",
                    "target_version",
                    "store_id",
                    "model_id",
                    "request_checksum",
                    "after_checksum",
                )
            )
            or preview.operation_id != fact.id
        ):
            _blocked("original recovery confirmation changed")
        self._scope(tenant)
        await components.projection.recover_failed_closed_operation(
            fact.id, confirmation_checksum=preview.confirmation_checksum
        )

    @staticmethod
    def _owned_mode(item, fact):
        state = fact.parent_state
        if (
            state is None
            or state.operation_id != fact.id
            or state.mode != item.mode
            or (state.parent_type, state.parent_id) != (item.after.parent_type, item.after.parent_id)
            or not (
                (state.version == fact.expected_version and state.projection_state in {"PROJECTING", "FAILED_CLOSED"})
                or (state.version == fact.target_version and state.projection_state == "CURRENT")
            )
        ):
            _blocked("nonfinalized operation does not own its mode fence")

    async def _reserve_prepared(self, components, item, fact, tenant):
        state = fact.parent_state
        if (
            fact.status == "PREPARED"
            and state is not None
            and state.projection_state == "CURRENT"
            and state.mode == item.mode
            and state.version == fact.expected_version
            and (state.parent_type, state.parent_id) == (item.before.parent_type, item.before.parent_id)
        ):
            catalog = await components.facade._runtime_catalog()
            self._scope(tenant)
            if (catalog.store_id, catalog.model_id) != (fact.store_id, fact.model_id):
                _blocked("original prepared operation pin changed")
            await components.state.mark_projecting(
                target=item.before,
                operation_id=fact.id,
                parent_type=item.after.parent_type,
                parent_id=item.after.parent_id,
                expected_catalog_release_id=catalog.release_id,
            )
            async with self._session() as session:
                fresh = await self.repository.alist_owned_operations(session, expectations=(item,))
            if len(fresh) != 1 or fresh[0].id != fact.id or fresh[0].request_checksum != fact.request_checksum:
                _blocked("original prepared reservation changed")
            fact = fresh[0]
        self._owned_mode(item, fact)
        return fact

    async def aexecute_or_resume(self, *, job_id, changes, actor) -> MoveProjectionProgress:
        tenant = get_current_tenant_id()
        self._scope(tenant)
        if not isinstance(actor, PermissionActor):
            _blocked("original actor required")
        # Validate the entire input before any FGA action, including bad tails.
        async with self._session() as session:
            self.repository._expectations(session, changes, job_id=job_id)
        if any(actor.user_id not in item.allowed_operator_ids for item in changes):
            _blocked("actor is not accepted for this operation")
        if changes and len({item.changes_digest for item in changes}) != 1:
            _blocked("mixed accepted change sets")
        components = await self._composition()
        self._scope(tenant)
        finalized = 0
        for offset in range(0, len(changes), 200):
            batch = changes[offset : offset + 200]
            async with self._session() as session:
                facts = await self.repository.alist_owned_operations(session, expectations=tuple(batch))
            by_key = {fact.idempotency_key: fact for fact in facts}
            for item in batch:
                self._scope(tenant)
                key = operation_key(job_id, item.resource_type, item.resource_id)
                fact = by_key.get(key)
                if fact is not None and fact.status != "FINALIZED":
                    fact = await self._reserve_prepared(components, item, fact, tenant)
                if fact is None:
                    await components.facade.project_parent_change(
                        actor=actor, old_target=item.before, target=item.after, mode=item.mode, idempotency_key=key
                    )
                elif fact.status == "FAILED_CLOSED":
                    await self._recover(components, fact, tenant)
                elif fact.status in {"PREPARED", "STAGING", "COMMIT_UNKNOWN", "COMMITTED"}:
                    # Reconcile the persisted plan. Its operator is intentionally
                    # not replaced with this retry actor, nor is its hash rebuilt.
                    try:
                        await components.projection.reconcile_operation(fact.id)
                    except PermissionProjectionFailedError:
                        # Original reconciliation can durably fence a mixed
                        # state. Only its freshly verified FAILED_CLOSED record
                        # permits the existing checksum-confirmed forward repair.
                        async with self._session() as session:
                            fresh = await self.repository.alist_owned_operations(session, expectations=(item,))
                        if (
                            len(fresh) != 1
                            or fresh[0].id != fact.id
                            or fresh[0].status != "FAILED_CLOSED"
                            or fresh[0].request_checksum != fact.request_checksum
                        ):
                            raise
                        self._owned_mode(item, fresh[0])
                        await self._recover(components, fresh[0], tenant)
                elif fact.status != "FINALIZED":
                    _blocked("unknown durable operation status")
                self._scope(tenant)
            async with self._session() as session:
                current = await self.repository.alist_owned_operations(session, expectations=tuple(batch))
                if len(current) != len(batch):
                    _blocked("runtime did not persist the accepted operation")
                final_keys = {fact.idempotency_key for fact in current if fact.status == "FINALIZED"}
                completed = tuple(
                    item for item in batch if operation_key(job_id, item.resource_type, item.resource_id) in final_keys
                )
                if completed:
                    evidence = await self.repository.arequire_finalized(
                        session, job_id=job_id, expectations=completed, changes_digest=completed[0].changes_digest
                    )
                    finalized += evidence.count
        return MoveProjectionProgress(len(changes), finalized, finalized == len(changes))
