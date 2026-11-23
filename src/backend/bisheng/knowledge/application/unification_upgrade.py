"""One F118 maintenance preview/apply, using native owners and immutable evidence."""

import re
import shlex
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime

from loguru import logger

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application.unification_conversion import UnificationSQLConversionApplication
from bisheng.knowledge.application.unification_inventory import UnificationInventoryApplication
from bisheng.knowledge.application.unification_progress import report_progress
from bisheng.knowledge.application.unification_reference_plan import UnificationReferencePlanReader
from bisheng.knowledge.application.unification_upgrade_executor import UpgradeExecutor
from bisheng.knowledge.application.unification_upgrade_materials import canonical, envelope
from bisheng.knowledge.domain.models.knowledge_unification_run import unification_now
from bisheng.knowledge.domain.repositories.unification_upgrade_repository import UpgradeRunRepository
from bisheng.permission.application.migration_history import discover_migration_environment

_CONTRACT = "f118-upgrade-v1"
_FIELDS = {
    "schema_version",
    "flow_contract",
    "kind",
    "run_id",
    "writer_contract_version",
    "environment",
    "database_fingerprint",
    "schema_digest",
    "tenant_ids",
    "planned_at",
    "operator_binding",
    "history_ref",
    "history_semantics_ref",
    "semantic_projection_ref",
    "reconciliation_ref",
    "baseline_ref",
    "plan_ref",
    "checks",
    "ready",
    "history_summary",
}
_CHECKS = {"history", "inventory", "permission_graph", "reference_sources"}
_SUMMARY_FIELDS = {"auto_repair", "retained_warning", "counts_scope", "actions"}
_ACTION_FIELDS = {
    "levels",
    "parents",
    "purges",
    "initializations",
    "recoveries",
    "empty_root_initializations",
    "builtin_finalizations",
    "delete_closures",
    "business_updates",
    "business_deletes",
}


def _reject(reason):
    raise KnowledgeOperationPlanConflictError(reason="migration_upgrade_" + reason)


@asynccontextmanager
async def _history_runtime(runtime):
    factory = getattr(runtime, "history", None)
    if factory is None:
        yield runtime
    else:
        async with factory() as owned:
            yield owned


def _flow(value, *, run_id, writer_contract_version):
    if (
        type(value) is not dict
        or set(value) != _FIELDS
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["flow_contract"] != _CONTRACT
        or value["kind"] not in {"new_run", "frozen_resume"}
        or value["run_id"] != run_id
        or value["writer_contract_version"] != writer_contract_version
        or value["ready"] is not True
        or type(value["checks"]) is not dict
        or set(value["checks"]) != _CHECKS
        or any(value["checks"][name] != "passed" for name in _CHECKS)
        or type(value["operator_binding"]) is not dict
        or set(value["operator_binding"]) != {"mode", "operator_id"}
        or value["operator_binding"]["mode"] not in {"apply_time", "fixed"}
        or (value["operator_binding"]["mode"] == "apply_time" and value["operator_binding"]["operator_id"] is not None)
        or (
            value["operator_binding"]["mode"] == "fixed"
            and (
                type(value["operator_binding"]["operator_id"]) is not int
                or value["operator_binding"]["operator_id"] <= 0
            )
        )
    ):
        _reject("flow_invalid_or_incomplete")
    summary = value["history_summary"]
    if (
        type(summary) is not dict
        or set(summary) != _SUMMARY_FIELDS
        or any(type(summary[name]) is not int or summary[name] < 0 for name in ("auto_repair", "retained_warning"))
        or summary["counts_scope"] not in {"original_history_plan", "history_actions_in_this_command"}
        or type(summary["actions"]) is not dict
        or set(summary["actions"]) - _ACTION_FIELDS
        or any(type(count) is not int or count < 0 for count in summary["actions"].values())
        or summary["auto_repair"] != sum(summary["actions"].values())
        or (
            summary["counts_scope"] == "history_actions_in_this_command"
            and (summary["actions"] or summary["auto_repair"] or summary["retained_warning"])
        )
    ):
        _reject("history_summary_invalid")
    return value


async def _read_record(store, ref, *, run_id, kind):
    from bisheng.knowledge.application.unification_history_materials import aload_history_record

    return await aload_history_record(store, ref, run_id=run_id, kind=kind)


class UnificationUpgradeApplication:
    def __init__(self, runtime, materials):
        self.runtime, self.materials = runtime, materials
        self.repository = UpgradeRunRepository()
        self.stages = dict.fromkeys(("history", "inventory", "sql", "permissions", "references"), "not_evaluated")
        self.private_backup_path = None
        self.history_summary = None

    @staticmethod
    def _history_summary(plan):
        actions = {
            name: len(plan.get(name, ()))
            for name in (
                "levels",
                "parents",
                "purges",
                "initializations",
                "recoveries",
                "empty_root_initializations",
                "builtin_finalizations",
                "delete_closures",
            )
        }
        actions.update(
            {"business_" + name: len(plan.get("business", {}).get(name, ())) for name in ("updates", "deletes")}
        )
        return {
            "auto_repair": sum(actions.values()),
            "retained_warning": len(plan.get("business", {}).get("warnings", ()))
            + len(plan.get("permission_delete_retained", ())),
            "counts_scope": "original_history_plan",
            "actions": actions,
        }

    async def _state(self, identity):
        with tenant_execution_scope(1):
            async with self.runtime.sessions() as session, session.begin():
                return await self.repository.aload_state(session, **identity)

    async def _environment(self, environment, *, state=None, backup_ref=None, schema_ref=None):
        with tenant_execution_scope(1):
            async with self.runtime.sessions() as session, session.begin():
                connection = await self.repository.aconnection_identity(session)
                if state is None or state.frozen is None:
                    if backup_ref is not None or schema_ref is not None:
                        raise KnowledgeOperationPlanConflictError(
                            reason="migration_cli_legacy_descriptors_require_frozen_run"
                        )
                    actual = await discover_migration_environment(session, environment)
                else:
                    from bisheng.knowledge.application.unification_inventory_codec import decode_inventory_page

                    content = await self.runtime.store.aload_canonical(
                        state.frozen.plan_ref, run_id=state.frozen.run_id, kind="plan"
                    )
                    page = decode_inventory_page(
                        content,
                        run_id=state.frozen.run_id,
                        section="manifest",
                        scope="global",
                        tenant_id=None,
                        page_index=0,
                        kind="plan",
                    )
                    records = [record.data for record in page.records if record.record_type == "run"]
                    if len(records) != 1 or (environment is not None and environment != records[0]["environment"]):
                        _reject("environment_assertion_changed")
                    if any(
                        value is not None and records[0][name] != value
                        for name, value in (("backup_ref", backup_ref), ("schema_ref", schema_ref))
                    ):
                        _reject("material_assertion_changed")
                    actual = records[0]["environment"]
                    # A native publishing checkpoint may legitimately fence
                    # CURRENT. The original frozen pin remains authoritative;
                    # resume preflight validates its before/staged/after state.
        return actual, connection

    async def _put(self, store, run_id, kind, record):
        from bisheng.knowledge.application.unification_history_materials import aput_history_record

        return await aput_history_record(store, run_id=run_id, kind=kind, record=record)

    async def _verify_actor(self, operator_id):
        from bisheng.knowledge.domain.repositories.unification_control_repository import UnificationControlRepository

        if type(operator_id) is not int or operator_id <= 0:
            _reject("positive_operator_required")
        with tenant_execution_scope(1):
            async with self.runtime.sessions() as session, session.begin():
                (actor,) = await UnificationControlRepository().ainspect_users(session, user_ids=(operator_id,))
        if not actor.exists or actor.delete != 0:
            _reject("operator_not_active")

    async def _source_semantics(self, store, candidate, *, environment, repository):
        from bisheng.knowledge.application.unification_reference_reconciliation import collect_semantics

        reader = UnificationReferencePlanReader(
            inventory=UnificationInventoryApplication(artifact_store=store), artifact_store=store
        )
        plan = await reader.aprepare(candidate, environment=environment, backup_ref=None, schema_ref=None)
        pages = []
        for tenant in candidate.tenant_ids:
            keys = tuple(
                entry.header.source_key for entry in plan.sources if entry.header.source_key.tenant_id == tenant
            )
            for offset in range(0, len(keys), 200):
                with tenant_execution_scope(tenant):
                    async with self.runtime.sessions() as session, session.begin():
                        manifest = await collect_semantics(
                            session, source_keys=keys[offset : offset + 200], repository=repository
                        )
                ref = await self._put(store, candidate.run_id, "verification", manifest)
                pages.append({"tenant_id": tenant, "source_count": len(manifest["sources"]), "ref": ref})
        if not pages:
            # A real empty source set still carries its actual tenant scope.
            tenant = candidate.tenant_ids[0]
            ref = await self._put(
                store,
                candidate.run_id,
                "verification",
                {
                    "schema_version": 1,
                    "semantic_contract": "f118-source-semantics-v1",
                    "tenant_id": tenant,
                    "sources": [],
                },
            )
            pages.append({"tenant_id": tenant, "source_count": 0, "ref": ref})
        while len(pages) > 1:
            parents = []
            for offset in range(0, len(pages), 128):
                group = pages[offset : offset + 128]
                ref = await self._put(
                    store,
                    candidate.run_id,
                    "verification",
                    {
                        "schema_version": 1,
                        "semantic_contract": "f118-source-semantics-directory-v1",
                        "pages": group,
                    },
                )
                parents.append(
                    {"tenant_id": None, "source_count": sum(item["source_count"] for item in group), "ref": ref}
                )
            pages = parents
        return pages[0]["ref"]

    async def _preview_new(
        self,
        *,
        identity,
        environment,
        planned_at,
        local_store,
        operator_id=None,
        replay_plan=None,
        expected_semantics=None,
    ):
        from bisheng.knowledge.application.unification_history import apreview_history

        report_progress("history", unit="action", waiting="planning")
        async with _history_runtime(self.runtime) as runtime:
            preview = await apreview_history(
                runtime,
                **identity,
                environment=environment,
                artifacts=self.materials,
                planned_at=planned_at,
                operator_id=operator_id,
                replay_plan=replay_plan,
                expected_semantics=expected_semantics,
            )
            try:
                self.private_backup_path = preview.private_backup_path
                self.history_summary = self._history_summary(preview.history_plan)
                if preview.diagnostics:
                    self.stages["history"] = "blocked"
                    return None, preview.diagnostics
                self.stages["history"] = "checked"
                self.stages["inventory"] = "checking"
                report_progress("inventory", unit="resource", waiting="planning")
                inventory = UnificationInventoryApplication(
                    artifact_store=local_store,
                    sharing_reader_factory=preview.reader_factory,
                    read_ports=preview.read_ports,
                )
                with tenant_execution_scope(1):
                    async with runtime.sessions() as session, session.begin():
                        candidate = await inventory.arun(
                            session,
                            **identity,
                            environment=environment,
                            freeze=False,
                            planned_at=planned_at,
                            retain_preview_artifacts=True,
                        )
                self.stages.update(inventory="checked", sql="checked", permissions="checked")
                self.stages["references"] = "checking"
                semantic = await self._source_semantics(
                    local_store, candidate, environment=environment, repository=preview.read_ports.inventory
                )
                replay = await self._put(local_store, identity["run_id"], "history_replay", preview.replay_plan)
                semantics = await self._put(local_store, identity["run_id"], "verification", preview.semantic_manifest)
                self.stages["references"] = "checked"
                return {
                    "history_ref": replay,
                    "history_semantics_ref": semantics,
                    "semantic_projection_ref": semantic,
                    "reconciliation_ref": None,
                    "baseline_ref": candidate.baseline_ref,
                    "plan_ref": candidate.plan_ref,
                    "tenant_ids": list(candidate.tenant_ids),
                    "history_summary": self._history_summary(preview.history_plan),
                }, []
            finally:
                await preview.aclose()

    async def _preview_frozen(self, *, identity, environment, state, local_store, prior_flow=None):
        from bisheng.knowledge.application.unification_reference_reconciliation import inspect_reference_reconciliation

        application = UnificationSQLConversionApplication(
            artifact_store=local_store, session_factory=self.runtime.sessions, read_only_resume=True
        )
        semantic = prior_flow.get("semantic_projection_ref") if prior_flow else None
        self.stages["history"] = "already_prepared"
        resume = await application.apreview_resume(
            frozen=state.frozen, inputs={"environment": environment, "backup_ref": None, "schema_ref": None}
        )
        self.stages.update(
            inventory="checked", sql=resume["checks"]["sql_resume"], permissions=resume["checks"]["permission_resume"]
        )
        self.stages["references"] = "checking"
        inspected = await inspect_reference_reconciliation(
            application, frozen=state.frozen, environment=environment, semantic_projection_ref=semantic
        )
        self.stages["references"] = "blocked" if inspected["diagnostics"] else "checked"
        diagnostics = [*resume["diagnostics"], *inspected["diagnostics"]]
        if not resume["complete"] or diagnostics:
            return None, diagnostics
        reconciliation = (
            await self._put(local_store, identity["run_id"], "verification", inspected["manifest"])
            if inspected["manifest"]
            else None
        )
        return {
            "history_ref": None,
            "history_semantics_ref": None,
            "semantic_projection_ref": semantic,
            "reconciliation_ref": reconciliation,
            "baseline_ref": state.frozen.baseline_ref,
            "plan_ref": state.frozen.plan_ref,
            "tenant_ids": list(state.tenant_ids),
            "history_summary": prior_flow["history_summary"]
            if prior_flow
            else {
                "auto_repair": 0,
                "retained_warning": 0,
                "counts_scope": "history_actions_in_this_command",
                "actions": {},
            },
        }, []

    async def preview(self, args):
        identity = {"run_id": args.run_id, "writer_contract_version": args.writer_contract_version}
        report_progress("scan", unit="tenant", waiting="database")
        state = await self._state(identity)
        if getattr(args, "verify", False) and not state.completed:
            _reject("verify_requires_completed")
        if args.resume and not state.phases:
            raise KnowledgeOperationPlanConflictError(reason="migration_cli_resume_requires_frozen_run")
        environment, connection = await self._environment(
            args.environment, state=state, backup_ref=args.backup_ref, schema_ref=args.schema_ref
        )
        actor = args.operator_id if args.operator_id else None
        if actor is not None:
            await self._verify_actor(actor)
        local = self.materials.local_store(self.runtime.store)
        diagnostics = []
        previous = self.materials.active(required=False)
        prior_flow = None
        if state.binding is not None:
            prior_flow = await _read_record(
                self.runtime.store, state.binding["flow_ref"], run_id=args.run_id, kind="upgrade_flow"
            )
        elif previous is not None:
            prior_flow = self.materials.read_object(previous, kind="upgrade_flow")["records"][0]
        if prior_flow is not None:
            prior_flow = _flow(prior_flow, **identity)
        planned_at = (
            datetime.fromisoformat(prior_flow["planned_at"])
            if prior_flow
            else (
                datetime.fromisoformat(state.created_at)
                if state.created_at
                else unification_now().replace(microsecond=0)
            )
        )
        try:
            with local.verified_reads():
                if state.pending_intents:
                    raise KnowledgeOperationPlanConflictError(reason="migration_executor_recovery_required")
                if state.preparing:
                    # Rebuild from the bound original shared recipe, never a
                    # fresh historical capture of partially modified data.
                    if state.binding is None or prior_flow is None:
                        _reject("preparing_original_flow_missing")
                    if actor is not None and actor != state.binding["operator_id"]:
                        _reject("operator_binding_changed")
                    replay = await _read_record(
                        self.runtime.store, prior_flow["history_ref"], run_id=args.run_id, kind="history_replay"
                    )
                    semantics = await _read_record(
                        self.runtime.store, prior_flow["history_semantics_ref"], run_id=args.run_id, kind="verification"
                    )
                    details, diagnostics = await self._preview_new(
                        identity=identity,
                        environment=environment,
                        planned_at=planned_at,
                        local_store=local,
                        operator_id=state.binding["operator_id"],
                        replay_plan=replay,
                        expected_semantics=semantics,
                    )
                    fields = (
                        "history_ref",
                        "history_semantics_ref",
                        "semantic_projection_ref",
                        "baseline_ref",
                        "plan_ref",
                        "tenant_ids",
                        "history_summary",
                    )
                    if details is not None and any(details[key] != prior_flow[key] for key in fields):
                        _reject("preparing_expected_after_changed")
                elif state.frozen is None:
                    details, diagnostics = await self._preview_new(
                        identity=identity,
                        environment=environment,
                        planned_at=planned_at,
                        local_store=local,
                        operator_id=actor,
                    )
                else:
                    details, diagnostics = await self._preview_frozen(
                        identity=identity,
                        environment=environment,
                        state=state,
                        local_store=local,
                        prior_flow=prior_flow,
                    )
        except BaseErrorCode as error:
            details = None
            reason = error.kwargs.get("reason", type(error).__name__)
            incomplete = any(
                marker in reason
                for marker in ("unavailable", "io_failed", "reader_required", "native_ports", "stream_required")
            )
            diagnostics.append({"reason": reason, "classification": "not_evaluated" if incomplete else "blocked"})
        for stage, status in self.stages.items():
            if status == "checking":
                self.stages[stage] = "blocked"
        summary = (
            details["history_summary"]
            if details
            else self.history_summary
            or {"auto_repair": 0, "retained_warning": 0, "counts_scope": "completed_checks_only", "actions": {}}
        )
        report = {
            "mode": "dry-run",
            **identity,
            "environment": environment,
            "tenant_ids": list(state.tenant_ids),
            "frozen": state.frozen is not None,
            "validation_scope": "frozen_resume" if state.frozen else "repaired_inventory",
            "preflight_complete": details is not None and not diagnostics,
            "can_apply": details is not None and not diagnostics,
            "ready": False,
            "diagnostics": diagnostics,
            "phases": dict(state.phases),
            "stages": dict(self.stages),
            **summary,
            "stage_status_scope": "preflight_checks",
            "blocker": sum(
                not item.get("not_evaluated") and item.get("classification") != "not_evaluated" for item in diagnostics
            ),
            "not_evaluated": sum(status == "not_evaluated" for status in self.stages.values()),
            "private_backup_path": self.private_backup_path,
        }
        if report["can_apply"]:
            flow = (
                prior_flow
                if state.preparing
                else {
                    "schema_version": 1,
                    "flow_contract": _CONTRACT,
                    "kind": "frozen_resume" if state.frozen else "new_run",
                    **identity,
                    "environment": environment,
                    **connection,
                    "planned_at": planned_at.isoformat(),
                    "operator_binding": {"mode": "fixed" if actor is not None else "apply_time", "operator_id": actor},
                    **details,
                    "checks": dict.fromkeys(sorted(_CHECKS), "passed"),
                    "ready": True,
                }
            )
            ref = self.materials.write_object("upgrade_flow", envelope(args.run_id, "upgrade_flow", [flow]))
            report["flow_ref"] = ref
        report["report_path"] = self.materials.write_report(report)
        if report["can_apply"]:
            # A report I/O failure cannot publish a newly executable candidate.
            self.materials.activate(ref)
        return report

    async def _completed(self, identity, state):
        from bisheng.knowledge.application.unification_coverage import production_coverage_factory
        from bisheng.knowledge.domain.repositories.unification_coverage_repository import UnificationCoverageRepository

        with tenant_execution_scope(1):
            async with self.runtime.sessions() as session, session.begin():
                ready = await production_coverage_factory(
                    session, writer_contract_version=identity["writer_contract_version"]
                ).arequire_global_ready()
                rows = await UnificationCoverageRepository().aload_runs(session)
        matching = [row for row in rows if row["run_id"] == identity["run_id"]]
        return {
            "mode": "apply",
            **identity,
            "ready": ready.verified_tenant_ids == state.tenant_ids,
            "complete": True,
            "tenant_ids": list(state.tenant_ids),
            "baseline_hash": state.frozen.baseline_ref["sha256"],
            "plan_hash": state.frozen.plan_ref["sha256"],
            "coverage_epoch": matching[0]["coverage_epoch"],
            "invalid_manifest_ref": state.frozen.plan_ref,
            "preflight_complete": True,
            "can_apply": True,
            "stages": dict.fromkeys(self.stages, "completed"),
            "stage_status_scope": "migration_execution",
            "blocker": 0,
            "not_evaluated": 0,
            "auto_repair": 0,
            "retained_warning": 0,
            "actions": {},
            "counts_scope": "history_actions_in_this_command",
            "source_proofs": {
                str(row["tenant_id"]): row["verification_report"]["reference_coverage"]["proofs"] for row in matching
            },
        }

    async def failure_report(self, args, error):
        reason = error.kwargs.get("reason") if isinstance(error, BaseErrorCode) else None
        reason = (
            reason
            if isinstance(reason, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", reason)
            else type(error).__name__
        )
        state = None
        try:
            state = await self._state({"run_id": args.run_id, "writer_contract_version": args.writer_contract_version})
        except Exception:
            logger.warning("F118 failure report cannot read the native Run; state remains unknown")
        command = ["python", "scripts/unify_knowledge_spaces.py", "--run-id", args.run_id, "--apply"]
        if args.operator_id > 0:
            command += ["--operator-id", str(args.operator_id)]
        command += ["--materials-dir", str(self.materials.root)]
        report = {
            "mode": "apply" if args.apply else "dry-run",
            "run_id": args.run_id,
            "preflight_complete": False,
            "can_apply": False,
            "ready": False,
            "reason": reason,
            "business_complete": state.completed if state is not None else None,
            "phases": dict(state.phases) if state is not None else None,
            "stages": dict(self.stages),
            "stage_status_scope": "preflight_checks",
            "commit_unknown": bool(state.pending_intents) or "commit_unknown" in reason if state is not None else None,
            "last_confirmed_positions": list(state.positions) if state is not None else None,
            "pending_intents": list(state.pending_intents) if state is not None else None,
            "resume_same_run": True,
            "resume_command": shlex.join(command),
            "blocker": 1,
            "not_evaluated": sum(value in {"checking", "not_evaluated"} for value in self.stages.values()),
        }
        if args.operator_id <= 0:
            report["resume_command"] += ' --operator-id "$UPGRADE_OPERATOR_ID"'
        try:
            report["report_path"] = self.materials.write_report(report)
        except OSError:
            report["report_path"], report["report_error"] = None, "output_failed"
            logger.warning("F118 failure report output failed; native Run remains authoritative")
        return report

    async def _select_flow(self, *, identity, environment, connection, state, operator_id):
        original = None
        if state.binding is not None:
            original = (
                state.binding["flow_ref"],
                await _read_record(
                    self.runtime.store, state.binding["flow_ref"], run_id=identity["run_id"], kind="upgrade_flow"
                ),
            )
        if state.reconciliation_refs:
            if len(state.reconciliation_refs) != 1:
                _reject("multiple_bound_reconciliations")
            ref = state.reconciliation_refs[0]
            return (
                ref,
                await _read_record(self.runtime.store, ref, run_id=identity["run_id"], kind="upgrade_flow"),
                False,
            )
        if state.frozen is None:
            if original is not None:
                return *original, False
            ref = self.materials.active()
            return ref, self.materials.read_object(ref, kind="upgrade_flow")["records"][0], False

        candidates = []
        for ref, value in self.materials.reconciliation_candidates():
            value = _flow(value, **identity)
            if value["baseline_ref"] != state.frozen.baseline_ref or value["plan_ref"] != state.frozen.plan_ref:
                continue
            if value["environment"] != environment or any(value[key] != connection[key] for key in connection):
                _reject("candidate_environment_or_schema_changed")
            binding = value["operator_binding"]
            if binding["mode"] == "fixed" and binding["operator_id"] != operator_id:
                continue
            candidates.append((ref, value))
        if not candidates:
            if original is not None:
                return *original, False
            _reject("dry_run_required")

        from bisheng.knowledge.application.unification_reference_reconciliation import (
            inspect_reference_reconciliation,
            validate_reference_candidate,
        )

        semantic = (
            original[1]["semantic_projection_ref"]
            if original is not None
            else candidates[0][1]["semantic_projection_ref"]
        )
        if any(candidate["semantic_projection_ref"] != semantic for _, candidate in candidates):
            _reject("candidate_semantic_identity_conflict")
        if original is not None and any(
            candidate["history_summary"] != original[1]["history_summary"] for _, candidate in candidates
        ):
            _reject("candidate_history_summary_changed")
        store = self.materials.local_store(self.runtime.store)
        application = UnificationSQLConversionApplication(
            artifact_store=store, session_factory=self.runtime.sessions, read_only_resume=True
        )
        with store.verified_reads():
            # Exactly one complete native observation for all candidate
            # comparisons; filesystem iteration order/mtime grants no priority.
            current = await inspect_reference_reconciliation(
                application,
                frozen=state.frozen,
                environment=environment,
                operator_id=operator_id,
                semantic_projection_ref=semantic,
            )
            matches = []
            for ref, value in candidates:
                if value["reconciliation_ref"] is None:
                    _reject("candidate_proof_missing")
                expected = await _read_record(
                    store, value["reconciliation_ref"], run_id=identity["run_id"], kind="verification"
                )
                try:
                    validate_reference_candidate(expected, current, frozen=state.frozen, environment=environment)
                except KnowledgeOperationPlanConflictError:
                    continue
                matches.append((ref, value))
        if len(matches) != 1:
            _reject("dry_run_required" if not matches else "multiple_matching_candidates")
        return *matches[0], True

    async def _admit_flow(self, args, *, identity, state, environment, connection):
        """Complete read-only admission, usable before bootstrap and under lock."""
        if state.pending_intents:
            raise KnowledgeOperationPlanConflictError(reason="migration_executor_recovery_required")
        flow_ref, flow, current_checked = await self._select_flow(
            identity=identity, environment=environment, connection=connection, state=state, operator_id=args.operator_id
        )
        flow = _flow(flow, **identity)
        if flow["operator_binding"]["mode"] == "fixed" and flow["operator_binding"]["operator_id"] != args.operator_id:
            _reject("operator_binding_changed")
        if (
            flow["environment"] != environment
            or any(flow[key] != connection[key] for key in connection)
            or flow["tenant_ids"] != list(state.tenant_ids)
        ):
            _reject("environment_or_schema_changed")
        if state.binding is not None and state.binding["operator_id"] != args.operator_id:
            _reject("operator_binding_changed")
        if (
            state.frozen is not None
            and state.binding is None
            and flow["history_summary"]["counts_scope"] != "history_actions_in_this_command"
        ):
            _reject("history_summary_scope_changed")
        if state.frozen is None:
            replay = semantics = None
            actor = flow["operator_binding"]["operator_id"]
            if state.preparing:
                replay = await _read_record(
                    self.runtime.store, flow["history_ref"], run_id=args.run_id, kind="history_replay"
                )
                semantics = await _read_record(
                    self.runtime.store, flow["history_semantics_ref"], run_id=args.run_id, kind="verification"
                )
                actor = state.binding["operator_id"]
            verified, diagnostics = await self._preview_new(
                identity=identity,
                environment=environment,
                planned_at=datetime.fromisoformat(flow["planned_at"]),
                local_store=self.materials.local_store(self.runtime.store),
                operator_id=actor,
                replay_plan=replay,
                expected_semantics=semantics,
            )
            fields = (
                "history_ref",
                "history_semantics_ref",
                "baseline_ref",
                "plan_ref",
                "semantic_projection_ref",
                "tenant_ids",
                "history_summary",
            )
            if diagnostics or verified is None or any(verified[key] != flow[key] for key in fields):
                _reject("preparing_expected_after_changed" if state.preparing else "before_changed")
        else:
            readonly = UnificationSQLConversionApplication(
                artifact_store=self.runtime.store, session_factory=self.runtime.sessions, read_only_resume=True
            )
            resume = await readonly.apreview_resume(
                frozen=state.frozen,
                inputs={"environment": environment, "backup_ref": args.backup_ref, "schema_ref": args.schema_ref},
                operator_id=args.operator_id,
            )
            if not resume["complete"]:
                _reject("resume_preflight_incomplete")
            if not current_checked:
                from bisheng.knowledge.application.unification_reference_reconciliation import (
                    inspect_reference_reconciliation,
                    validate_reference_candidate,
                )

                # Original new-Run flows need this check too: absence of an
                # extension candidate never licenses a changed source.
                current = await inspect_reference_reconciliation(
                    readonly,
                    frozen=state.frozen,
                    environment=environment,
                    operator_id=args.operator_id,
                    semantic_projection_ref=flow["semantic_projection_ref"],
                )
                if current["diagnostics"] or current["manifest"] is None:
                    _reject("reference_resume_preflight_changed")
                if flow["reconciliation_ref"] is not None:
                    expected = await _read_record(
                        self.runtime.store
                        if flow_ref in state.reconciliation_refs
                        else self.materials.local_store(self.runtime.store),
                        flow["reconciliation_ref"],
                        run_id=args.run_id,
                        kind="verification",
                    )
                    validate_reference_candidate(expected, current, frozen=state.frozen, environment=environment)
        await self.materials.validate_tree(self.runtime.store, flow_ref)
        return flow_ref, flow

    async def apply(self, args):
        if type(args.operator_id) is not int or args.operator_id <= 0:
            _reject("positive_operator_required")
        await self._verify_actor(args.operator_id)
        identity = {"run_id": args.run_id, "writer_contract_version": args.writer_contract_version}
        state = await self._state(identity)
        if getattr(args, "verify", False) and not state.completed:
            _reject("verify_requires_completed")
        if args.resume and not state.phases:
            raise KnowledgeOperationPlanConflictError(reason="migration_cli_resume_requires_frozen_run")
        environment, connection = await self._environment(
            args.environment, state=state, backup_ref=args.backup_ref, schema_ref=args.schema_ref
        )
        if state.completed:
            if not getattr(args, "verify", False):
                result = await self._completed(identity, state)
                result["report_path"] = self.materials.write_report(result)
                return result
            # Terminal audits never create an executor, upload a candidate or
            # append a binding, including a legacy completed Run's first audit.
            # Its newly checked candidate remains private and is read through
            # the local overlay by the native complete verification path.
            _, flow = await self._admit_flow(
                args, identity=identity, state=state, environment=environment, connection=connection
            )
            report_progress("verify", unit="source", waiting="database")
            store = self.materials.local_store(self.runtime.store)
            application = UnificationSQLConversionApplication(
                artifact_store=store, session_factory=self.runtime.sessions
            )
            with store.verified_reads():
                report = await application.arun_references(
                    **identity,
                    environment=environment,
                    backup_ref=args.backup_ref,
                    schema_ref=args.schema_ref,
                    operator_id=args.operator_id,
                    reuse_completed=True,
                    reconciliation_ref=flow["reconciliation_ref"],
                    semantic_projection_ref=flow["semantic_projection_ref"],
                )
            return await self._reference_result(identity, flow, report)
        from bisheng.knowledge.domain.repositories.unification_executor_repository import UnificationExecutorRepository

        if getattr(
            self.runtime, "executor_lock", None
        ) is None and not await UnificationExecutorRepository().ahas_control_seed(self.runtime.engine):
            # A failed first plan must not leave even a lock seed. The initial
            # bootstrap pays one extra live admission; existing seeds do not.
            await self._admit_flow(args, identity=identity, state=state, environment=environment, connection=connection)
        async with UpgradeExecutor.acquire(self.runtime, **identity) as executor:
            # Recheck under the global mutex before creating or resuming rows.
            current = await self._state(identity)
            if current != state:
                _reject("run_changed_during_admission")
            flow_ref, flow = await self._admit_flow(
                args, identity=identity, state=state, environment=environment, connection=connection
            )
            # Publish all recovery dependencies and read them back before the
            # preparing binding or the first historical business effect.
            if flow_ref not in state.reconciliation_refs and (
                state.binding is None or state.binding["flow_ref"] != flow_ref
            ):
                await self.materials.upload_tree(self.runtime.store, flow_ref)
            await executor.start(
                state.tenant_ids,
                preparing_binding={"schema_version": 1, "flow_ref": flow_ref, "operator_id": args.operator_id}
                if state.frozen is None
                else None,
            )
            try:
                from bisheng.permission.domain.services.maintenance_guard import maintenance_guard

                with maintenance_guard(
                    transaction_guard=executor.permission_transaction_guard,
                    external_guard=executor,
                    global_tenants=state.tenant_ids,
                    identity=identity,
                ):
                    if state.frozen is None:
                        await self._history_and_freeze(args, executor, state, flow_ref, flow, environment)
                    else:
                        if flow["kind"] == "frozen_resume":
                            with tenant_execution_scope(1):
                                async with self.runtime.sessions() as session, session.begin():
                                    await executor.guard_all(session)
                                    await self.repository.abind_reconciliation(
                                        session, **identity, tenant_ids=state.tenant_ids, flow_ref=flow_ref
                                    )
                    application = UnificationSQLConversionApplication(
                        artifact_store=self.runtime.store,
                        session_factory=self.runtime.sessions,
                        transaction_guard=executor.transaction_guard,
                        external_guard=executor,
                    )
                    report_progress("sql", unit="command", waiting="database")
                    with self.runtime.store.verified_reads():
                        report = await application.arun_references(
                            **identity,
                            environment=environment,
                            backup_ref=args.backup_ref,
                            schema_ref=args.schema_ref,
                            operator_id=args.operator_id,
                            reuse_completed=True,
                            reconciliation_ref=flow["reconciliation_ref"],
                            semantic_projection_ref=flow["semantic_projection_ref"],
                        )
                await executor.finish_attempt()
            except BaseException:
                await executor.finish_attempt(preserve_error=True)
                raise
        return await self._reference_result(identity, flow, report)

    async def _reference_result(self, identity, flow, report):
        latest = await self._state(identity)
        result = await self._completed(identity, latest)
        result.update({name: flow["history_summary"][name] for name in _SUMMARY_FIELDS})
        result.update(asdict(report))
        result["tenant_ids"] = list(report.tenant_ids)
        result["report_path"] = self.materials.write_report(result)
        return result

    async def _history_and_freeze(self, args, executor, state, flow_ref, flow, environment):
        from bisheng.knowledge.application.unification_history import (
            apply_history,
            assert_history_after,
            verified_history_after_ports,
        )

        identity = {"run_id": args.run_id, "writer_contract_version": args.writer_contract_version}
        binding = {"schema_version": 1, "flow_ref": flow_ref, "operator_id": args.operator_id}
        with tenant_execution_scope(1):
            async with self.runtime.sessions() as session, session.begin():
                await executor.guard_all(session)
                await self.repository.abind_preparing(session, **identity, tenant_ids=state.tenant_ids, binding=binding)
        replay = await _read_record(self.runtime.store, flow["history_ref"], run_id=args.run_id, kind="history_replay")
        semantics = await _read_record(
            self.runtime.store, flow["history_semantics_ref"], run_id=args.run_id, kind="verification"
        )
        report_progress("history", unit="action", waiting="database")
        async with _history_runtime(self.runtime) as runtime:
            await apply_history(
                runtime,
                replay_plan=replay,
                operator_id=args.operator_id,
                transaction_guard=executor.permission_transaction_guard,
                external_guard=executor,
                **identity,
            )
            after = await assert_history_after(runtime, replay, semantics, args.operator_id)
            await executor.assert_settled()
            normalized = await verified_history_after_ports(runtime, replay, semantics, after, args.operator_id)
            try:
                inventory = UnificationInventoryApplication(
                    artifact_store=self.materials.local_store(self.runtime.store),
                    sharing_reader_factory=normalized.reader_factory,
                    read_ports=normalized.read_ports,
                )
                with tenant_execution_scope(1):
                    async with runtime.sessions() as session, session.begin():
                        checked = await inventory.arun(
                            session,
                            **identity,
                            environment=environment,
                            planned_at=datetime.fromisoformat(flow["planned_at"]),
                            freeze=False,
                            retain_preview_artifacts=True,
                        )
                if checked.baseline_ref != flow["baseline_ref"] or checked.plan_ref != flow["plan_ref"]:
                    _reject("full_expected_after_changed")
            finally:
                await normalized.aclose()
            after_ref = await self._put(self.runtime.store, args.run_id, "verification", after)
            with tenant_execution_scope(1):
                async with self.runtime.sessions() as session, session.begin():
                    for tenant in state.tenant_ids:
                        with tenant_execution_scope(tenant):
                            await executor.permission_transaction_guard(session)
                            row = await self.repository.runs._required(session, **identity)
                            value = {
                                "cursor": canonical({"schema_version": 1, "ref": after_ref}).decode(),
                                "processed_count": 1,
                                "digest": after_ref["sha256"],
                                "complete": True,
                            }
                            await self.repository.runs.acheckpoint(
                                session,
                                **identity,
                                baseline_hash=None,
                                plan_hash=None,
                                expected_phase="preparing",
                                checkpoint_key="history_after_v1",
                                expected_checkpoint=row.checkpoints.get("preparing", {}).get("history_after_v1"),
                                checkpoint=value,
                            )
            report_progress("freeze", unit="tenant", waiting="database")
            inventory = UnificationInventoryApplication(
                artifact_store=self.runtime.store, sharing_reader_factory=runtime.sharing_reader_factory
            )
            with tenant_execution_scope(1):
                async with runtime.sessions() as session, session.begin():
                    await executor.guard_all(session)
                    await inventory.arun(
                        session,
                        **identity,
                        environment=environment,
                        planned_at=datetime.fromisoformat(flow["planned_at"]),
                        flow_binding={
                            "upgrade_flow_policy": "unified_v1",
                            "upgrade_flow_ref": flow_ref,
                            "upgrade_history_sha256": replay["history_sha256"],
                            "upgrade_semantics_sha256": flow["history_semantics_ref"]["sha256"],
                            "upgrade_history_after_ref": after_ref,
                        },
                    )


async def arun_upgrade(args, *, runtime, materials):
    application = UnificationUpgradeApplication(runtime, materials)
    try:
        return await (application.apply(args) if args.apply else application.preview(args))
    except BaseException as error:
        args._upgrade_failure = await application.failure_report(args, error)
        raise
