"""F118 maintenance ledger; the caller owns the native async transaction.

Artifacts have already been uploaded by the operational inventory owner. This
repository stores their immutable descriptors, never blob bytes or local files.
Lifecycle progress does not certify reference Coverage or perform migration.
"""

import re
from collections.abc import Mapping
from copy import deepcopy
from itertools import pairwise
from typing import NoReturn

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge_unification_run import (
    KnowledgeUnificationPhase,
    KnowledgeUnificationRun,
    unification_now,
)

_PHASES = tuple(phase.value for phase in KnowledgeUnificationPhase if phase != KnowledgeUnificationPhase.FAILED)
_NEXT = dict(pairwise(_PHASES))
_FAILED_FROM = "_failed_from_phase"
_CHECKPOINT_FIELDS = {"cursor", "processed_count", "digest", "complete"}


def _reject(reason: str) -> NoReturn:
    raise KnowledgeOperationPlanConflictError(reason=f"migration_ledger_{reason}")


def _name(value, length: int) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value) is not None
        and len(value) <= length
    )


def _hash(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _descriptor(value) -> dict:
    if not isinstance(value, Mapping) or set(value) != {"object_key", "sha256"}:
        _reject("invalid_artifact")
    key = value["object_key"]
    if (
        not isinstance(key, str)
        or not key.strip()
        or key.startswith("/")
        or key.casefold().startswith("file:")
        or "://" in key
        or not _hash(value["sha256"])
    ):
        _reject("invalid_artifact")
    return {"object_key": key, "sha256": value["sha256"]}


def _checkpoint(value) -> dict:
    if (
        not isinstance(value, Mapping)
        or set(value) != _CHECKPOINT_FIELDS
        or (value["cursor"] is not None and not isinstance(value["cursor"], str))
        or type(value["processed_count"]) is not int
        or value["processed_count"] < 0
        or (value["digest"] is not None and not _hash(value["digest"]))
        or type(value["complete"]) is not bool
    ):
        _reject("invalid_checkpoint")
    return deepcopy(dict(value))


def _failure(error_code, error_reason) -> None:
    # Only a bounded machine reason is persisted, never exception text/config.
    if type(error_code) is not int or not 10000 <= error_code <= 99999 or not _name(error_reason, 128):
        _reject("invalid_failure")


class KnowledgeUnificationRunRepository:
    @staticmethod
    def _tenant() -> int:
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
            _reject("invalid_tenant_scope")
        return tenant

    @staticmethod
    def _identity(run_id: str, writer_contract_version: str) -> None:
        if not _name(run_id, 64) or not _name(writer_contract_version, 32):
            _reject("invalid_identity")

    def _validate(self, row: KnowledgeUnificationRun, run_id: str, writer_contract_version: str) -> None:
        if (
            row.tenant_id != self._tenant()
            or row.run_id != run_id
            or row.writer_contract_version != writer_contract_version
            or row.origin != "migration"
            or row.phase not in (*_PHASES, "failed")
            or not isinstance(row.checkpoints, dict)
        ):
            _reject("run_mismatch")
        evidence_phase = row.phase
        if row.phase == "failed":
            evidence_phase = row.checkpoints.get(_FAILED_FROM)
            if evidence_phase not in _PHASES[:-1]:
                _reject("invalid_recovery_phase")
            _failure(row.error_code, row.error_reason)
        elif _FAILED_FROM in row.checkpoints or row.error_code is not None or row.error_reason is not None:
            _reject("invalid_recovery_state")
        if evidence_phase == "preparing":
            if (
                row.baseline_hash is not None
                or row.plan_hash is not None
                or row.baseline_ref != {}
                or row.plan_ref != {}
            ):
                _reject("unfrozen_evidence_changed")
        elif (
            _descriptor(row.baseline_ref)["sha256"] != row.baseline_hash
            or _descriptor(row.plan_ref)["sha256"] != row.plan_hash
        ):
            _reject("frozen_evidence_changed")
        for phase, checkpoints in row.checkpoints.items():
            if phase == _FAILED_FROM:
                continue
            if phase not in _PHASES or not isinstance(checkpoints, dict):
                _reject("invalid_checkpoint_phase")
            for key, value in checkpoints.items():
                if not _name(key, 64):
                    _reject("invalid_checkpoint_key")
                _checkpoint(value)

    async def _row(
        self,
        session: AsyncSession,
        run_id: str,
        writer_contract_version: str,
        *,
        lock: bool = False,
    ) -> KnowledgeUnificationRun | None:
        self._tenant()
        self._identity(run_id, writer_contract_version)
        statement = (
            select(KnowledgeUnificationRun)
            .where(KnowledgeUnificationRun.run_id == run_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        with session.no_autoflush, strict_tenant_filter():
            row = (await session.execute(statement)).scalar_one_or_none()
        if row is not None:
            self._validate(row, run_id, writer_contract_version)
        return row

    async def _required(self, session, run_id, writer_contract_version) -> KnowledgeUnificationRun:
        row = await self._row(session, run_id, writer_contract_version, lock=True)
        if row is None:
            _reject("run_missing")
        return row

    async def _lock_tenant(self, session: AsyncSession) -> None:
        # Existing tenants, including disabled tenants retaining configuration,
        # serialize first-run creation without a new lock table or revision.
        tenant = self._tenant()
        with session.no_autoflush, strict_tenant_filter():
            found = (
                await session.execute(select(Tenant.id).where(Tenant.id == tenant).with_for_update())
            ).scalar_one_or_none()
        if found != tenant:
            _reject("tenant_missing")

    async def _unique_run(self, session, run_id, writer_contract_version) -> None:
        with session.no_autoflush, strict_tenant_filter():
            other = (
                await session.execute(
                    select(KnowledgeUnificationRun.id)
                    .where(
                        KnowledgeUnificationRun.writer_contract_version == writer_contract_version,
                        KnowledgeUnificationRun.origin == "migration",
                        KnowledgeUnificationRun.run_id != run_id,
                    )
                    .limit(1)
                    .with_for_update()
                )
            ).scalar_one_or_none()
        if other is not None:
            _reject("another_run_exists")

    @staticmethod
    def _hashes(row, baseline_hash, plan_hash) -> None:
        if row.baseline_hash != baseline_hash or row.plan_hash != plan_hash:
            _reject("frozen_hash_mismatch")

    def _expected(self, row, expected_phase, baseline_hash, plan_hash) -> None:
        self._hashes(row, baseline_hash, plan_hash)
        if row.phase != expected_phase:
            _reject("phase_changed")

    @staticmethod
    async def _save(session, row) -> KnowledgeUnificationRun:
        row.update_time = unification_now()
        session.add(row)
        await session.flush()
        return row

    async def aschema_precheck(self, session: AsyncSession) -> None:
        self._tenant()
        try:
            with session.no_autoflush, strict_tenant_filter():
                await session.execute(select(KnowledgeUnificationRun).limit(0))
        except SQLAlchemyError as exc:
            raise ReferenceCoverageNotReadyError(reason="migration_ledger_schema_not_ready") from exc

    async def aget(
        self, session: AsyncSession, *, run_id: str, writer_contract_version: str
    ) -> KnowledgeUnificationRun | None:
        return await self._row(session, run_id, writer_contract_version)

    async def aget_or_create(
        self, session: AsyncSession, *, run_id: str, writer_contract_version: str
    ) -> KnowledgeUnificationRun:
        self._identity(run_id, writer_contract_version)
        await self._lock_tenant(session)
        row = await self._row(session, run_id, writer_contract_version, lock=True)
        await self._unique_run(session, run_id, writer_contract_version)
        if row is not None:
            return row
        row = KnowledgeUnificationRun(
            run_id=run_id, writer_contract_version=writer_contract_version, origin="migration"
        )
        return await self._save(session, row)

    async def afreeze(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        writer_contract_version: str,
        baseline_ref: Mapping,
        plan_ref: Mapping,
    ) -> KnowledgeUnificationRun:
        self._identity(run_id, writer_contract_version)
        baseline, plan = _descriptor(baseline_ref), _descriptor(plan_ref)
        await self._lock_tenant(session)
        row = await self._required(session, run_id, writer_contract_version)
        await self._unique_run(session, run_id, writer_contract_version)
        if row.phase == "failed":
            _reject("explicit_recovery_required")
        if row.phase != "preparing":
            if row.baseline_ref != baseline or row.plan_ref != plan:
                _reject("frozen_evidence_changed")
            return row
        row.baseline_ref, row.plan_ref = baseline, plan
        row.baseline_hash, row.plan_hash = baseline["sha256"], plan["sha256"]
        row.phase = "baseline_frozen"
        return await self._save(session, row)

    async def aadvance(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        writer_contract_version: str,
        baseline_hash: str,
        plan_hash: str,
        expected_phase: str,
        next_phase: str,
    ) -> KnowledgeUnificationRun:
        if expected_phase == "preparing" or expected_phase not in _NEXT or _NEXT[expected_phase] != next_phase:
            _reject("invalid_phase_transition")
        row = await self._required(session, run_id, writer_contract_version)
        self._expected(row, expected_phase, baseline_hash, plan_hash)
        row.phase = next_phase
        return await self._save(session, row)

    async def acheckpoint(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        writer_contract_version: str,
        baseline_hash: str | None,
        plan_hash: str | None,
        expected_phase: str,
        checkpoint_key: str,
        expected_checkpoint: Mapping | None,
        checkpoint: Mapping,
    ) -> KnowledgeUnificationRun:
        if expected_phase not in _PHASES[:-1] or not _name(checkpoint_key, 64):
            _reject("invalid_checkpoint_phase_or_key")
        expected = _checkpoint(expected_checkpoint) if expected_checkpoint is not None else None
        value = _checkpoint(checkpoint)
        row = await self._required(session, run_id, writer_contract_version)
        self._expected(row, expected_phase, baseline_hash, plan_hash)
        actual = row.checkpoints.get(expected_phase, {}).get(checkpoint_key)
        if actual == value:
            return row
        if actual != expected:
            _reject("checkpoint_changed")
        if actual is not None and (
            value["processed_count"] < actual["processed_count"] or (actual["complete"] and not value["complete"])
        ):
            _reject("checkpoint_regressed")
        checkpoints = deepcopy(row.checkpoints)
        checkpoints.setdefault(expected_phase, {})[checkpoint_key] = value
        row.checkpoints = checkpoints
        return await self._save(session, row)

    async def afail(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        writer_contract_version: str,
        baseline_hash: str | None,
        plan_hash: str | None,
        expected_phase: str,
        error_code: int,
        error_reason: str,
    ) -> KnowledgeUnificationRun:
        if expected_phase not in _PHASES[:-1]:
            _reject("invalid_failure_phase")
        _failure(error_code, error_reason)
        row = await self._required(session, run_id, writer_contract_version)
        self._hashes(row, baseline_hash, plan_hash)
        if row.phase == "failed":
            if (
                row.checkpoints[_FAILED_FROM] != expected_phase
                or row.error_code != error_code
                or row.error_reason != error_reason
            ):
                _reject("failure_changed")
            return row
        self._expected(row, expected_phase, baseline_hash, plan_hash)
        row.checkpoints = {**deepcopy(row.checkpoints), _FAILED_FROM: expected_phase}
        row.phase, row.error_code, row.error_reason = "failed", error_code, error_reason
        return await self._save(session, row)

    async def aresume(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        writer_contract_version: str,
        baseline_hash: str | None,
        plan_hash: str | None,
    ) -> KnowledgeUnificationRun:
        row = await self._required(session, run_id, writer_contract_version)
        self._hashes(row, baseline_hash, plan_hash)
        if row.phase != "failed":
            _reject("run_not_failed")
        checkpoints = deepcopy(row.checkpoints)
        row.phase = checkpoints.pop(_FAILED_FROM)
        row.checkpoints = checkpoints
        row.error_code = row.error_reason = None
        return await self._save(session, row)
