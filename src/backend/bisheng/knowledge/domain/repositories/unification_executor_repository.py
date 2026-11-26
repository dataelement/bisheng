"""Native Run attempt fencing and a dedicated, fail-closed DB control lock."""

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from uuid import uuid4

from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.domain.models.knowledge_unification_executor_lock import KnowledgeUnificationExecutorLock
from bisheng.knowledge.domain.repositories.unification_run_repository import KnowledgeUnificationRunRepository

_ATTEMPT = "executor_attempt_v1"


def _reject(reason):
    raise KnowledgeOperationPlanConflictError(reason="migration_executor_" + reason)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def carry_executor_checkpoint(row, next_phase):
    """Close/carry the execution identity atomically with the native phase."""
    latest = UnificationExecutorRepository._latest(row)
    if latest is None:
        return
    state = latest[2]
    if state["pending"] is not None:
        _reject("recovery_required")
    checkpoints = deepcopy(row.checkpoints)
    previous = checkpoints.get(row.phase, {}).get(_ATTEMPT)
    if previous is None:
        _reject("attempt_phase_mismatch")
    previous["complete"] = True
    if next_phase != "completed":
        state = dict(state, sequence=state["sequence"] + 1)
        checkpoints.setdefault(next_phase, {})[_ATTEMPT] = {
            "cursor": _json(state),
            "processed_count": state["sequence"],
            "digest": _digest(state),
            "complete": False,
        }
    else:
        state = dict(state, closed=True)
        previous.update(cursor=_json(state), digest=_digest(state))
    row.checkpoints = checkpoints


class ExecutorControlLease:
    def __init__(self, connection):
        self.connection, self.lost = connection, False
        self._probe_lock = asyncio.Lock()

    async def ensure(self):
        async with self._probe_lock:
            if (
                self.lost
                or self.connection.closed
                or self.connection.invalidated
                or not self.connection.in_transaction()
            ):
                self.lost = True
                _reject("lock_lost")
            try:
                # Execute on the very same active transaction. An invalidated
                # transaction may never transparently reconnect and regain authority.
                result = await self.connection.execute(
                    select(KnowledgeUnificationExecutorLock.id).where(
                        KnowledgeUnificationExecutorLock.id == "f118-global"
                    )
                )
                if result.scalar_one_or_none() != "f118-global":
                    self.lost = True
                    _reject("lock_lost")
            except DBAPIError as error:
                self.lost = True
                raise KnowledgeOperationPlanConflictError(reason="migration_executor_lock_lost") from error


class UnificationExecutorRepository:
    def __init__(self):
        self.runs = KnowledgeUnificationRunRepository()

    async def ahas_control_seed(self, engine):
        """Read-only admission probe; bootstrap is never a failed plan's effect."""
        async with engine.connect() as connection:
            result = await connection.execute(
                select(KnowledgeUnificationExecutorLock.id).where(KnowledgeUnificationExecutorLock.id == "f118-global")
            )
            return result.scalar_one_or_none() == "f118-global"

    @asynccontextmanager
    async def acquire(self, engine):
        if engine.dialect.name not in {"mysql", "dm", "dm8"}:
            _reject("unsupported_lock_dialect")
        with tenant_execution_scope(1):
            # A unique conflict is bounded to one reread. Never hold the Tenant
            # or Run row for the command: business connections need those locks.
            try:
                async with AsyncSession(engine) as session, session.begin():
                    row = await session.get(KnowledgeUnificationExecutorLock, "f118-global")
                    if row is None:
                        session.add(KnowledgeUnificationExecutorLock())
                        await session.flush()
            except IntegrityError:
                async with AsyncSession(engine) as session, session.begin():
                    if await session.get(KnowledgeUnificationExecutorLock, "f118-global") is None:
                        _reject("bootstrap_conflict")
            async with engine.connect() as connection:
                async with connection.begin():
                    try:
                        statement = (
                            select(KnowledgeUnificationExecutorLock.id)
                            .where(KnowledgeUnificationExecutorLock.id == "f118-global")
                            .with_for_update(nowait=True)
                        )
                        if (await connection.execute(statement)).scalar_one_or_none() != "f118-global":
                            _reject("bootstrap_missing")
                    except DBAPIError as error:
                        raise KnowledgeOperationPlanConflictError(
                            reason="migration_executor_busy_or_lock_unavailable"
                        ) from error
                    yield ExecutorControlLease(connection)

    @staticmethod
    def _latest(row):
        values = []
        for checkpoints in row.checkpoints.values():
            if isinstance(checkpoints, dict) and _ATTEMPT in checkpoints:
                checkpoint = checkpoints[_ATTEMPT]
                try:
                    state = json.loads(checkpoint["cursor"])
                    if (
                        type(state) is not dict
                        or set(state) != {"schema_version", "token", "sequence", "pending", "closed", "terminal_digest"}
                        or state["schema_version"] != 1
                        or _json(state) != checkpoint["cursor"]
                        or checkpoint["digest"] != _digest(state)
                        or type(state["sequence"]) is not int
                        or state["sequence"] <= 0
                        or checkpoint["processed_count"] != state["sequence"]
                        or type(state["closed"]) is not bool
                    ):
                        _reject("attempt_invalid")
                except (ValueError, TypeError, KeyError) as error:
                    raise KnowledgeOperationPlanConflictError(reason="migration_executor_attempt_invalid") from error
                values.append((state["sequence"], checkpoint, state))
        return max(values, default=None, key=lambda item: item[0])

    async def _save(self, session, row, state, *, complete=False):
        if row.phase == "completed":
            _reject("completed_is_read_only")
        expected = row.checkpoints.get(row.phase, {}).get(_ATTEMPT)
        return await self.runs.acheckpoint(
            session,
            run_id=row.run_id,
            writer_contract_version=row.writer_contract_version,
            baseline_hash=row.baseline_hash,
            plan_hash=row.plan_hash,
            expected_phase=row.phase,
            checkpoint_key=_ATTEMPT,
            expected_checkpoint=expected,
            checkpoint={
                "cursor": _json(state),
                "processed_count": state["sequence"],
                "digest": _digest(state),
                "complete": complete,
            },
        )

    async def abegin_attempt(self, session, *, run_id, writer_contract_version, token=None):
        row = await self.runs.aget_or_create(session, run_id=run_id, writer_contract_version=writer_contract_version)
        if row.phase == "completed":
            return None
        latest = self._latest(row)
        if latest is not None and latest[2]["pending"] is not None:
            _reject("recovery_required")
        sequence = latest[0] + 1 if latest is not None else 1
        state = {
            "schema_version": 1,
            "token": token or uuid4().hex,
            "sequence": sequence,
            "pending": None,
            "closed": False,
            "terminal_digest": None,
        }
        # The global lock excludes a second scheduler; the root Run lock fences
        # any late old SQL batch before changing the durable generation.
        await self._save(session, row, state)
        return state["token"]

    async def acheck_attempt(self, session, *, run_id, writer_contract_version, token):
        row = await self.runs._required(session, run_id, writer_contract_version)
        latest = self._latest(row)
        if latest is None or latest[2]["token"] != token or latest[2]["closed"] or latest[1]["complete"]:
            _reject("attempt_changed")
        return row, latest[2]

    async def abegin_external(self, session, *, run_id, writer_contract_version, token, kind, identity):
        row, state = await self.acheck_attempt(
            session, run_id=run_id, writer_contract_version=writer_contract_version, token=token
        )
        if (
            kind
            not in {
                "fga",
                "history",
                "history_fga",
                "permission_publish",
                "namespace",
                "permission_tuple_batch",
                "permission_prepare",
            }
            or type(identity) is not dict
        ):
            _reject("invalid_external_intent")
        if state["pending"] is not None:
            _reject("recovery_required")
        encoded = _json(identity).encode()
        if len(encoded) > 4096:
            _reject("invalid_external_intent")
        ticket = uuid4().hex
        state = dict(
            state,
            pending={
                "ticket": ticket,
                "kind": kind,
                "identity_digest": hashlib.sha256(encoded).hexdigest(),
                "outcome": "dispatched",
            },
        )
        await self._save(session, row, state)
        return ticket

    async def afinish_external(self, session, *, run_id, writer_contract_version, token, ticket, outcome, receipt=None):
        row, state = await self.acheck_attempt(
            session, run_id=run_id, writer_contract_version=writer_contract_version, token=token
        )
        if state["pending"] is None or state["pending"]["ticket"] != ticket:
            _reject("intent_changed")
        if outcome == "unknown":
            # The persisted dispatch intent stays open. A snapshot or timeout
            # cannot prove request termination, so no automatic new intent.
            await self._save(session, row, dict(state, pending=dict(state["pending"], outcome="unknown")))
            return
        if outcome != "acknowledged" or not isinstance(receipt, str) or not receipt or len(receipt) > 128:
            _reject("terminal_receipt_required")
        await self._save(
            session,
            row,
            dict(state, pending=None, terminal_digest=_digest({"intent": state["pending"], "receipt": receipt})),
        )

    async def afinish_attempt(self, session, *, run_id, writer_contract_version, token):
        row, state = await self.acheck_attempt(
            session, run_id=run_id, writer_contract_version=writer_contract_version, token=token
        )
        if state["pending"] is not None:
            _reject("recovery_required")
        if row.phase != "completed":
            await self._save(session, row, dict(state, closed=True))
