"""Execute only the SQL substep of one genuine frozen M2 plan.

The operational caller supplies an owned fresh-session factory and artifact IO.
This entry neither inventories again nor certifies namespace/reference readiness.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from weakref import WeakSet

from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore
from bisheng.knowledge.application.unification_conversion_codec import decode_sql_conversion_page
from bisheng.knowledge.application.unification_inventory import UnificationInventoryApplication
from bisheng.knowledge.domain.repositories.unification_run_repository import KnowledgeUnificationRunRepository
from bisheng.knowledge.domain.services.unification_conversion import SQLConversionProgress, UnificationConversionService


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason="migration_sql_application_" + reason)


@dataclass(frozen=True, slots=True)
class TenantSQLConversionProgress:
    tenant_id: int
    command_count: int
    deferred_count: int
    progress: SQLConversionProgress


@dataclass(frozen=True, slots=True)
class SQLConversionExecutionReport:
    run_id: str
    writer_contract_version: str
    baseline_hash: str
    plan_hash: str
    tenant_ids: tuple[int, ...]
    tenant_progress: tuple[TenantSQLConversionProgress, ...]
    sql_complete: bool


@dataclass(frozen=True, slots=True)
class _Member:
    tenant_id: int
    page_index: int
    record_count: int
    command_count: int
    descriptor: dict = field(repr=False)


class UnificationSQLConversionApplication:
    def __init__(self, *, artifact_store, session_factory, sql_service=None):
        if not isinstance(artifact_store, UnificationArtifactStore) or not callable(session_factory):
            _blocked("native_ports_required")
        if sql_service is not None and not isinstance(sql_service, UnificationConversionService):
            _blocked("actual_sql_service_required")
        self.store, self.sessions = artifact_store, session_factory
        self.sql = sql_service or UnificationConversionService()
        self.runs = KnowledgeUnificationRunRepository()
        self.reader = UnificationInventoryApplication(artifact_store=artifact_store)
        self._seen = WeakSet()

    @asynccontextmanager
    async def _session(self):
        async with self.sessions() as session:
            if not isinstance(session, AsyncSession) or session.in_transaction() or session in self._seen:
                _blocked("fresh_native_session_required")
            self._seen.add(session)
            yield session

    @staticmethod
    def _identity(frozen):
        return {
            "run_id": frozen.run_id,
            "writer_contract_version": frozen.writer_contract_version,
            "baseline_hash": frozen.baseline_ref["sha256"],
            "plan_hash": frozen.plan_ref["sha256"],
        }

    async def _scope_run(self, session, frozen):
        run = await self.sql.repository.aread_run(
            session, run_id=frozen.run_id, writer_contract_version=frozen.writer_contract_version, lock=True
        )
        if (
            run.phase not in {"baseline_frozen", "converting"}
            or run.baseline_ref != frozen.baseline_ref
            or run.plan_ref != frozen.plan_ref
            or run.baseline_hash != frozen.baseline_ref["sha256"]
            or run.plan_hash != frozen.plan_ref["sha256"]
        ):
            _blocked("frozen_run_changed")
        return run

    async def _admit(self, run_id, writer):
        async with self._session() as session, session.begin():
            tenants = await self.runs.alist_actual_tenant_ids(session)
            frozen = await self.runs.aget_global_freeze(
                session, run_id=run_id, writer_contract_version=writer, tenant_ids=tenants
            )
            if frozen is None:
                _blocked("actual_frozen_run_required")
            for tenant in tenants:
                with tenant_execution_scope(tenant):
                    await self._scope_run(session, frozen)
            return frozen

    async def _plan(self, frozen, *, environment, backup_ref, schema_ref):
        members = {tenant: [] for tenant in frozen.tenant_ids}
        totals, deferred = dict.fromkeys(frozen.tenant_ids, 0), dict.fromkeys(frozen.tenant_ids, 0)
        # Exhaust the entire verified graph, including late non-SQL leaves and
        # backup/schema materials, before opening any business-write transaction.
        async for page in self.reader.aiter_frozen_pages(
            frozen, environment=environment, backup_ref=backup_ref, schema_ref=schema_ref
        ):
            if page.kind != "plan" or page.section != "conversion":
                continue
            if page.scope != "tenant" or page.tenant_id not in members:
                _blocked("conversion_membership")
            decoded = decode_sql_conversion_page(
                page.content,
                run_id=frozen.run_id,
                writer_contract_version=frozen.writer_contract_version,
                tenant_id=page.tenant_id,
                page_index=page.page_index,
            )
            totals[page.tenant_id] += len(decoded.commands)
            deferred[page.tenant_id] += len(decoded.deferred)
            members[page.tenant_id].append(
                _Member(
                    page.tenant_id, page.page_index, page.record_count, len(decoded.commands), dict(page.descriptor)
                )
            )
        return members, totals, deferred

    async def _page(self, frozen, member):
        content = await self.store.aload_canonical(member.descriptor, run_id=frozen.run_id, kind="plan")
        decoded = decode_sql_conversion_page(
            content,
            run_id=frozen.run_id,
            writer_contract_version=frozen.writer_contract_version,
            tenant_id=member.tenant_id,
            page_index=member.page_index,
        )
        if (
            len(decoded.commands) != member.command_count
            or len(decoded.commands) + len(decoded.deferred) != member.record_count
        ):
            _blocked("conversion_page_changed")
        return decoded.commands

    async def _status(self, frozen):
        async with self._session() as session, session.begin():
            run = await self._scope_run(session, frozen)
            if run.phase == "baseline_frozen":
                if run.checkpoints.get("converting", {}).get("sql_conversion") is not None:
                    _blocked("checkpoint_before_phase")
                return None
            progress = await self.sql.aget_progress(session, **self._identity(frozen))
            return progress if progress.digest is not None else None

    async def _verify(self, frozen, commands, ordinal, goal, continuation, eof):
        async with self._session() as session, session.begin():
            await self._scope_run(session, frozen)
            batch = await self.sql._issue_verified_batch(
                session,
                **self._identity(frozen),
                commands=commands,
                expected_checkpoint=goal,
                ordinal=ordinal,
                continuation=continuation,
                eof=eof,
                mode="verify",
            )
            result = await self.sql.averify_committed_page(session, batch=batch)
        return result

    async def _apply(self, frozen, commands, ordinal, current, continuation, eof, state):
        async with self._session() as session:
            await session.begin()
            try:
                run = await self._scope_run(session, frozen)
                if run.phase == "baseline_frozen":
                    await self.runs.aadvance(
                        session, **self._identity(frozen), expected_phase="baseline_frozen", next_phase="converting"
                    )
                batch = await self.sql._issue_verified_batch(
                    session,
                    **self._identity(frozen),
                    commands=commands,
                    expected_checkpoint=current,
                    ordinal=ordinal,
                    continuation=continuation,
                    eof=eof,
                )
                result = await self.sql.aapply_batch(session, batch=batch)
                state["stage"] = "commit"
                await session.commit()
            except BaseException:
                try:
                    if session.in_transaction():
                        await session.rollback()
                except Exception:
                    # The primary failure remains authoritative, including an
                    # unknown COMMIT result. Cleanup cannot prove non-commit.
                    logger.opt(exception=True).warning("SQL conversion rollback failed after a primary error")
                raise
        # A receipt becomes a cross-session continuation ONLY after commit ACK.
        state["last_acknowledged_progress"] = asdict(result.progress)
        state["stage"] = "apply"
        return result

    async def _tenant(self, frozen, tenant, members, total, deferred, state):
        state.update(tenant_id=tenant, stage="read_progress", last_acknowledged_progress=None)
        goal = await self._status(frozen)
        if goal is not None and (goal.processed_count > total or (goal.complete and goal.processed_count != total)):
            _blocked("checkpoint_outside_plan")
        ordinal, continuation, current = 0, None, goal
        if goal is not None and goal.processed_count == 0:
            state["stage"] = "verify_prefix"
            continuation = await self._verify(frozen, (), 0, goal, None, True)
            state["last_acknowledged_progress"] = asdict(goal)
        for member in members:
            state["stage"] = "read_page"
            commands = await self._page(frozen, member)
            take = min(len(commands), max(0, goal.processed_count - ordinal)) if goal else 0
            if take:
                state["stage"] = "verify_prefix"
                continuation = await self._verify(
                    frozen, commands[:take], ordinal, goal, continuation, ordinal + take == goal.processed_count
                )
                ordinal += take
                if continuation.verification_complete:
                    state["last_acknowledged_progress"] = asdict(goal)
            if commands[take:]:
                state["stage"] = "apply"
                continuation = await self._apply(
                    frozen,
                    commands[take:],
                    ordinal,
                    current,
                    continuation,
                    ordinal + len(commands[take:]) == total,
                    state,
                )
                current, ordinal = continuation.progress, ordinal + len(commands[take:])
        if ordinal != total:
            _blocked("conversion_count_changed")
        if current is None or not current.complete:
            state["stage"] = "apply"
            continuation = await self._apply(frozen, (), ordinal, current, continuation, True, state)
            current = continuation.progress
        return TenantSQLConversionProgress(tenant, total, deferred, current)

    async def arun_permissions(
        self, *, run_id, writer_contract_version, environment, backup_ref, schema_ref, operator_id
    ):
        from bisheng.knowledge.application.unification_permissions import run_permissions

        return await run_permissions(
            self,
            run_id=run_id,
            writer_contract_version=writer_contract_version,
            environment=environment,
            backup_ref=backup_ref,
            schema_ref=schema_ref,
            operator_id=operator_id,
        )

    async def arun(self, *, run_id, writer_contract_version, environment, backup_ref, schema_ref):
        state = {"run_id": None, "tenant_id": None, "stage": "read_frozen", "last_acknowledged_progress": None}
        try:
            self.runs._identity(run_id, writer_contract_version)
            state["run_id"] = run_id
            frozen = await self._admit(run_id, writer_contract_version)
            members, totals, deferred = await self._plan(
                frozen, environment=environment, backup_ref=backup_ref, schema_ref=schema_ref
            )
            result = []
            for tenant in frozen.tenant_ids:
                with tenant_execution_scope(tenant):
                    result.append(
                        await self._tenant(frozen, tenant, members[tenant], totals[tenant], deferred[tenant], state)
                    )
            state["stage"] = "verify_universe"
            if await self._admit(run_id, writer_contract_version) != frozen:
                _blocked("frozen_universe_changed")
            return SQLConversionExecutionReport(
                run_id,
                writer_contract_version,
                frozen.baseline_ref["sha256"],
                frozen.plan_ref["sha256"],
                frozen.tenant_ids,
                tuple(result),
                True,
            )
        except asyncio.CancelledError as error:
            error.sql_conversion_report = state | {
                "commit_outcome": "unknown" if state["stage"] == "commit" else "not_attempted"
            }
            raise
        except Exception as error:
            report = state | {"commit_outcome": "unknown" if state["stage"] == "commit" else "not_attempted"}
            if isinstance(error, BaseErrorCode):
                error.kwargs["sql_conversion_report"] = report
                raise
            raise ReferenceCoverageNotReadyError(
                reason="migration_sql_conversion_failed", sql_conversion_report=report
            ) from error
