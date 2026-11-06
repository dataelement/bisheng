"""Verified finite SQL batches; only the caller commits the parent transaction.

The private issuer is an internal handoff for the future frozen-artifact reader.
It does not discover or certify artifact membership by inspecting command values.
"""

import re
from dataclasses import asdict, dataclass
from weakref import WeakKeyDictionary

from bisheng.knowledge.domain.repositories.unification_conversion_repository import (
    KINDS,
    UnificationConversionRepository,
    _blocked,
    _clean,
    _hash,
)
from bisheng.knowledge.domain.repositories.unification_resource_repository import _scope
from bisheng.knowledge.domain.repositories.unification_run_repository import KnowledgeUnificationRunRepository
from bisheng.knowledge.domain.services.unification_fingerprints import digest
from bisheng.resource_reference.application.contracts import TransactionIdentity


@dataclass(frozen=True, slots=True)
class SQLConversionProgress:
    cursor: str | None
    processed_count: int
    digest: str | None
    complete: bool


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class VerifiedConversionBatch:
    run_id: str
    writer_contract_version: str
    tenant_id: int
    baseline_hash: str
    plan_hash: str
    commands: tuple
    expected_checkpoint: SQLConversionProgress | None
    ordinal: int
    eof: bool
    mode: str


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class SQLConversionBatchResult:
    progress: SQLConversionProgress
    outcomes: tuple
    verification_complete: bool = False


def _identity(batch):
    return {name: getattr(batch, name) for name in ("run_id", "writer_contract_version", "baseline_hash", "plan_hash")}


def _progress(value):
    if value is None:
        return SQLConversionProgress(None, 0, None, False)
    if type(value) is not dict or set(value) != {"cursor", "processed_count", "digest", "complete"}:
        _blocked("invalid_sql_checkpoint")
    count, cursor = value["processed_count"], value["cursor"]
    if (
        type(count) is not int
        or count < 0
        or type(value["complete"]) is not bool
        or not _hash(value["digest"])
        or (count == 0 and cursor is not None)
        or (count > 0 and (type(cursor) is not str or re.fullmatch(rf"sql-v1:{count}:[0-9a-f]{{64}}", cursor) is None))
    ):
        _blocked("invalid_sql_checkpoint")
    return SQLConversionProgress(**value)


class UnificationConversionService:
    def __init__(self, repository=None):
        self.repository = repository or UnificationConversionRepository()
        self.runs = KnowledgeUnificationRunRepository()
        self._batches, self._results = WeakKeyDictionary(), WeakKeyDictionary()

    async def _run(self, session, identity, *, lock=False):
        run = await self.repository.aread_run(
            session, run_id=identity["run_id"], writer_contract_version=identity["writer_contract_version"], lock=lock
        )
        self.runs._validate(run, identity["run_id"], identity["writer_contract_version"])
        self.runs._expected(run, "converting", identity["baseline_hash"], identity["plan_hash"])
        raw = run.checkpoints.get("converting", {}).get("sql_conversion")
        return _progress(raw), raw

    async def aget_progress(self, session, *, run_id, writer_contract_version, baseline_hash, plan_hash):
        identity = {
            "run_id": run_id,
            "writer_contract_version": writer_contract_version,
            "baseline_hash": baseline_hash,
            "plan_hash": plan_hash,
        }
        return (await self._run(session, identity))[0]

    @staticmethod
    def _seed(batch):
        return digest({"sql_conversion": 1, "tenant_id": batch.tenant_id, **_identity(batch)})

    def _continuation(self, result, batch, *, mode):
        value = self._results.get(result) if type(result) is SQLConversionBatchResult else None
        if (
            value is None
            or value["seal"] != digest(asdict(result))
            or value["identity"] != (batch.tenant_id, _identity(batch))
        ):
            _blocked("unsigned_continuation")
        if mode == "apply":
            if result.progress != batch.expected_checkpoint or (
                value["mode"] == "verify" and not result.verification_complete
            ):
                _blocked("prefix_not_verified")
        elif value["mode"] != "verify" or value["goal"] != batch.expected_checkpoint or result.verification_complete:
            _blocked("prefix_continuation_changed")
        return result.progress

    async def _issue_verified_batch(
        self,
        session,
        *,
        run_id,
        writer_contract_version,
        baseline_hash,
        plan_hash,
        commands,
        expected_checkpoint=None,
        ordinal=0,
        eof=False,
        continuation=None,
        mode="apply",
    ):
        _clean(session)
        if (
            type(commands) is not tuple
            or len(commands) > 200
            or any(type(cmd) not in KINDS for cmd in commands)
            or type(ordinal) is not int
            or ordinal < 0
            or type(eof) is not bool
            or mode not in {"apply", "verify"}
            or (not commands and not eof)
            or (expected_checkpoint is not None and type(expected_checkpoint) is not SQLConversionProgress)
        ):
            _blocked("invalid_verified_batch")
        batch = VerifiedConversionBatch(
            run_id,
            writer_contract_version,
            _scope(session),
            baseline_hash,
            plan_hash,
            commands,
            expected_checkpoint,
            ordinal,
            eof,
            mode,
        )
        current, raw = await self._run(session, _identity(batch), lock=True)
        if current != (expected_checkpoint or SQLConversionProgress(None, 0, None, False)):
            _blocked("checkpoint_changed")
        if mode == "apply":
            if current.complete or ordinal != current.processed_count:
                _blocked("not_next_batch")
            start = SQLConversionProgress(None, 0, self._seed(batch), False)
            if raw is not None:
                start = self._continuation(continuation, batch, mode=mode)
            elif continuation is not None:
                _blocked("unexpected_continuation")
        else:
            if raw is None or ordinal + len(commands) > current.processed_count:
                _blocked("prefix_outside_checkpoint")
            start = SQLConversionProgress(None, 0, self._seed(batch), False)
            if ordinal:
                start = self._continuation(continuation, batch, mode=mode)
            elif continuation is not None:
                _blocked("unexpected_continuation")
            if start.processed_count != ordinal or eof != (ordinal + len(commands) == current.processed_count):
                _blocked("prefix_page_changed")
        self._batches[batch] = {
            "seal": digest(asdict(batch)),
            "transaction": TransactionIdentity.capture(session),
            "checkpoint": raw,
            "start": start,
        }
        return batch

    def _consume(self, session, batch, mode):
        _clean(session)
        value = self._batches.pop(batch, None) if type(batch) is VerifiedConversionBatch else None
        if (
            value is None
            or value["seal"] != digest(asdict(batch))
            or batch.mode != mode
            or batch.tenant_id != _scope(session)
        ):
            _blocked("unsigned_batch")
        try:
            value["transaction"].assert_current(session)
        except (ValueError, TypeError):
            _blocked("original_transaction_changed")
        return value

    async def _check(self, session, batch, value):
        _, actual = await self._run(session, _identity(batch), lock=True)
        if actual != value["checkpoint"]:
            _blocked("checkpoint_changed")

    def _fold(self, batch, start, outcomes, *, complete):
        if len(outcomes) != len(batch.commands):
            _blocked("outcome_count_changed")
        after = start.digest
        for command, outcome in zip(batch.commands, outcomes, strict=True):
            if (outcome.command_key, outcome.operation) != (command.command_key, command.operation):
                _blocked("outcome_changed")
            after = digest({"previous": after, "command": asdict(command), "after": asdict(outcome)})
        count = start.processed_count + len(outcomes)
        cursor = f"sql-v1:{count}:{outcomes[-1].command_key}" if outcomes else start.cursor
        return SQLConversionProgress(cursor, count, after, complete)

    def _result(self, batch, progress, outcomes, *, verified=False):
        result = SQLConversionBatchResult(progress, outcomes, verified)
        self._results[result] = {
            "seal": digest(asdict(result)),
            "identity": (batch.tenant_id, _identity(batch)),
            "mode": batch.mode,
            "goal": batch.expected_checkpoint,
        }
        return result

    async def aapply_batch(self, session, *, batch):
        value = self._consume(session, batch, "apply")
        await self._check(session, batch, value)
        # begin_nested auto-flushes: _consume already rejected all caller pending.
        # This savepoint includes BOTH the repo's writes and the Run checkpoint.
        async with session.begin_nested():
            scope = await self.repository.alock_scope(session, **_identity(batch), commands=batch.commands)
            outcomes = await self.repository.aapply_and_read_after(session, scope=scope)
            next_progress = self._fold(batch, value["start"], outcomes, complete=batch.eof)
            await self.runs.acheckpoint(
                session,
                **_identity(batch),
                expected_phase="converting",
                checkpoint_key="sql_conversion",
                expected_checkpoint=value["checkpoint"],
                checkpoint=asdict(next_progress),
            )
        value["transaction"].assert_current(session)
        return self._result(batch, next_progress, outcomes)

    async def averify_committed_page(self, session, *, batch):
        value = self._consume(session, batch, "verify")
        await self._check(session, batch, value)
        scope = await self.repository.alock_scope(session, **_identity(batch), commands=batch.commands)
        try:
            outcomes = await self.repository.aread_after(session, scope=scope)
        finally:
            self.repository._scopes.pop(scope, None)
        next_progress = self._fold(
            batch, value["start"], outcomes, complete=batch.expected_checkpoint.complete if batch.eof else False
        )
        if batch.eof and next_progress != batch.expected_checkpoint:
            _blocked("committed_prefix_changed")
        value["transaction"].assert_current(session)
        return self._result(batch, next_progress, outcomes, verified=batch.eof)
