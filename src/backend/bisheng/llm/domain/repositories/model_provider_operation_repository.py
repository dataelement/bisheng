"""Provider locks and the existing plan ledger's private execution state.

This repository grants no administrator or sharing authority. The owning
application authenticates its original caller before requesting these facts.
All mutations remain in the caller's native transaction.
"""

from copy import deepcopy
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanChangedError,
    KnowledgeOperationPlanConflictError,
    KnowledgeProcessingConflictError,
)
from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError, LLMModelSharedReadonlyError
from bisheng.core.context.tenant import bypass_tenant_filter, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.domain.models.llm_server import LLMServer
from bisheng.llm.domain.repositories.model_delete_plan_repository import ModelDeletePlanRepository, _hash
from bisheng.resource_reference.application.contracts import TransactionIdentity
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository

ACTIVE_STATES = ("PREPARING", "RESERVED", "SHARING_COMPLETE", "FAILED_CLOSED")
SHARE_OPERATION = "model_share_server"


class ModelProviderOperationRepository:
    def __init__(self, plans: ModelDeletePlanRepository | None = None):
        self.plans = plans if plans is not None else ModelDeletePlanRepository()

    @staticmethod
    def _native(session):
        if (
            not isinstance(session, AsyncSession)
            or not session.in_transaction()
            or session.new
            or session.dirty
            or session.deleted
        ):
            raise KnowledgeOperationPlanConflictError(reason="model_provider_native_context_required")
        return ReferenceRepository.current_tenant_id(), TransactionIdentity.capture(session)

    async def alock_provider(self, session, *, server_id: int):
        tenant, transaction = self._native(session)
        if type(server_id) is not int or server_id <= 0:
            raise LLMModelNotAccessibleError()
        with session.no_autoflush, bypass_tenant_filter():
            owner = (
                await session.execute(select(LLMServer.tenant_id).where(LLMServer.id == server_id))
            ).scalar_one_or_none()
        transaction.assert_current(session)
        if ReferenceRepository.current_tenant_id() != tenant:
            raise KnowledgeOperationPlanChangedError()
        if owner == 1 and tenant != 1:
            raise LLMModelSharedReadonlyError()
        if owner != tenant:
            raise LLMModelNotAccessibleError()
        with session.no_autoflush, strict_tenant_filter():
            row = (
                await session.execute(
                    select(LLMServer)
                    .where(LLMServer.id == server_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
        transaction.assert_current(session)
        if row is None or row.tenant_id != tenant or ReferenceRepository.current_tenant_id() != tenant:
            raise LLMModelNotAccessibleError()
        return row

    async def arequire_idle(self, session, *, server_id: int, allowed_operation_id: str | None = None):
        tenant, transaction = self._native(session)
        with session.no_autoflush, strict_tenant_filter():
            rows = (
                await session.execute(
                    select(KnowledgeOperationPlan.id, KnowledgeOperationPlan.operation_id)
                    .where(
                        KnowledgeOperationPlan.model_server_id == server_id,
                        KnowledgeOperationPlan.model_execution_state.in_(ACTIVE_STATES),
                    )
                    .order_by(KnowledgeOperationPlan.id)
                    .limit(2)
                )
            ).all()
        transaction.assert_current(session)
        if ReferenceRepository.current_tenant_id() != tenant:
            raise KnowledgeOperationPlanChangedError()
        if rows and (len(rows) != 1 or rows[0].operation_id != allowed_operation_id):
            raise KnowledgeProcessingConflictError(reason="model_provider_operation_active")

    async def aread_plan(self, session, *, confirmation_id: str, lock=False, required=True):
        tenant, transaction = self._native(session)
        statement = select(KnowledgeOperationPlan).where(KnowledgeOperationPlan.id == confirmation_id)
        if lock:
            statement = statement.with_for_update()
        with session.no_autoflush, strict_tenant_filter():
            row = (await session.execute(statement.execution_options(populate_existing=True))).scalar_one_or_none()
        transaction.assert_current(session)
        if row is None and required is False and ReferenceRepository.current_tenant_id() == tenant:
            return None
        if row is None or row.tenant_id != tenant or ReferenceRepository.current_tenant_id() != tenant:
            raise KnowledgeOperationPlanChangedError()
        return row

    async def ascalar_pin(self, session, *, confirmation_id):
        tenant, transaction = self._native(session)
        with session.no_autoflush, strict_tenant_filter():
            row = (
                await session.execute(
                    select(
                        KnowledgeOperationPlan.id,
                        KnowledgeOperationPlan.tenant_id,
                        KnowledgeOperationPlan.operation,
                        KnowledgeOperationPlan.operation_id,
                        KnowledgeOperationPlan.actor_user_id,
                        KnowledgeOperationPlan.model_server_id,
                        KnowledgeOperationPlan.model_execution_state,
                        KnowledgeOperationPlan.request_hash,
                        KnowledgeOperationPlan.plan_digest,
                    ).where(KnowledgeOperationPlan.id == confirmation_id)
                )
            ).one_or_none()
        transaction.assert_current(session)
        if row is None or row.tenant_id != tenant or ReferenceRepository.current_tenant_id() != tenant:
            raise KnowledgeOperationPlanChangedError()
        return row

    async def aactive_plan(self, session, *, server_id):
        tenant, transaction = self._native(session)
        with session.no_autoflush, strict_tenant_filter():
            rows = (
                (
                    await session.execute(
                        select(KnowledgeOperationPlan)
                        .where(
                            KnowledgeOperationPlan.model_server_id == server_id,
                            KnowledgeOperationPlan.model_execution_state.in_(ACTIVE_STATES),
                        )
                        .order_by(KnowledgeOperationPlan.id)
                        .limit(2)
                        .execution_options(populate_existing=True)
                    )
                )
                .scalars()
                .all()
            )
        transaction.assert_current(session)
        if ReferenceRepository.current_tenant_id() != tenant or len(rows) > 1:
            raise KnowledgeOperationPlanChangedError()
        return rows[0] if rows else None

    async def afind_completed(self, session, *, server_id, operation, actor_user_id, command_digest):
        tenant, transaction = self._native(session)
        with session.no_autoflush, strict_tenant_filter():
            rows = (
                (
                    await session.execute(
                        select(KnowledgeOperationPlan)
                        .where(
                            KnowledgeOperationPlan.model_server_id == server_id,
                            KnowledgeOperationPlan.model_execution_state == "COMPLETED",
                            KnowledgeOperationPlan.operation == operation,
                            KnowledgeOperationPlan.actor_user_id == actor_user_id,
                        )
                        .order_by(KnowledgeOperationPlan.update_time.desc(), KnowledgeOperationPlan.id.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .all()
            )
        transaction.assert_current(session)
        if ReferenceRepository.current_tenant_id() != tenant:
            raise KnowledgeOperationPlanChangedError()
        return next((row for row in rows if row.parameters.get("command_digest") == command_digest), None)

    def validate(self, row):
        if row.operation == SHARE_OPERATION:
            if (
                row.space_id is not None
                or row.target_manifest != []
                or row.source_revisions != {}
                or row.impact != {}
                or set(row.parameters) != {"command_digest"}
                or row.request_hash != _hash(self.plans._payload(row))
                or row.plan_digest != self.plans._plan_digest(row)
                or not row.operation_id
                or row.consumed_at is None
            ):
                raise KnowledgeOperationPlanChangedError()
            self.plans._actor(row.actor_reference, row.tenant_id)
            self.plans._revisions(row.target_revisions, [])
        else:
            self.plans._validate(row, expiry=False)
        if row.operation_id is None and any(
            value is not None
            for value in (row.model_server_id, row.model_execution_state, row.model_execution_metadata)
        ):
            raise KnowledgeOperationPlanChangedError()
        if row.operation_id is not None and (
            type(row.model_server_id) is not int
            or row.model_server_id <= 0
            or row.model_execution_state not in {*ACTIVE_STATES, "COMPLETED"}
            or not isinstance(row.model_execution_metadata, dict)
        ):
            raise KnowledgeOperationPlanChangedError()

    @staticmethod
    def require_current_actor(row, actor_reference):
        # An unconsumed confirmation retains the exact original credential.
        old = row.actor_reference
        if row.operation_id is None:
            matches = old == actor_reference
        else:
            keys = ("tenant_id", "actor_user_id", "management_tenant_id", "data_scope")
            matches = all(old.get(key) == actor_reference.get(key) for key in keys)
            matches = matches and (
                old["credential_reference"]["kind"],
                old["credential_reference"]["user_id"],
                old["credential_reference"]["tenant_id"],
            ) == (
                actor_reference["credential_reference"]["kind"],
                actor_reference["credential_reference"]["user_id"],
                actor_reference["credential_reference"]["tenant_id"],
            )
        if not matches:
            raise KnowledgeOperationPlanChangedError()

    async def acreate_share_reservation(
        self, session, *, server_id, actor_reference, server_revision, command_digest, metadata
    ):
        tenant, transaction = self._native(session)
        actor = self.plans._actor(actor_reference, tenant)
        await self.arequire_idle(session, server_id=server_id)
        now = self.plans.clock()
        row = KnowledgeOperationPlan(
            tenant_id=tenant,
            actor_user_id=actor["actor_user_id"],
            actor_reference=actor,
            operation=SHARE_OPERATION,
            target_manifest=[],
            target_revisions={f"server:{server_id}": server_revision},
            source_revisions={},
            parameters={"command_digest": command_digest},
            impact={},
            expires_at=now,
            operation_id=str(uuid4()),
            consumed_at=now,
            create_time=now,
            update_time=now,
            model_server_id=server_id,
            model_execution_state="PREPARING",
            model_execution_metadata=deepcopy(metadata),
            request_hash="",
            plan_digest="",
        )
        row.request_hash = _hash(self.plans._payload(row))
        row.plan_digest = self.plans._plan_digest(row)
        session.add(row)
        await session.flush()
        transaction.assert_current(session)
        self.validate(row)
        return row

    async def abind(self, session, row, *, server_id, metadata):
        tenant, transaction = self._native(session)
        self.plans._validate(row, expiry=False) if row.operation != SHARE_OPERATION else self.validate(row)
        if row.operation_id is None or row.tenant_id != tenant or type(server_id) is not int or server_id <= 0:
            raise KnowledgeOperationPlanChangedError()
        row.model_server_id = server_id
        row.model_execution_state = "RESERVED"
        row.model_execution_metadata = deepcopy(metadata)
        row.update_time = self.plans.clock()
        session.add(row)
        await session.flush()
        transaction.assert_current(session)
        self.validate(row)

    async def aset_state(self, session, *, row, expected, target, metadata=None):
        tenant, transaction = self._native(session)
        if target not in {*ACTIVE_STATES, "COMPLETED"}:
            raise KnowledgeOperationPlanChangedError()
        values = {"model_execution_state": target, "update_time": self.plans.clock()}
        if metadata is not None:
            values["model_execution_metadata"] = deepcopy(metadata)
        result = await session.execute(
            update(KnowledgeOperationPlan)
            .where(
                KnowledgeOperationPlan.id == row.id,
                KnowledgeOperationPlan.tenant_id == tenant,
                KnowledgeOperationPlan.model_server_id == row.model_server_id,
                KnowledgeOperationPlan.operation_id == row.operation_id,
                KnowledgeOperationPlan.model_execution_state == expected,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        transaction.assert_current(session)
        if result.rowcount != 1 or ReferenceRepository.current_tenant_id() != tenant:
            raise KnowledgeOperationPlanChangedError()
