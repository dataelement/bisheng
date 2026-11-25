"""Tenant-scoped provider ledger. The caller owns the short transaction.

Commit a claim before sending HTTP. On takeover a sender can reconcile, not
send again. apply() advances ledger facts; it does not grant resource access.
"""

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderInstance as Instance
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderOperation as Op


class RequestKeyConflict(ValueError):
    """A request key does not identify this actor's original intent."""


# Only the result interpreter may request a transition; it must verify the
# remote receipt before choosing applying (and verified absence before pending).
_NEXT = {
    "sending": {"waiting_remote", "reconciling", "applying", "failed", "manual_review"},
    "waiting_remote": {"waiting_remote", "reconciling", "applying", "failed", "manual_review"},
    "reconciling": {"reconciling", "waiting_remote", "applying", "pending", "manual_review", "failed"},
    "applying": {"applying", "succeeded", "failed", "manual_review"},
}
_RUNNABLE = ("pending", *_NEXT)


class ProviderOperationRepository:
    async def accept(self, session: AsyncSession, intent: Op) -> Op:
        key = select(Op).where(
            Op.tenant_id == intent.tenant_id, Op.kind == intent.kind, Op.request_key == intent.request_key
        )
        existing = await session.scalar(key)
        if existing is None:
            try:
                async with session.begin_nested():
                    session.add(intent)
                    await session.flush()
                return intent
            except IntegrityError:
                # A locking read sees the concurrent winner even under MySQL RR.
                # An unrelated constraint violation is not an idempotent replay.
                existing = await session.scalar(key.with_for_update().execution_options(populate_existing=True))
                if existing is None:
                    raise
        if existing.actor_user_id != intent.actor_user_id or existing.request_hash != intent.request_hash:
            raise RequestKeyConflict("request key conflicts with an existing operation")
        return existing

    async def read_owned_upload(self, session, *, tenant_id, actor_id, space_id, request_key):
        """Read local item facts only; never claim a sender or touch its retry clock."""
        return (
            await session.execute(
                select(Op.operation_id, Op.state, Op.last_error_code, Op.target_manifest).where(
                    Op.tenant_id == tenant_id,
                    Op.actor_user_id == actor_id,
                    Op.space_id == space_id,
                    Op.kind == "upload",
                    Op.request_key == request_key,
                )
            )
        ).one_or_none()

    async def list_due(self, session, *, tenant_id, now, limit, kinds):
        statement = (
            select(Op.tenant_id, Op.operation_id, Op.revision)
            .where(
                Op.tenant_id == tenant_id,
                Op.kind.in_(kinds),
                Op.state.in_(_RUNNABLE),
                Op.next_attempt_at <= now,
                or_(Op.lease_token.is_(None), Op.lease_until <= now),
            )
            .order_by(Op.next_attempt_at, Op.operation_id)
            .limit(limit)
        )
        return (await session.execute(statement)).all()

    async def message_target(self, session, *, operation_id, tenant_id):
        return (
            await session.execute(
                select(Op.tenant_id, Op.kind, Op.provider_instance_id, Op.revision).where(
                    Op.operation_id == operation_id, Op.tenant_id == tenant_id
                )
            )
        ).one_or_none()

    async def claim_instance_slot(
        self,
        session,
        *,
        tenant_id,
        operation_id,
        expected_revision,
        instance_id,
        kind,
        concurrency,
        clock,
        lease_seconds,
    ):
        # Serialize admissions across processes. This locking read MUST precede
        # any snapshot read in this transaction (MySQL REPEATABLE READ).
        if (
            await session.scalar(
                select(Instance.id).where(Instance.tenant_id == tenant_id, Instance.id == instance_id).with_for_update()
            )
            is None
        ):
            return None
        now = clock()
        active = await session.scalar(
            select(func.count())
            .select_from(Op)
            .where(Op.tenant_id == tenant_id, Op.provider_instance_id == instance_id, Op.lease_until > now)
        )
        if active >= concurrency:
            return None
        return await self.claim(
            session,
            tenant_id=tenant_id,
            operation_id=operation_id,
            now=now,
            lease_seconds=lease_seconds,
            expected_revision=expected_revision,
            instance_id=instance_id,
            kind=kind,
        )

    async def claim(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        operation_id: str,
        now: datetime,
        lease_seconds: int,
        expected_revision: int | None = None,
        instance_id: int | None = None,
        kind: str | None = None,
    ) -> Op | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        token = str(uuid4())
        identity = [Op.tenant_id == tenant_id, Op.operation_id == operation_id]
        if expected_revision is not None:
            identity.append(Op.revision == expected_revision)
        if instance_id is not None:
            identity.append(Op.provider_instance_id == instance_id)
        if kind is not None:
            identity.append(Op.kind == kind)
        result = await session.execute(
            update(Op)
            .where(
                *identity,
                Op.state.in_(_RUNNABLE),
                Op.next_attempt_at <= now,
                or_(Op.lease_token.is_(None), Op.lease_until <= now),
            )
            .values(
                state=case((Op.state == "pending", "sending"), (Op.state == "sending", "reconciling"), else_=Op.state),
                lease_token=token,
                lease_until=now + timedelta(seconds=lease_seconds),
                revision=Op.revision + 1,
                attempt=Op.attempt + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            return None
        return (
            await session.scalars(
                select(Op)
                .where(Op.tenant_id == tenant_id, Op.operation_id == operation_id, Op.lease_token == token)
                .execution_options(populate_existing=True)
            )
        ).one()

    async def apply(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        operation_id: str,
        lease_token: str,
        expected_revision: int,
        generation: int,
        operation_epoch: int,
        now: datetime,
        state: str,
        next_attempt_at: datetime | None = None,
        remote_task_id: str | None = None,
        next_phase: str | None = None,
        last_error_code: str | None = None,
    ) -> bool:
        sources = [src for src, allowed in _NEXT.items() if state in allowed]
        if not sources or not lease_token:
            return False
        values = {
            "state": state,
            "revision": Op.revision + 1,
            "lease_token": None,
            "lease_until": None,
            "next_attempt_at": (next_attempt_at or now) if state in _RUNNABLE else None,
            "last_error_code": last_error_code,
        }
        if next_phase is not None:
            if state != "applying" or not next_phase or len(next_phase) > 48:
                raise ValueError("invalid projection checkpoint")
            values["phase"] = next_phase
        if remote_task_id is not None:
            values["remote_task_id"] = remote_task_id
        result = await session.execute(
            update(Op)
            .where(
                Op.tenant_id == tenant_id,
                Op.operation_id == operation_id,
                Op.lease_token == lease_token,
                Op.lease_until > now,
                Op.revision == expected_revision,
                Op.generation == generation,
                Op.operation_epoch == operation_epoch,
                Op.state.in_(sources),
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1
