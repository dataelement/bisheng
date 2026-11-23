"""Execute only the SQL substep of one genuine frozen M2 plan.

The operational caller supplies an owned fresh-session factory and artifact IO.
This entry neither inventories again nor certifies namespace/reference readiness.
"""

import asyncio
from contextlib import asynccontextmanager, nullcontext
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from weakref import WeakSet

from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application import unification_stage_receipts as receipts
from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore
from bisheng.knowledge.application.unification_conversion_codec import decode_sql_conversion_page
from bisheng.knowledge.application.unification_inventory import UnificationInventoryApplication
from bisheng.knowledge.application.unification_inventory_codec import decode_inventory_page
from bisheng.knowledge.application.unification_progress import report_progress
from bisheng.knowledge.domain.repositories.unification_conversion_repository import UnificationConversionRepository
from bisheng.knowledge.domain.repositories.unification_resource_repository import UnificationResourceRepository
from bisheng.knowledge.domain.repositories.unification_run_repository import KnowledgeUnificationRunRepository
from bisheng.knowledge.domain.services.unification_conversion import (
    SQLConversionProgress,
    UnificationConversionService,
    result_checkpoint,
)


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
    def __init__(
        self,
        *,
        artifact_store,
        session_factory,
        sql_service=None,
        structural_reader_factory=None,
        transaction_guard=None,
        external_guard=None,
        read_only_resume=False,
    ):
        if not isinstance(artifact_store, UnificationArtifactStore) or not callable(session_factory):
            _blocked("native_ports_required")
        if sql_service is not None and not isinstance(sql_service, UnificationConversionService):
            _blocked("actual_sql_service_required")
        if type(read_only_resume) is not bool or (read_only_resume and sql_service is not None):
            _blocked("readonly_resume_requires_native_service")
        self.structural_reader_factory = structural_reader_factory
        self.store, self.sessions = artifact_store, session_factory
        self.read_only_resume = read_only_resume
        self.sql = sql_service or UnificationConversionService(
            repository=UnificationConversionRepository(read_only_resume=read_only_resume)
        )
        self.runs = KnowledgeUnificationRunRepository()
        self.reader = UnificationInventoryApplication(artifact_store=artifact_store)
        self._seen = WeakSet()
        self.transaction_guard, self.external_guard = transaction_guard, external_guard
        self._results_enabled, self._sql_directory = False, None

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
        if not self.read_only_resume and self.transaction_guard is None:
            from bisheng.knowledge.domain.repositories.unification_executor_repository import (
                UnificationExecutorRepository,
            )

            latest = UnificationExecutorRepository._latest(run)
            if latest is not None and not latest[2]["closed"] and not latest[1]["complete"]:
                _blocked("executor_identity_required")
        if (
            run.phase not in {"baseline_frozen", "converting", "backfilling", "verifying", "verified", "completed"}
            or run.baseline_ref != frozen.baseline_ref
            or run.plan_ref != frozen.plan_ref
            or run.baseline_hash != frozen.baseline_ref["sha256"]
            or run.plan_hash != frozen.plan_ref["sha256"]
        ):
            _blocked("frozen_run_changed")
        if run.phase not in {"baseline_frozen", "converting"} and any(
            run.checkpoints.get("converting", {}).get(name, {}).get("complete") is not True
            for name in ("sql_conversion",)
        ):
            _blocked("later_phase_incomplete_conversion")
        if self.transaction_guard is not None:
            await self.transaction_guard(session, run)
        return run

    async def _read_stage_checkpoint(self, frozen, key):
        async with self._session() as session, session.begin():
            run = await self._scope_run(session, frozen)
            return receipts.find(run, key)

    async def _write_stage_checkpoint(self, frozen, key, value, expected=None):
        """Append a bounded proof in the actual phase, never regress a Run."""
        if self.read_only_resume:
            _blocked("readonly_resume_cannot_mutate")
        async with self._session() as session, session.begin():
            run = await self._scope_run(session, frozen)
            actual = receipts.find(run, key)
            if actual == value:
                return True
            if run.phase == "completed":
                return False
            if actual != expected:
                _blocked("stage_checkpoint_changed")
            await self.runs.acheckpoint(
                session,
                **self._identity(frozen),
                expected_phase=run.phase,
                checkpoint_key=key,
                expected_checkpoint=expected,
                checkpoint=value,
            )
        return True

    async def _external_effect(self, *, kind, identity, effect):
        if self.read_only_resume:
            _blocked("readonly_resume_cannot_mutate")
        ticket = (
            await self.external_guard.begin(kind=kind, identity=identity) if self.external_guard is not None else None
        )
        try:
            result = await effect()
        except BaseException:
            if self.external_guard is not None:
                try:
                    await self.external_guard.finish(ticket, outcome="unknown", receipt=None)
                except BaseException as cleanup_error:
                    logger.warning(
                        "F118 maintenance reason=external_unknown_receipt_output_failed error_type={}",
                        type(cleanup_error).__name__,
                    )
            raise
        if self.external_guard is not None:
            from bisheng.knowledge.domain.services.unification_fingerprints import digest

            await self.external_guard.finish(ticket, outcome="acknowledged", receipt=digest(identity))
        return result

    async def _publish_result_tail(self, frozen):
        tail = await self._read_stage_checkpoint(frozen, "sql_results_v1")
        if tail is None:
            return None, None
        from bisheng.core.context.tenant import get_current_tenant_id

        body, _, _ = receipts.result_body(tail, frozen, get_current_tenant_id())
        # This is outside a SQL transaction and only reads the acknowledged Run.
        return tail, await receipts.put_record(self.store, frozen, body)

    async def _result_context(self, frozen):
        tail, previous = await self._publish_result_tail(frozen)
        return {
            "expected_tail": tail,
            "predecessor": previous,
            "directory": self._sql_directory,
            "sequence": receipts.payload(tail)["sequence"] + 1 if tail is not None else 0,
        }

    async def _prepare_sql_directory(self, frozen, members, totals, deferred, retained, structural, inputs):
        def rows():
            yield {
                "section": "metadata",
                "compiler_contract": "f118-sql-results-v1",
                "tenant_ids": list(frozen.tenant_ids),
                "inputs": inputs,
                "totals": {str(k): v for k, v in totals.items()},
                "deferred": {str(k): v for k, v in deferred.items()},
            }
            for tenant, pages in members.items():
                for page in pages:
                    yield {"section": "member", "tenant_id": tenant, "value": asdict(page)}
            for tenant, values in retained.items():
                for value in values:
                    yield {"section": "retained", "tenant_id": tenant, "value": list(value)}
            for tenant, values in structural.items():
                for value in values:
                    yield {"section": "structural", "tenant_id": tenant, "value": value}

        return await receipts.put_directory(self.store, frozen, purpose="sql-directory-v1", records=rows())

    async def _load_sql_directory(self, frozen, ref, inputs):
        metadata, retained, structural = None, {}, {}
        async for row in receipts.iter_directory(self.store, frozen, ref, purpose="sql-directory-v1"):
            section = row.get("section")
            if section == "metadata":
                if (
                    metadata is not None
                    or row.get("compiler_contract") != "f118-sql-results-v1"
                    or row["tenant_ids"] != list(frozen.tenant_ids)
                    or row["inputs"] != inputs
                ):
                    _blocked("sql_directory_binding")
                metadata = row
            elif section in {"retained", "structural"}:
                tenant = row["tenant_id"]
                if tenant not in frozen.tenant_ids:
                    _blocked("sql_directory_tenant")
                (retained if section == "retained" else structural).setdefault(tenant, []).append(
                    tuple(row["value"]) if section == "retained" else row["value"]
                )
            elif section != "member":
                _blocked("sql_directory_section")
        if metadata is None:
            _blocked("sql_directory_metadata")
        return metadata, retained, structural

    async def _material_inputs(self, frozen, inputs):
        """Omitted legacy assertions resolve to the exact original frozen values."""
        content = await self.store.aload_canonical(frozen.plan_ref, run_id=frozen.run_id, kind="plan")
        page = decode_inventory_page(
            content, run_id=frozen.run_id, section="manifest", scope="global", tenant_id=None, page_index=0, kind="plan"
        )
        records = [row.data for row in page.records if row.record_type == "run"]
        if len(records) != 1:
            _blocked("material_metadata")
        original = {name: records[0][name] for name in ("environment", "backup_ref", "schema_ref")}
        if inputs["environment"] != original["environment"] or any(
            inputs[name] is not None and inputs[name] != original[name] for name in ("backup_ref", "schema_ref")
        ):
            _blocked("material_assertion_changed")
        return original

    async def _verify_result_tenant(self, frozen, tenant, goal, head):
        ordinal, continuation, last = 0, None, None
        report_progress(
            "sql_verify", tenant_id=tenant, processed=0, total=goal.processed_count, unit="command", waiting="database"
        )
        async for body, commands, outcomes in receipts.iter_results(self.store, frozen, tenant, head):
            if body["start"] != ordinal:
                _blocked("sql_result_ordinal")
            # A final empty EOF marker only changes complete, never the fold.
            if commands or ordinal == 0:
                continuation = await self._verify(
                    frozen, commands, ordinal, goal, continuation, ordinal + len(commands) == goal.processed_count
                )
                if tuple(asdict(value) for value in continuation.outcomes) != tuple(
                    asdict(value) for value in outcomes
                ):
                    _blocked("sql_result_after_changed")
            ordinal += len(commands)
            last = body
            report_progress(
                "sql_verify",
                tenant_id=tenant,
                processed=ordinal,
                total=goal.processed_count,
                unit="command",
                verified=ordinal,
                cursor=goal.cursor,
            )
        if (
            last is None
            or last["sql_checkpoint"] != asdict(goal)
            or ordinal != goal.processed_count
            or continuation is None
            or not continuation.verification_complete
        ):
            _blocked("sql_results_incomplete")
        return last

    async def _admit_sql_completed(self, frozen, inputs, *, verify_current=True):
        inputs = await self._material_inputs(frozen, inputs)
        values, shared_directory = [], None
        # Decide global completeness before consuming any tenant's result pages.
        for tenant in frozen.tenant_ids:
            with tenant_execution_scope(tenant):
                goal = await self._status(frozen)
                if goal is None or not goal.complete:
                    return None
        for tenant in frozen.tenant_ids:
            with tenant_execution_scope(tenant):
                goal = await self._status(frozen)
                if goal is None or not goal.complete:
                    return None
                admission = await self._read_stage_checkpoint(frozen, "sql_admission_v1")
                if admission is not None:
                    admitted = receipts.payload(admission)
                    if (
                        set(admitted)
                        != {
                            "schema_version",
                            "compiler_contract",
                            "stage",
                            "identity",
                            "tenants",
                            "directory",
                            "results",
                            "sql_checkpoint",
                        }
                        or admitted["schema_version"] != 1
                        or admitted["compiler_contract"] != "f118-sql-admission-v1"
                        or admitted["stage"] != "sql"
                        or admitted["identity"] != receipts.identity(frozen, tenant)
                        or admitted["tenants"] != list(frozen.tenant_ids)
                        or admitted["sql_checkpoint"] != asdict(goal)
                        or admission != receipts.checkpoint(admitted, goal.processed_count)
                    ):
                        _blocked("sql_admission_binding")
                    head, directory = admitted["results"], admitted["directory"]
                else:
                    tail, head = await self._publish_result_tail(frozen)
                    if tail is None:
                        return None
                    directory = receipts.payload(tail)["directory"]
                if verify_current:
                    last = await self._verify_result_tenant(frozen, tenant, goal, head)
                else:
                    last = None
                    async for body, _, _ in receipts.iter_results(self.store, frozen, tenant, head):
                        last = body
                    if last is None or last["sql_checkpoint"] != asdict(goal):
                        _blocked("sql_results_incomplete")
                if last["directory"] != directory or (shared_directory is not None and shared_directory != directory):
                    _blocked("sql_admission_directory_changed")
                shared_directory = directory
                values.append((tenant, goal, head, admission))
        metadata, retained, structural = await self._load_sql_directory(frozen, shared_directory, inputs)
        await self._verify_retained_indexes(frozen, retained)
        await self._verify_structural_retentions(frozen, structural, environment=inputs["environment"])
        progress = []
        for tenant, goal, head, admission in values:
            count, deferred = metadata["totals"][str(tenant)], metadata["deferred"][str(tenant)]
            if goal.processed_count != count:
                _blocked("sql_admission_count")
            if admission is None:
                value = receipts.checkpoint(
                    {
                        "schema_version": 1,
                        "compiler_contract": "f118-sql-admission-v1",
                        "stage": "sql",
                        "identity": receipts.identity(frozen, tenant),
                        "tenants": list(frozen.tenant_ids),
                        "directory": shared_directory,
                        "results": head,
                        "sql_checkpoint": asdict(goal),
                    },
                    count,
                )
                with tenant_execution_scope(tenant):
                    await self._write_stage_checkpoint(frozen, "sql_admission_v1", value)
            progress.append(TenantSQLConversionProgress(tenant, count, deferred, goal))
        return SQLConversionExecutionReport(
            frozen.run_id,
            frozen.writer_contract_version,
            frozen.baseline_ref["sha256"],
            frozen.plan_ref["sha256"],
            frozen.tenant_ids,
            tuple(progress),
            True,
        )

    async def _admit(self, run_id, writer):
        async with self._session() as session, session.begin():
            from bisheng.knowledge.domain.repositories.unification_task_repository import UnificationTaskRepository

            await UnificationTaskRepository().avalidate_migration_idle(session)
            tenants = await self.runs.alist_actual_tenant_ids(session)
            read = self.runs.aget_global_freeze_readonly if self.read_only_resume else self.runs.aget_global_freeze
            frozen = await read(session, run_id=run_id, writer_contract_version=writer, tenant_ids=tenants)
            if frozen is None:
                _blocked("actual_frozen_run_required")
            for tenant in tenants:
                with tenant_execution_scope(tenant):
                    await self._scope_run(session, frozen)
            return frozen

    async def _plan(self, frozen, *, environment, backup_ref, schema_ref):
        members = {tenant: [] for tenant in frozen.tenant_ids}
        totals, deferred = dict.fromkeys(frozen.tenant_ids, 0), dict.fromkeys(frozen.tenant_ids, 0)
        physical, retained = {}, {tenant: [] for tenant in frozen.tenant_ids}
        structural = {tenant: [] for tenant in frozen.tenant_ids}
        pages_read = 0
        report_progress("sql_plan", unit="page", waiting="decode")
        # Exhaust the entire verified graph, including late non-SQL leaves and
        # original frozen metadata, before opening any business-write transaction.
        async for page in self.reader.aiter_frozen_pages(
            frozen, environment=environment, backup_ref=backup_ref, schema_ref=schema_ref
        ):
            pages_read += 1
            report_progress("sql_plan", tenant_id=page.tenant_id, processed=pages_read, unit="page", waiting="decode")
            if page.kind == "plan" and page.section == "control":
                from bisheng.knowledge.application.unification_structural_retention import RETENTIONS

                decoded = decode_inventory_page(
                    page.content,
                    run_id=frozen.run_id,
                    section=page.section,
                    scope=page.scope,
                    tenant_id=page.tenant_id,
                    page_index=page.page_index,
                    kind=page.kind,
                )
                structural[page.tenant_id].extend(
                    record.data for record in decoded.records if record.record_type in RETENTIONS
                )
            if page.section == "physical":
                decoded = decode_inventory_page(
                    page.content,
                    run_id=frozen.run_id,
                    section=page.section,
                    scope=page.scope,
                    tenant_id=page.tenant_id,
                    page_index=page.page_index,
                    kind=page.kind,
                )
                for record in decoded.records:
                    value = record.data
                    key = (page.tenant_id, value["space_id"])
                    if record.record_type == "physical_index":
                        physical[key] = (value["space_id"], value["index_name"], value["collection_name"])
                    elif record.record_type == "physical_index_retention":
                        retained[page.tenant_id].append(key)
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
        return (
            members,
            totals,
            deferred,
            {tenant: tuple(physical[key] for key in keys) for tenant, keys in retained.items() if keys},
            {tenant: tuple(values) for tenant, values in structural.items() if values},
        )

    async def _verify_retained_indexes(self, frozen, retained):
        # Check all tenants before the first business write, including resume.
        for tenant, bindings in retained.items():
            with tenant_execution_scope(tenant):
                async with self._session() as session, session.begin():
                    await self._scope_run(session, frozen)
                    await UnificationResourceRepository().avalidate_retained_index_bindings(session, bindings=bindings)

    async def _verify_structural_retentions(self, frozen, structural, *, environment):
        if not structural:
            return
        from bisheng.common.services.config_service import settings
        from bisheng.knowledge.application.unification_structural_retention import validate_native_retentions
        from bisheng.knowledge.domain.repositories.unification_control_repository import UnificationControlRepository
        from bisheng.permission.application.migration_read import PinnedMigrationPermissionReader
        from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
            PermissionMigrationSnapshotRepository,
        )

        permissions = PermissionMigrationSnapshotRepository()
        factory = self.structural_reader_factory or (
            lambda catalog: PinnedMigrationPermissionReader(settings.openfga, catalog)
        )
        historical_files = set()
        historical_catalog = None
        for tenant, proofs in structural.items():
            with tenant_execution_scope(tenant):
                async with self._session() as session, session.begin():
                    await self._scope_run(session, frozen)
                    catalog = await permissions.aload_catalog_baseline(session, environment=environment)
                    await validate_native_retentions(
                        session,
                        proofs,
                        resources=UnificationResourceRepository(),
                        controls=UnificationControlRepository(),
                        permissions=permissions,
                    )
                rootless = {
                    p["file_id"]
                    for p in proofs
                    if p.get("reason") == "preserve_original_file_with_absent_knowledge_parent"
                }
                historical_files.update(rootless)
                if rootless:
                    if historical_catalog is not None and historical_catalog != catalog:
                        _blocked("structural_permission_pin_changed")
                    historical_catalog = catalog
                files = tuple(sorted({p["file_id"] for p in proofs if "file_id" in p} - rootless))
                if not files:
                    continue
                # External I/O never holds an M3 native SQL Session open.
                async with factory(catalog) as reader:
                    for offset in range(0, len(files), 199):
                        await reader.aassert_no_file_objects(tenant, file_ids=files[offset : offset + 199])
                async with self._session() as session, session.begin():
                    await self._scope_run(session, frozen)
                    current = await permissions.aload_catalog_baseline(session, environment=environment)
                    if current != catalog:
                        _blocked("structural_permission_pin_changed")
                    await validate_native_retentions(
                        session,
                        proofs,
                        resources=UnificationResourceRepository(),
                        controls=UnificationControlRepository(),
                        permissions=permissions,
                    )

        if historical_files:
            # One complete Store read for the entire retained set, with no
            # native SQL session held across external I/O.
            async with factory(historical_catalog) as reader:
                await reader.aassert_no_historical_file_objects(file_ids=tuple(sorted(historical_files)))
            for tenant, proofs in structural.items():
                with tenant_execution_scope(tenant):
                    async with self._session() as session, session.begin():
                        await self._scope_run(session, frozen)
                        current = await permissions.aload_catalog_baseline(session, environment=environment)
                        if current != historical_catalog:
                            _blocked("structural_permission_pin_changed")
                        await validate_native_retentions(
                            session,
                            proofs,
                            resources=UnificationResourceRepository(),
                            controls=UnificationControlRepository(),
                            permissions=permissions,
                        )

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
        report_progress(
            "sql",
            tenant_id=state.get("tenant_id"),
            processed=ordinal,
            total=state.get("total"),
            unit="command",
            committed=ordinal,
            waiting="minio" if self._results_enabled else "database",
        )
        results_context = await self._result_context(frozen) if self._results_enabled else None
        async with self._session() as session:
            await session.begin()
            try:
                run = await self._scope_run(session, frozen)
                if not state.get("_migration_idle_checked"):
                    from bisheng.knowledge.domain.repositories.unification_task_repository import (
                        UnificationTaskRepository,
                    )

                    await UnificationTaskRepository().avalidate_migration_idle(session)
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
                    results_context=results_context,
                )
                result = await self.sql.aapply_batch(session, batch=batch)
                state["stage"] = "commit"
                report_progress(
                    "sql",
                    tenant_id=state.get("tenant_id"),
                    processed=ordinal + len(commands),
                    total=state.get("total"),
                    unit="command",
                    committed=ordinal,
                    waiting="transaction_commit",
                )
                await session.commit()
            except BaseException:
                try:
                    if session.in_transaction():
                        await session.rollback()
                except Exception as cleanup_error:
                    # The primary failure remains authoritative, including an
                    # unknown COMMIT result. Cleanup cannot prove non-commit.
                    logger.warning(
                        "F118 maintenance reason=sql_rollback_failed error_type={}", type(cleanup_error).__name__
                    )
                raise
        # A receipt becomes a cross-session continuation ONLY after commit ACK.
        state["last_acknowledged_progress"] = asdict(result.progress)
        state["_migration_idle_checked"] = True
        state["stage"] = "apply"
        report_progress(
            "sql",
            tenant_id=state.get("tenant_id"),
            processed=result.progress.processed_count,
            total=state.get("total"),
            unit="command",
            committed=result.progress.processed_count,
            cursor=result.progress.cursor,
            commit_outcome="acknowledged",
        )
        return result

    async def _tenant(self, frozen, tenant, members, total, deferred, state):
        state.update(tenant_id=tenant, total=total, stage="read_progress", last_acknowledged_progress=None)
        goal = await self._status(frozen)
        if goal is not None and (goal.processed_count > total or (goal.complete and goal.processed_count != total)):
            _blocked("checkpoint_outside_plan")
        if self._results_enabled and goal is not None and goal.complete:
            tail, head = await self._publish_result_tail(frozen)
            if tail is not None:
                await self._verify_result_tenant(frozen, tenant, goal, head)
                state["last_acknowledged_progress"] = asdict(goal)
                return TenantSQLConversionProgress(tenant, total, deferred, goal)
        ordinal, continuation, current = 0, None, goal
        legacy_tail, legacy_head, legacy_sequence = None, None, 0
        materialize_legacy = (
            self._results_enabled
            and goal is not None
            and await self._read_stage_checkpoint(frozen, "sql_results_v1") is None
        )

        async def legacy_result(commands, before, result, start):
            nonlocal legacy_tail, legacy_head, legacy_sequence
            batch = SimpleNamespace(
                **self._identity(frozen),
                tenant_id=tenant,
                commands=commands,
                ordinal=start,
                results_context={
                    "directory": self._sql_directory,
                    "predecessor": legacy_head,
                    "sequence": legacy_sequence,
                },
            )
            legacy_tail = result_checkpoint(batch, before, result.progress, result.outcomes)
            legacy_head = await receipts.put_record(self.store, frozen, receipts.payload(legacy_tail))
            legacy_sequence += 1
            if result.verification_complete:
                await self._write_stage_checkpoint(frozen, "sql_results_v1", legacy_tail)

        if goal is not None and goal.processed_count == 0:
            state["stage"] = "verify_prefix"
            continuation = await self._verify(frozen, (), 0, goal, None, True)
            if materialize_legacy:
                seed = SQLConversionProgress(
                    None, 0, self.sql._seed(SimpleNamespace(**self._identity(frozen), tenant_id=tenant)), False
                )
                await legacy_result((), seed, continuation, 0)
            state["last_acknowledged_progress"] = asdict(goal)
        for member in members:
            state["stage"] = "read_page"
            commands = await self._page(frozen, member)
            take = min(len(commands), max(0, goal.processed_count - ordinal)) if goal else 0
            if take:
                state["stage"] = "verify_prefix"
                before = (
                    continuation.progress
                    if continuation is not None
                    else SQLConversionProgress(
                        None, 0, self.sql._seed(SimpleNamespace(**self._identity(frozen), tenant_id=tenant)), False
                    )
                )
                continuation = await self._verify(
                    frozen, commands[:take], ordinal, goal, continuation, ordinal + take == goal.processed_count
                )
                if materialize_legacy:
                    await legacy_result(commands[:take], before, continuation, ordinal)
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

    async def apreview_resume(self, *, frozen, inputs, operator_id=None):
        """Reconcile a frozen continuation using reads, never effect rollback.

        The preview uses a distinct unguarded application: acquiring an executor
        attempt is an apply operation. No admission/result object is produced.
        """
        from bisheng.knowledge.application.unification_permissions import PermissionPublicationApplication

        if self.transaction_guard is not None or self.external_guard is not None:
            _blocked("preview_requires_readonly_application")
        checks = {"sql_resume": "not_evaluated", "permission_resume": "not_evaluated"}
        diagnostics, progress = [], []

        def failed(stage, error):
            reason = (
                error.kwargs.get("reason", type(error).__name__)
                if isinstance(error, BaseErrorCode)
                else type(error).__name__
            )
            checks[stage] = "blocked"
            diagnostics.append({"stage": stage, "classification": "blocked", "reason": reason})

        with self.store.verified_reads():
            try:
                if await self._admit(frozen.run_id, frozen.writer_contract_version) != frozen:
                    _blocked("preview_frozen_changed")
                inputs = await self._material_inputs(frozen, inputs)
                members, totals, deferred, retained, structural = await self._plan(frozen, **inputs)
                await self._verify_retained_indexes(frozen, retained)
                await self._verify_structural_retentions(frozen, structural, environment=inputs["environment"])
                for tenant in frozen.tenant_ids:
                    with tenant_execution_scope(tenant):
                        goal = await self._status(frozen)
                        count = goal.processed_count if goal is not None else 0
                        if count > totals[tenant] or (goal is not None and goal.complete and count != totals[tenant]):
                            _blocked("checkpoint_outside_plan")
                        ordinal, continuation = 0, None
                        if goal is not None and count == 0:
                            continuation = await self._verify(frozen, (), 0, goal, None, True)
                        for member in members[tenant]:
                            commands = await self._page(frozen, member)
                            take = min(len(commands), max(0, count - ordinal))
                            if take:
                                continuation = await self._verify(
                                    frozen, commands[:take], ordinal, goal, continuation, ordinal + take == count
                                )
                            if commands[take:]:
                                async with self._session() as session, session.begin():
                                    await self._scope_run(session, frozen)
                                    await self.sql.repository.apreview_before(
                                        session, **self._identity(frozen), commands=commands[take:]
                                    )
                            ordinal += len(commands)
                        if ordinal != totals[tenant] or (
                            count and (continuation is None or not continuation.verification_complete)
                        ):
                            _blocked("preview_sql_prefix_incomplete")
                        progress.append(
                            {
                                "tenant_id": tenant,
                                "processed": count,
                                "total": totals[tenant],
                                "deferred": deferred[tenant],
                                "complete": bool(goal and goal.complete),
                            }
                        )
                checks["sql_resume"] = "passed"
            except BaseErrorCode as error:
                failed("sql_resume", error)
            except Exception as error:
                logger.warning("F118 maintenance reason=sql_preview_incomplete error_type={}", type(error).__name__)
                failed("sql_resume", error)
            try:
                permission = await PermissionPublicationApplication(self).apreview(
                    frozen=frozen, inputs=inputs, operator_id=operator_id
                )
                checks["permission_resume"] = "passed" if permission["complete"] else "not_evaluated"
                diagnostics.extend(permission["diagnostics"])
            except BaseErrorCode as error:
                failed("permission_resume", error)
            except Exception as error:
                logger.warning(
                    "F118 maintenance reason=permission_preview_incomplete error_type={}", type(error).__name__
                )
                failed("permission_resume", error)
            if not diagnostics and await self._admit(frozen.run_id, frozen.writer_contract_version) != frozen:
                _blocked("preview_final_universe_changed")
        return {
            "complete": all(value == "passed" for value in checks.values()) and not diagnostics,
            "checks": checks,
            "diagnostics": diagnostics,
            "sql": progress,
        }

    async def arun_references(
        self,
        *,
        run_id,
        writer_contract_version,
        environment,
        backup_ref,
        schema_ref,
        operator_id,
        reuse_completed=False,
        reconciliation_ref=None,
        semantic_projection_ref=None,
    ):
        if self.read_only_resume:
            _blocked("readonly_resume_cannot_mutate")
        from bisheng.knowledge.application.unification_references import run_references

        return await run_references(
            self,
            run_id=run_id,
            writer_contract_version=writer_contract_version,
            environment=environment,
            backup_ref=backup_ref,
            schema_ref=schema_ref,
            operator_id=operator_id,
            reuse_completed=reuse_completed,
            reconciliation_ref=reconciliation_ref,
            semantic_projection_ref=semantic_projection_ref,
        )

    async def arun_permissions(
        self,
        *,
        run_id,
        writer_contract_version,
        environment,
        backup_ref,
        schema_ref,
        operator_id,
        reuse_completed=False,
    ):
        if self.read_only_resume:
            _blocked("readonly_resume_cannot_mutate")
        from bisheng.knowledge.application.unification_permissions import run_permissions

        return await run_permissions(
            self,
            run_id=run_id,
            writer_contract_version=writer_contract_version,
            environment=environment,
            backup_ref=backup_ref,
            schema_ref=schema_ref,
            operator_id=operator_id,
            reuse_completed=reuse_completed,
        )

    async def arun(
        self, *, run_id, writer_contract_version, environment, backup_ref, schema_ref, reuse_completed=False
    ):
        if self.read_only_resume:
            _blocked("readonly_resume_cannot_mutate")
        with (
            self.store.verified_reads() if reuse_completed or self.store.verified_inputs is not None else nullcontext()
        ):
            self._results_enabled = reuse_completed
            return await self._arun(
                run_id=run_id,
                writer_contract_version=writer_contract_version,
                environment=environment,
                backup_ref=backup_ref,
                schema_ref=schema_ref,
                reuse_completed=reuse_completed,
            )

    async def _arun(self, *, run_id, writer_contract_version, environment, backup_ref, schema_ref, reuse_completed):
        state = {"run_id": None, "tenant_id": None, "stage": "read_frozen", "last_acknowledged_progress": None}
        try:
            self.runs._identity(run_id, writer_contract_version)
            state["run_id"] = run_id
            frozen = await self._admit(run_id, writer_contract_version)
            from bisheng.knowledge.application import unification_identity_retention as identity_retention

            retained_metadata = await identity_retention.load_metadata(self.store, frozen)
            if retained_metadata:
                with tenant_execution_scope(1):
                    async with self._session() as session, session.begin():
                        await self._scope_run(session, frozen)
                        await identity_retention.validate(session, expected=retained_metadata)
            inputs = {"environment": environment, "backup_ref": backup_ref, "schema_ref": schema_ref}
            if reuse_completed:
                completed = await self._admit_sql_completed(frozen, inputs)
                if completed is not None:
                    return completed
                terminal = True
                for tenant in frozen.tenant_ids:
                    with tenant_execution_scope(tenant):
                        async with self._session() as session, session.begin():
                            terminal = terminal and (await self._scope_run(session, frozen)).phase == "completed"
                if terminal:
                    # Legacy completed Runs have no place for new checkpoints.
                    # Keep their audit fully read-only, including object storage.
                    reuse_completed = self._results_enabled = False
            members, totals, deferred, retained, structural = await self._plan(
                frozen, environment=environment, backup_ref=backup_ref, schema_ref=schema_ref
            )
            if reuse_completed:
                self._sql_directory = await self._prepare_sql_directory(
                    frozen, members, totals, deferred, retained, structural, await self._material_inputs(frozen, inputs)
                )
            await self._verify_retained_indexes(frozen, retained)
            await self._verify_structural_retentions(frozen, structural, environment=environment)
            result = []
            for tenant in frozen.tenant_ids:
                with tenant_execution_scope(tenant):
                    result.append(
                        await self._tenant(frozen, tenant, members[tenant], totals[tenant], deferred[tenant], state)
                    )
            state["stage"] = "verify_universe"
            if await self._admit(run_id, writer_contract_version) != frozen:
                _blocked("frozen_universe_changed")
            if reuse_completed:
                await self._admit_sql_completed(frozen, inputs, verify_current=False)
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
            report_progress(
                "sql",
                tenant_id=state.get("tenant_id"),
                unit="command",
                status="cancelled",
                commit_outcome="unknown" if state["stage"] == "commit" else "not_attempted",
            )
            error.sql_conversion_report = {
                key: value for key, value in state.items() if key != "_migration_idle_checked"
            } | {"commit_outcome": "unknown" if state["stage"] == "commit" else "not_attempted"}
            raise
        except Exception as error:
            report_progress(
                "sql",
                tenant_id=state.get("tenant_id"),
                unit="command",
                status="failed",
                commit_outcome="unknown" if state["stage"] == "commit" else "not_attempted",
            )
            report = {key: value for key, value in state.items() if key != "_migration_idle_checked"} | {
                "commit_outcome": "unknown" if state["stage"] == "commit" else "not_attempted"
            }
            if isinstance(error, BaseErrorCode):
                error.kwargs["sql_conversion_report"] = report
                raise
            raise ReferenceCoverageNotReadyError(
                reason="migration_sql_conversion_failed", sql_conversion_report=report
            ) from error
