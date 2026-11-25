"""Original Run-coordinated stopped-service permission publication.

No IO executes inside owned SQL transactions. The original four-field Run
checkpoint records an ACK prefix and at most one pending fixed finite effect.
"""

import asyncio
import json
from contextlib import nullcontext
from dataclasses import asdict, dataclass, field
from hashlib import sha256

from loguru import logger

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application import unification_identity_retention as identity_retention
from bisheng.knowledge.application import unification_stage_receipts as receipts
from bisheng.knowledge.application.unification_inventory_codec import canonical, decode_inventory_page
from bisheng.knowledge.application.unification_permission_namespace import PermissionNamespacePlan, catalog_from_records
from bisheng.knowledge.application.unification_progress import report_progress
from bisheng.permission.application.catalog_api import OpenFGACatalogProjector
from bisheng.permission.application.f118_permission_publish import F118PermissionPublisher
from bisheng.permission.application.f118_permission_tuples import F118PermissionTupleBuilder, blocked
from bisheng.permission.domain.repositories.f118_catalog_write_repository import F118CatalogWriteRepository, _Current
from bisheng.permission.domain.repositories.f118_resource_write_repository import F118ResourceWriteRepository
from bisheng.permission.migration.f118_plan import (
    AuthorizationPinBaseline,
    ResourceRetirementPlanner,
    _checksum,
    build_catalog_retirement_plan,
)


def decode(page, content=None):
    return decode_inventory_page(
        page.content if content is None else content,
        run_id=page.run_id,
        section=page.section,
        scope=page.scope,
        tenant_id=page.tenant_id,
        page_index=page.page_index,
        kind=page.kind,
    ).records


@dataclass(frozen=True, slots=True)
class _Page:
    run_id: str
    kind: str
    section: str
    scope: str
    tenant_id: int | None
    page_index: int
    descriptor: dict = field(repr=False)


class PermissionPublicationInput:
    def __init__(self, *, application, frozen, inputs):
        self.app, self.frozen, self.inputs = application, frozen, inputs
        self.pages = {tenant: [] for tenant in frozen.tenant_ids}
        self.summaries = {tenant: {} for tenant in frozen.tenant_ids}
        self.original_tuples = []
        self.planner = None
        self.retention_metadata = {}
        self.retention_objects = None

    async def _catalog_seed(self):
        # This bounded pre-read supplies pure compilation, not admission. The
        # original reader below subsequently verifies the entire graph and every
        # original/after byte against this exact supplied compiled context.
        records, seen = [], set()

        async def visit(ref, section="manifest", scope="global", tenant=None, index=0, depth=0):
            if depth > 64 or ref["object_key"] in seen:
                blocked("catalog_seed_graph")
            seen.add(ref["object_key"])
            if section not in {"manifest", "catalog"}:
                return
            content = await self.app.store.aload_canonical(ref, run_id=self.frozen.run_id, kind="baseline")
            page = decode_inventory_page(
                content,
                run_id=self.frozen.run_id,
                section=section,
                scope=scope,
                tenant_id=tenant,
                page_index=index,
                kind="baseline",
            )
            if section == "catalog":
                if scope != "global" or tenant is not None:
                    blocked("catalog_seed_scope")
                records.extend(page.records)
            else:
                for record in page.records:
                    if record.record_type == "manifest_entry":
                        row = record.data
                        await visit(
                            row["descriptor"],
                            row["section"],
                            row["scope"],
                            row["tenant_id"],
                            row["page_index"],
                            depth + 1,
                        )

        await visit(self.frozen.baseline_ref)
        plan_content = await self.app.store.aload_canonical(
            self.frozen.plan_ref, run_id=self.frozen.run_id, kind="plan"
        )
        root = decode_inventory_page(
            plan_content,
            run_id=self.frozen.run_id,
            section="manifest",
            scope="global",
            tenant_id=None,
            page_index=0,
            kind="plan",
        )
        metadata = [row.data for row in root.records if row.record_type == "run"]
        if len(metadata) != 1:
            blocked("plan_metadata")
        self.legacy_policy = metadata[0].get("preparation_policy_version", 1) == 1
        self.retention_metadata = identity_retention.metadata(metadata[0])
        plan = build_catalog_retirement_plan(
            run_id=self.frozen.run_id,
            writer_contract_version=self.frozen.writer_contract_version,
            before=catalog_from_records(records),
            target_model_checksum=metadata[0]["authorization_model_checksum"],
            namespace_type_mappings=(("knowledge_library", "knowledge_space"),),
        )
        return ResourceRetirementPlanner(catalog_plan=plan)

    async def aload(self):
        report_progress("permission_plan", unit="page", waiting="planning")
        execution = self.app.store.verified_inputs
        key = execution.inventory_key(self.frozen, **self.inputs) if execution is not None else None
        bundle = execution.get_inventory(key) if execution is not None else None
        self.planner = bundle.permission_planner if bundle is not None and bundle.sealed else await self._catalog_seed()
        if bundle is not None and bundle.sealed:
            # The same original metadata is hash-verified; no namespace/catalog
            # compilation is repeated when the SQL consumer already sealed it.
            content = await self.app.store.aload_canonical(self.frozen.plan_ref, run_id=self.frozen.run_id, kind="plan")
            root = decode_inventory_page(
                content,
                run_id=self.frozen.run_id,
                section="manifest",
                scope="global",
                tenant_id=None,
                page_index=0,
                kind="plan",
            )
            metadata = [row.data for row in root.records if row.record_type == "run"]
            if len(metadata) != 1:
                blocked("plan_metadata")
            self.legacy_policy = metadata[0].get("preparation_policy_version", 1) == 1
            self.retention_metadata = identity_retention.metadata(metadata[0])
        async for actual in self.app.reader.aiter_frozen_pages(
            self.frozen, **self.inputs, _permission_planner=self.planner
        ):
            if actual.section not in {"resources", "permission", "fga", "conversion"}:
                continue
            page = _Page(
                self.frozen.run_id,
                actual.kind,
                actual.section,
                actual.scope,
                actual.tenant_id,
                actual.page_index,
                dict(actual.descriptor),
            )
            rows = decode(page, actual.content)
            if actual.kind == "baseline" and actual.section in {"resources", "permission"}:
                self.pages[actual.tenant_id].append(page)
            elif actual.kind == "baseline" and actual.section == "fga":
                self.original_tuples.extend(
                    (row.data["user"], row.data["relation"], row.data["object"]) for row in rows
                )
            elif actual.kind == "plan" and actual.section == "conversion":
                for row in rows:
                    if row.record_type == "permission_plan":
                        data = row.data
                        if data["mode_id"] in self.summaries[actual.tenant_id]:
                            blocked("duplicate_mode_header")
                        self.summaries[actual.tenant_id][data["mode_id"]] = data
        # Only an exhausted original verifier makes these facts consumable.
        self._bundle = execution.get_inventory(key) if execution is not None else None
        return self

    async def aplans(self, tenant):
        if getattr(self, "_bundle", None) is not None:
            plans = self._bundle.plans(tenant)
            if len(plans) != len(self.summaries[tenant]):
                blocked("mode_header_membership")
            return plans
        collector = PermissionNamespacePlan(permission_planner=self.planner)
        for page in self.pages[tenant]:
            content = await self.app.store.aload_canonical(page.descriptor, run_id=self.frozen.run_id, kind="baseline")
            for row in decode(page, content):
                collector.observe(section=page.section, tenant_id=tenant, record=row)
        plans = tuple(collector.finish())
        if {plan.before.mode.id for plan in plans} != set(self.summaries[tenant]):
            blocked("mode_header_membership")
        return plans


@dataclass(frozen=True, slots=True)
class PermissionPublicationReport:
    run_id: str
    writer_contract_version: str
    baseline_hash: str
    plan_hash: str
    complete: bool


class PermissionPublicationApplication:
    def __init__(self, application):
        self.app, self.catalog = application, F118CatalogWriteRepository()

    def _binding(self, frozen, planner, operator):
        return self.app._identity(frozen) | {
            "catalog_plan_checksum": planner.catalog_plan.checksum,
            "operator_id": operator,
        }

    def _value(self, cursor, count, *, complete=False, digest=None):
        return {
            "cursor": canonical(cursor).decode(),
            "processed_count": count,
            "digest": digest or _checksum(cursor),
            "complete": complete,
        }

    def _cursor(self, checkpoint):
        try:
            cursor = json.loads(checkpoint["cursor"])
            if canonical(cursor).decode() != checkpoint["cursor"]:
                blocked("noncanonical_checkpoint")
            return cursor
        except (TypeError, ValueError, KeyError) as error:
            raise ReferenceCoverageNotReadyError(reason="permission_checkpoint_invalid") from error

    async def _get(self, frozen, key):
        async with self.app._session() as session, session.begin():
            run = await self.app._scope_run(session, frozen)
            return run.checkpoints.get("converting", {}).get(key)

    async def _commit(self, frozen, key, expected, value, effect=None):
        async with self.app._session() as session:
            await session.begin()
            try:
                await self.app._scope_run(session, frozen)
                async with session.begin_nested():
                    current = _Current(session)
                    result = await effect(session) if effect else None
                    current.check()
                    await self.app.runs.acheckpoint(
                        session,
                        **self.app._identity(frozen),
                        expected_phase="converting",
                        checkpoint_key=key,
                        expected_checkpoint=expected,
                        checkpoint=value,
                    )
                    current.check()
                current = _Current(session)
                current.check()
                # Unknown ACKs propagate. No continuation is issued by cleanup.
                await session.commit()
                return result
            except BaseException:
                try:
                    if session.in_transaction():
                        await session.rollback()
                except Exception as cleanup_error:
                    logger.warning(
                        "F118 maintenance reason=permission_rollback_failed error_type={}", type(cleanup_error).__name__
                    )
                raise

    def _args(self, planner, meta):
        return {
            "permission_planner": planner,
            "draft_id": meta["draft_id"],
            "target_authorization_release_id": meta["authorization"]["id"],
            "operator_id": meta["binding"]["operator_id"],
            "idempotency_key": meta["idempotency_key"],
        }

    def _metadata(self, checkpoint, binding):
        meta = self._cursor(checkpoint)
        if (
            set(meta) != {"binding", "draft_id", "authorization", "release_key", "idempotency_key"}
            or meta["binding"] != binding
            or checkpoint != self._value(meta, 0, complete=True)
        ):
            blocked("catalog_checkpoint_binding")
        try:
            pin = AuthorizationPinBaseline(**meta["authorization"])
        except (TypeError, ValueError) as error:
            raise ReferenceCoverageNotReadyError(reason="permission_checkpoint_pin") from error
        if type(meta["draft_id"]) is not int or meta["draft_id"] <= 0 or type(pin.id) is not int or pin.id <= 0:
            blocked("catalog_checkpoint_ids")
        return meta, pin

    async def _receipt_checkpoints(self, session, frozen, complete=None):
        tenants, global_values = [], None
        for tenant in frozen.tenant_ids:
            with tenant_execution_scope(tenant):
                run = await self.app._scope_run(session, frozen)
                cp = run.checkpoints.get("converting", {})
                tenants.append(
                    {
                        "tenant_id": tenant,
                        "sql_conversion": cp.get("sql_conversion"),
                        "sql_admission": receipts.find(run, "sql_admission_v1"),
                        "permission_namespace": cp.get("permission_namespace"),
                    }
                )
                if tenant == frozen.tenant_ids[0]:
                    global_values = {
                        key: cp.get(key)
                        for key in ("permission_prepare", "permission_catalog", "permission_fga", "permission_complete")
                    }
        if complete is not None:
            global_values["permission_complete"] = complete
        if global_values is None or any(
            value is None or value.get("complete") is not True for value in global_values.values()
        ):
            blocked("admission_global_incomplete")
        if any(
            row[key] is None or row[key].get("complete") is not True
            for row in tenants
            for key in ("sql_conversion", "permission_namespace")
        ):
            blocked("admission_tenant_incomplete")
        return {"tenants": tenants, "global": global_values}

    async def _after_directory(self, frozen, tuple_plan):
        def records():
            yield {"section": "metadata", "retention_metadata": self.inputs.retention_metadata}
            for tenant in frozen.tenant_ids:
                for mode_id, header in self.inputs.summaries[tenant].items():
                    yield {"section": "namespace", "tenant_id": tenant, "mode_id": mode_id, "header": header}
            for key in sorted(tuple_plan.after):
                yield {"section": "tuple", "key": list(key)}

        return await receipts.put_directory(
            self.app.store, frozen, purpose="permission-after-v1", records=records(), batch_size=10000
        )

    def _admission_value(self, frozen, *, directory, checkpoints, binding, environment):
        return receipts.checkpoint(
            {
                "schema_version": 1,
                "compiler_contract": "f118-permission-admission-v1",
                "stage": "permission",
                "identity": receipts.identity(frozen),
                "binding": binding,
                "environment": environment,
                "tenant_ids": list(frozen.tenant_ids),
                "directory": directory,
                "checkpoints": checkpoints,
            },
            1,
        )

    async def arequire_completed(self, *, frozen, inputs, operator_id):
        with tenant_execution_scope(frozen.tenant_ids[0]):
            raw = await self.app._read_stage_checkpoint(frozen, "permission_admission_v1")
            if raw is None:
                return None
            value = receipts.payload(raw)
            if (
                set(value)
                != {
                    "schema_version",
                    "compiler_contract",
                    "stage",
                    "identity",
                    "binding",
                    "environment",
                    "tenant_ids",
                    "directory",
                    "checkpoints",
                }
                or value["schema_version"] != 1
                or value["compiler_contract"] != "f118-permission-admission-v1"
                or value["stage"] != "permission"
                or value["identity"] != receipts.identity(frozen)
                or value["environment"] != inputs["environment"]
                or value["tenant_ids"] != list(frozen.tenant_ids)
                or raw != receipts.checkpoint(value, 1)
            ):
                blocked("admission_binding")
            self.inputs = PermissionPublicationInput(application=self.app, frozen=frozen, inputs=inputs)
            self.inputs.planner = await self.inputs._catalog_seed()
            planner = self.inputs.planner
            binding = self._binding(frozen, planner, operator_id)
            if value["binding"] != binding:
                blocked("admission_operator_or_catalog_changed")
            expected_tuples, metadata_seen = set(), False
            async for record in receipts.iter_directory(
                self.app.store, frozen, value["directory"], purpose="permission-after-v1"
            ):
                if record.get("section") == "metadata":
                    if metadata_seen or record["retention_metadata"] != self.inputs.retention_metadata:
                        blocked("admission_retention_changed")
                    metadata_seen = True
                elif record.get("section") == "namespace":
                    tenant, ident = record["tenant_id"], record["mode_id"]
                    if (
                        tenant not in frozen.tenant_ids
                        or ident in self.inputs.summaries[tenant]
                        or record["header"]["mode_id"] != ident
                    ):
                        blocked("admission_namespace_membership")
                    self.inputs.summaries[tenant][ident] = record["header"]
                elif record.get("section") == "tuple":
                    key = tuple(record["key"])
                    if (
                        len(key) != 3
                        or key in expected_tuples
                        or any(type(part) is not str or not part or len(part) > 4096 for part in key)
                    ):
                        blocked("admission_tuple_invalid")
                    expected_tuples.add(key)
                else:
                    blocked("admission_directory_section")
            if not metadata_seen:
                blocked("admission_metadata_missing")
            async with self.app._session() as session, session.begin():
                actual = await self._receipt_checkpoints(session, frozen)
            if actual != value["checkpoints"]:
                blocked("admission_checkpoints_changed")
            meta, pin = self._metadata(actual["global"]["permission_catalog"], binding)
            complete = actual["global"]["permission_complete"]
            complete_cursor = self._cursor(complete)
            if set(complete_cursor) != set(meta) | {"commit_checksum"} or complete != self._value(
                meta | {"commit_checksum": complete_cursor["commit_checksum"]}, 1, complete=True
            ):
                blocked("admission_completion_changed")
            fga = actual["global"]["permission_fga"]
            cursor = self._cursor(fga)
            if (
                cursor.get("pending") is not None
                or type(cursor.get("acked")) is not int
                or fga != self._fga_value(meta, cursor.get("operation_hash"), cursor["acked"], None, cursor["acked"])
            ):
                blocked("admission_fga_pending")
            if await self.app._admit_sql_completed(frozen, inputs) is None:
                blocked("admission_sql_evidence_missing")
            await self._resource_status(frozen, self.inputs, meta, final=True)
            async with self.app._session() as session, session.begin():
                await self.app._scope_run(session, frozen)
                published = await self.catalog.averify_published(session, **self._args(planner, meta))
            expected_pin = {**asdict(pin), "status": "ACTIVE"}
            if (
                asdict(published.authorization) != expected_pin
                or published.release.commit_checksum != complete_cursor["commit_checksum"]
            ):
                blocked("admission_current_pin_changed")
            from bisheng.permission.application.control_state import SqlPermissionControlState

            current = await SqlPermissionControlState().current_catalog()
            if (current.release_id, current.store_id, current.model_id, current.model_checksum) != (
                published.release.id,
                pin.store_id,
                pin.model_id,
                pin.model_checksum,
            ):
                blocked("admission_runtime_pin_changed")
            async with F118PermissionPublisher(
                catalog_plan=planner.catalog_plan, session_factory=self.app.sessions
            ) as io:
                await io.aset_target(pin)
                report_progress("permission_verify", unit="tuple", total=len(expected_tuples), waiting="fga")
                actual_tuples = await io.ascan()
                if actual_tuples != expected_tuples:
                    blocked("admission_current_graph_changed")
                report_progress(
                    "permission_verify",
                    unit="tuple",
                    processed=len(actual_tuples),
                    total=len(expected_tuples),
                    verified=len(actual_tuples),
                    status="complete",
                )
            if await self.app._admit(frozen.run_id, frozen.writer_contract_version) != frozen:
                blocked("admission_universe_changed")
            return PermissionPublicationReport(
                frozen.run_id,
                frozen.writer_contract_version,
                frozen.baseline_ref["sha256"],
                frozen.plan_ref["sha256"],
                True,
            )

    async def _resource_status(self, frozen, inputs, meta, *, final=False):
        repository = F118ResourceWriteRepository(permission_planner=inputs.planner)
        async with self.app._session() as session, session.begin():
            await self.app._scope_run(session, frozen)
            current = _Current(session)
            retained = await identity_retention.validate(
                session, expected=inputs.retention_metadata, repository=repository.snapshots
            )
            inputs.retention_objects = identity_retention.protected_objects(retained)
            current.check()
        for tenant in frozen.tenant_ids:
            with tenant_execution_scope(tenant):
                checkpoint = await self._get(frozen, "permission_namespace")
                headers = inputs.summaries[tenant]
                count = checkpoint["processed_count"] if checkpoint else 0
                if count > len(headers) or (final and count != len(headers)):
                    blocked("resource_checkpoint_count")
                seed, expected, ordinal = _checksum(meta), {}, 0
                for ident, header in headers.items():
                    ordinal += 1
                    if ordinal <= count:
                        seed = _checksum((seed, header["plan_checksum"]))
                    expected[ident] = header["after_digest"] if ordinal <= count else header["before_digest"]
                if checkpoint is not None and checkpoint != self._value(
                    meta, count, complete=count == len(headers), digest=seed
                ):
                    blocked("resource_checkpoint_digest")
                if final and (checkpoint is None or not checkpoint["complete"]):
                    blocked("resource_incomplete")
                async with self.app._session() as session, session.begin():
                    await self.app._scope_run(session, frozen)
                    actual = await repository.alist_resources(session)
                    if {row.mode.id for row in actual} != set(expected) or any(
                        _checksum(row) != expected[row.mode.id] for row in actual
                    ):
                        blocked("resource_sql_prefix_changed")
                    del actual

    async def _final_sql(self, session, frozen):
        # No artifact/FGA reads here. Recheck the entire detached signed after
        # directory inside the same final SQL transaction as CURRENT and Run.
        if await self.app.runs.alist_actual_tenant_ids(session) != frozen.tenant_ids:
            blocked("final_tenant_universe_changed")
        repository = F118ResourceWriteRepository(permission_planner=self.inputs.planner)
        current = _Current(session)
        await identity_retention.validate(
            session, expected=self.inputs.retention_metadata, repository=repository.snapshots
        )
        current.check()
        for tenant in frozen.tenant_ids:
            with tenant_execution_scope(tenant):
                await self.app._scope_run(session, frozen)
                actual = await repository.alist_resources(session, lock=True)
                expected = self.inputs.summaries[tenant]
                if {row.mode.id for row in actual} != set(expected) or any(
                    _checksum(row) != expected[row.mode.id]["after_digest"] for row in actual
                ):
                    blocked("final_permission_sql_changed")
                del actual

    async def _resources(self, frozen, inputs, meta):
        repository = F118ResourceWriteRepository(permission_planner=inputs.planner)
        for tenant in frozen.tenant_ids:
            with tenant_execution_scope(tenant):
                checkpoint = await self._get(frozen, "permission_namespace")
                count = checkpoint["processed_count"] if checkpoint else 0
                seed, ordinal = _checksum(meta), 0
                plans = await inputs.aplans(tenant)
                report_progress(
                    "namespace",
                    tenant_id=tenant,
                    unit="resource",
                    processed=count,
                    committed=count,
                    total=len(plans),
                    waiting="database",
                )
                pending = []
                for plan in plans:
                    ordinal += 1
                    seed = _checksum((seed, plan.checksum))
                    if ordinal <= count:
                        continue
                    pending.append(plan)
                    if len(pending) < 100 and ordinal != len(plans):
                        continue
                    batch = tuple(pending)

                    async def apply(session, batch=batch):
                        return await repository.aapply_resources(session, plans=batch)

                    value = self._value(meta, ordinal, complete=ordinal == len(plans), digest=seed)
                    await self._commit(frozen, "permission_namespace", checkpoint, value, apply)
                    checkpoint = value
                    pending.clear()
                    report_progress(
                        "namespace",
                        tenant_id=tenant,
                        unit="resource",
                        processed=ordinal,
                        committed=ordinal,
                        total=len(plans),
                        cursor=value["cursor"],
                        commit_outcome="acknowledged",
                    )
                if not plans and checkpoint is None:
                    await self._commit(
                        frozen, "permission_namespace", None, self._value(meta, 0, complete=True, digest=seed)
                    )
                del plans

    async def _tuple_plan(self, inputs, io, release_key, stage):
        builder = F118PermissionTupleBuilder(
            catalog_plan=inputs.planner.catalog_plan,
            before_tuples=inputs.original_tuples,
            source_schema=io.source_schema,
            target_schema=io.target_schema,
            legacy_policy=inputs.legacy_policy,
        )
        for tenant in inputs.frozen.tenant_ids:
            for plan in await inputs.aplans(tenant):
                builder.observe(
                    plan,
                    restore_missing_markers=inputs.summaries[tenant][plan.before.mode.id].get(
                        "restore_missing_markers", False
                    ),
                )
        result = builder.finish(
            stage_tuples=stage,
            before_release_key=inputs.planner.catalog_plan.before.release.release_key,
            after_release_key=release_key,
        )
        if inputs.retention_objects is None:
            blocked("identity_retention_not_checked")
        identity_retention.verify_tuple_plan(result, inputs.retention_objects)
        return result

    def _operations(self, tuple_plan, io, draft):
        operations = []
        for action, keys in (("WRITE", tuple_plan.writes), ("DELETE", tuple_plan.deletes)):
            operations.extend((action, keys[start : start + 90]) for start in range(0, len(keys), 90))
        changes = io.pointer_changes(draft)
        operations.append(("ACTIVE", tuple((row.user, row.relation, row.object) for row in changes)))
        return tuple(operations)

    @staticmethod
    def _advance(values, operation):
        action, keys = operation
        if action == "WRITE":
            values.update(keys)
        elif action == "DELETE":
            values.difference_update(keys)
        else:
            # Original pointer changes are ordered DELETE subjects, then WRITE subjects.
            values.difference_update(keys[:2])
            values.update(keys[2:])

    def _fga_value(self, meta, operation_hash, ack, pending, total):
        return self._value(
            {"catalog": meta, "operation_hash": operation_hash, "acked": ack, "pending": pending},
            ack,
            complete=ack == total,
        )

    async def _fga(self, frozen, meta, io, tuple_plan, draft, live, checkpoint):
        operations = self._operations(tuple_plan, io, draft)
        op_hash, total = _checksum(operations), len(operations)
        ack, pending = 0, None
        if checkpoint is not None:
            cursor = self._cursor(checkpoint)
            ack, pending = cursor.get("acked"), cursor.get("pending")
            if (
                type(ack) is not int
                or not 0 <= ack <= total
                or (pending is not None and (type(pending) is not int or pending != ack or ack == total))
                or checkpoint != self._fga_value(meta, op_hash, ack, pending, total)
            ):
                blocked("tuple_checkpoint_binding")
        report_progress("fga", unit="batch", processed=ack, committed=ack, total=total, waiting="fga")
        expected = set(tuple_plan.before)
        for operation in operations[:ack]:
            self._advance(expected, operation)
        if pending is not None:
            after = set(expected)
            self._advance(after, operations[pending])
            if live == after:
                ack += 1
                expected = after
                value = self._fga_value(meta, op_hash, ack, None, total)
                await self._commit(frozen, "permission_fga", checkpoint, value)
                checkpoint = value
            elif live != expected:
                blocked("pending_tuple_effect_mixed")
        elif live != expected:
            blocked("live_tuple_prefix_changed")
        for index in range(ack, total):
            if operations[index][0] == "ACTIVE":
                # A complete finite S check is required immediately before the
                # sole pointer operation, never once per ordinary delta batch.
                actual = await io.ascan()
                if actual != tuple_plan.staged:
                    blocked("complete_staged_store_changed")
                await self._resource_status(frozen, self.inputs, meta, final=True)
                async with self.app._session() as session, session.begin():
                    await self.app._scope_run(session, frozen)
                    await self.catalog.averify_staged_catalog(session, **self._args(self.inputs.planner, meta))
            intent = self._fga_value(meta, op_hash, index, index, total)
            if checkpoint != intent:
                await self._commit(frozen, "permission_fga", checkpoint, intent)
                checkpoint = intent
            await self.app._external_effect(
                kind="permission_tuple_batch",
                identity={**self.app._identity(frozen), "batch": index, "intent_digest": _checksum(operations[index])},
                effect=lambda operation=operations[index]: io.aapply(operation, draft=draft),
            )
            value = self._fga_value(meta, op_hash, index + 1, None, total)
            await self._commit(frozen, "permission_fga", checkpoint, value)
            checkpoint = value
            report_progress(
                "fga",
                unit="batch",
                processed=index + 1,
                committed=index + 1,
                total=total,
                cursor=value["cursor"],
                commit_outcome="acknowledged",
            )
        # All ACKs still require exact Store reconciliation, including pointer.
        report_progress("fga_verify", unit="tuple", total=len(tuple_plan.after), waiting="fga")
        if await io.ascan() != tuple_plan.after:
            blocked("complete_after_store_changed")
        from bisheng.permission.application.catalog_api import _commit_checksum

        return _commit_checksum(io.pointer_changes(draft))

    async def apreview(self, *, frozen, inputs, operator_id=None):
        """Check native publication prefix without prepare, commit, or upload."""
        self.inputs = await PermissionPublicationInput(application=self.app, frozen=frozen, inputs=inputs).aload()
        planner = self.inputs.planner
        with tenant_execution_scope(frozen.tenant_ids[0]):
            catalog_checkpoint = await self._get(frozen, "permission_catalog")
            complete_checkpoint = await self._get(frozen, "permission_complete")
            prepare_checkpoint = await self._get(frozen, "permission_prepare")
            fga_checkpoint = await self._get(frozen, "permission_fga")
            original_operator = None
            if catalog_checkpoint is not None:
                original_operator = self._cursor(catalog_checkpoint).get("binding", {}).get("operator_id")
            elif prepare_checkpoint is not None:
                original_operator = self._cursor(prepare_checkpoint).get("operator_id")
            if operator_id is None:
                operator_id = original_operator if original_operator is not None else 0
            if type(operator_id) is not int or operator_id < 0:
                blocked("operator_invalid")
            binding = self._binding(frozen, planner, operator_id)
            pending, done = self._value(binding, 0), self._value(binding, 0, complete=True)
            if prepare_checkpoint is not None and prepare_checkpoint not in (pending, done):
                blocked("prepare_checkpoint_binding")
            if (catalog_checkpoint is None and prepare_checkpoint == done) or (
                catalog_checkpoint is not None and prepare_checkpoint != done
            ):
                blocked("prepare_catalog_checkpoint_order")
            async with F118PermissionPublisher(
                catalog_plan=planner.catalog_plan, session_factory=self.app.sessions
            ) as io:
                live = await io.ascan()
                if catalog_checkpoint is None:
                    if complete_checkpoint is not None or fga_checkpoint is not None:
                        blocked("checkpoint_without_catalog")
                    await self._resource_status(frozen, self.inputs, {"binding": binding})
                    async with self.app._session() as session, session.begin():
                        await self.app._scope_run(session, frozen)
                        await self.catalog.averify_before(session, expected=planner.catalog_plan.before)
                    if live != set(self.inputs.original_tuples) or len(live) != len(self.inputs.original_tuples):
                        blocked("original_store_changed")
                    await self._tuple_plan(self.inputs, io, "unreserved", ())
                    if prepare_checkpoint == pending:
                        # The catalog reservation/model publication has no
                        # native catalog receipt yet. Reads cannot assert that
                        # the external prepare request terminated.
                        return {
                            "complete": False,
                            "diagnostics": [
                                {
                                    "stage": "permission_resume",
                                    "classification": "not_evaluated",
                                    "reason": "permission_prepare_pending_unresolved",
                                }
                            ],
                        }
                else:
                    meta, pin = self._metadata(catalog_checkpoint, binding)
                    await io.aset_target(pin)
                    await self._resource_status(frozen, self.inputs, meta, final=complete_checkpoint is not None)
                    async with self.app._session() as session, session.begin():
                        await self.app._scope_run(session, frozen)
                        published = (
                            await self.catalog.averify_published(session, **self._args(planner, meta))
                            if complete_checkpoint is not None
                            else await self.catalog.averify_staged_catalog(session, **self._args(planner, meta))
                        )
                    expected_pin = {**asdict(pin), **({"status": "ACTIVE"} if complete_checkpoint is not None else {})}
                    if asdict(published.authorization) != expected_pin:
                        blocked("checkpoint_actual_pin_changed")
                    draft = io.stage_snapshot(published)
                    if draft.release_key != meta["release_key"]:
                        blocked("draft_key_changed")
                    plan = await self._tuple_plan(
                        self.inputs, io, meta["release_key"], OpenFGACatalogProjector.expected_stage_tuples(draft)
                    )
                    operations = self._operations(plan, io, draft)
                    ack, pending_index = 0, None
                    if fga_checkpoint is not None:
                        await self._resource_status(frozen, self.inputs, meta, final=True)
                        cursor = self._cursor(fga_checkpoint)
                        ack, pending_index = cursor.get("acked"), cursor.get("pending")
                        if (
                            type(ack) is not int
                            or not 0 <= ack <= len(operations)
                            or (
                                pending_index is not None
                                and (type(pending_index) is not int or pending_index != ack or ack == len(operations))
                            )
                            or fga_checkpoint
                            != self._fga_value(meta, _checksum(operations), ack, pending_index, len(operations))
                        ):
                            blocked("tuple_checkpoint_binding")
                    expected = set(plan.before)
                    for operation in operations[:ack]:
                        self._advance(expected, operation)
                    if pending_index is not None:
                        after = set(expected)
                        self._advance(after, operations[pending_index])
                        if live != expected and live != after:
                            blocked("pending_tuple_effect_mixed")
                    elif live != expected:
                        blocked("live_tuple_prefix_changed")
                    if complete_checkpoint is not None:
                        from bisheng.permission.application.catalog_api import _commit_checksum

                        checksum = _commit_checksum(io.pointer_changes(draft))
                        if (
                            complete_checkpoint != self._value(meta | {"commit_checksum": checksum}, 1, complete=True)
                            or fga_checkpoint is None
                            or not fga_checkpoint["complete"]
                            or pending_index is not None
                            or live != plan.after
                            or published.release.commit_checksum != checksum
                        ):
                            blocked("completion_binding")
                        from bisheng.permission.application.control_state import SqlPermissionControlState

                        current = await SqlPermissionControlState().current_catalog()
                        if (current.release_id, current.store_id, current.model_id, current.model_checksum) != (
                            published.release.id,
                            pin.store_id,
                            pin.model_id,
                            pin.model_checksum,
                        ):
                            blocked("admission_runtime_pin_changed")
        return {"complete": True, "diagnostics": []}

    async def arun(self, *, frozen, inputs, operator_id):
        if type(operator_id) is not int or operator_id < 0:
            blocked("operator_invalid")
        self.inputs = await PermissionPublicationInput(application=self.app, frozen=frozen, inputs=inputs).aload()
        planner = self.inputs.planner
        binding = self._binding(frozen, planner, operator_id)
        anchor = frozen.tenant_ids[0]
        with tenant_execution_scope(anchor):
            catalog_checkpoint = await self._get(frozen, "permission_catalog")
            complete_checkpoint = await self._get(frozen, "permission_complete")
            prepare_checkpoint = await self._get(frozen, "permission_prepare")
            prepare_pending = self._value(binding, 0)
            prepare_done = self._value(binding, 0, complete=True)
            if prepare_checkpoint is not None and prepare_checkpoint not in (prepare_pending, prepare_done):
                blocked("prepare_checkpoint_binding")
            if (catalog_checkpoint is None and prepare_checkpoint == prepare_done) or (
                catalog_checkpoint is not None and prepare_checkpoint != prepare_done
            ):
                blocked("prepare_catalog_checkpoint_order")
            async with F118PermissionPublisher(
                catalog_plan=planner.catalog_plan, session_factory=self.app.sessions
            ) as io:
                if catalog_checkpoint is None:
                    if complete_checkpoint is not None or await self._get(frozen, "permission_fga") is not None:
                        blocked("checkpoint_without_catalog")
                    # Validate complete SQL and tuple before facts before any
                    # remote model publication or reservation side effect.
                    seed_meta = {"binding": binding}
                    await self._resource_status(frozen, self.inputs, seed_meta)
                    async with self.app._session() as session, session.begin():
                        await self.app._scope_run(session, frozen)
                        await self.catalog.averify_before(session, expected=planner.catalog_plan.before)
                    live = await io.ascan()
                    if live != set(self.inputs.original_tuples) or len(live) != len(self.inputs.original_tuples):
                        blocked("original_store_changed")
                    await self._tuple_plan(self.inputs, io, "unreserved", ())
                    key = "f118-" + sha256(canonical(binding)).hexdigest()[:56]
                    if prepare_checkpoint is None:
                        await self._commit(frozen, "permission_prepare", None, prepare_pending)
                    model_id, reservation = await self.app._external_effect(
                        kind="permission_prepare",
                        identity={
                            **self.app._identity(frozen),
                            "intent_digest": _checksum(binding),
                            "idempotency_key": key,
                        },
                        effect=lambda: io.aprepare(operator_id=operator_id, idempotency_key=key),
                    )
                    async with self.app._session() as session, session.begin():
                        pin = await self.catalog.aresolve_target(session, permission_planner=planner, model_id=model_id)
                    meta = {
                        "binding": binding,
                        "draft_id": reservation.release_id,
                        "release_key": reservation.release_key,
                        "authorization": asdict(pin),
                        "idempotency_key": key,
                    }

                    await io.aset_target(pin)

                    async def stage(session):
                        result = await self.catalog.astage_catalog(session, **self._args(planner, meta))
                        await self.app.runs.acheckpoint(
                            session,
                            **self.app._identity(frozen),
                            expected_phase="converting",
                            checkpoint_key="permission_prepare",
                            expected_checkpoint=prepare_pending,
                            checkpoint=prepare_done,
                        )
                        return result

                    value = self._value(meta, 0, complete=True)
                    await self._commit(frozen, "permission_catalog", None, value, stage)
                else:
                    meta, pin = self._metadata(catalog_checkpoint, binding)
                    live = await io.ascan()
                if io.target is None:
                    await io.aset_target(pin)
                await self._resource_status(frozen, self.inputs, meta, final=complete_checkpoint is not None)
                async with self.app._session() as session, session.begin():
                    await self.app._scope_run(session, frozen)
                    if complete_checkpoint is None:
                        actual_catalog = await self.catalog.averify_staged_catalog(session, **self._args(planner, meta))
                    else:
                        actual_catalog = await self.catalog.averify_published(session, **self._args(planner, meta))
                    actual_pin = asdict(actual_catalog.authorization)
                    expected_pin = asdict(pin)
                    if complete_checkpoint is not None:
                        expected_pin["status"] = "ACTIVE"
                    if actual_pin != expected_pin:
                        blocked("checkpoint_actual_pin_changed")
                draft = io.stage_snapshot(actual_catalog)
                if draft.release_key != meta["release_key"]:
                    blocked("draft_key_changed")
                tuple_plan = await self._tuple_plan(
                    self.inputs, io, meta["release_key"], OpenFGACatalogProjector.expected_stage_tuples(draft)
                )
                fga_checkpoint = await self._get(frozen, "permission_fga")
                # Before any remaining SQL writes, reconcile an existing FGA
                # checkpoint. SQL resource prefixes cannot advance after FGA began.
                if fga_checkpoint is not None:
                    await self._resource_status(frozen, self.inputs, meta, final=True)
                elif live != tuple_plan.before:
                    blocked("original_store_changed")
                if complete_checkpoint is None:
                    await self._resources(frozen, self.inputs, meta)
                checksum = await self._fga(frozen, meta, io, tuple_plan, draft, live, fga_checkpoint)
                value = self._value(meta | {"commit_checksum": checksum}, 1, complete=True)
                report_progress(
                    "permission_finalize",
                    unit="stage",
                    total=1,
                    waiting="minio" if getattr(self.app, "_record_permissions", False) else "database",
                )
                directory = (
                    await self._after_directory(frozen, tuple_plan)
                    if getattr(self.app, "_record_permissions", False)
                    else None
                )
                if complete_checkpoint is not None:
                    if complete_checkpoint != value:
                        blocked("completion_binding")
                else:
                    await self._resource_status(frozen, self.inputs, meta, final=True)

                    async def finalize(session):
                        await self._final_sql(session, frozen)
                        result = await self.catalog.afinalize_catalog(
                            session, **self._args(planner, meta), commit_checksum=checksum
                        )
                        if directory is not None:
                            checkpoints = await self._receipt_checkpoints(session, frozen, complete=value)
                            await self.app.runs.acheckpoint(
                                session,
                                **self.app._identity(frozen),
                                expected_phase="converting",
                                checkpoint_key="permission_admission_v1",
                                expected_checkpoint=None,
                                checkpoint=self._admission_value(
                                    frozen,
                                    directory=directory,
                                    checkpoints=checkpoints,
                                    binding=binding,
                                    environment=inputs["environment"],
                                ),
                            )
                        return result

                    await self._commit(frozen, "permission_complete", None, value, finalize)
                if complete_checkpoint is not None and directory is not None:
                    async with self.app._session() as session, session.begin():
                        checkpoints = await self._receipt_checkpoints(session, frozen)
                    await self.app._write_stage_checkpoint(
                        frozen,
                        "permission_admission_v1",
                        self._admission_value(
                            frozen,
                            directory=directory,
                            checkpoints=checkpoints,
                            binding=binding,
                            environment=inputs["environment"],
                        ),
                    )
        if await self.app._admit(frozen.run_id, frozen.writer_contract_version) != frozen:
            blocked("final_universe_changed")
        return PermissionPublicationReport(
            frozen.run_id,
            frozen.writer_contract_version,
            frozen.baseline_ref["sha256"],
            frozen.plan_ref["sha256"],
            True,
        )


async def run_permissions(
    application,
    *,
    run_id,
    writer_contract_version,
    environment,
    backup_ref,
    schema_ref,
    operator_id,
    reuse_completed=False,
):
    with (
        application.store.verified_reads()
        if reuse_completed or application.store.verified_inputs is not None
        else nullcontext()
    ):
        application._record_permissions = reuse_completed
        return await _run_permissions(
            application,
            run_id=run_id,
            writer_contract_version=writer_contract_version,
            environment=environment,
            backup_ref=backup_ref,
            schema_ref=schema_ref,
            operator_id=operator_id,
            reuse_completed=reuse_completed,
        )


async def _run_permissions(
    application, *, run_id, writer_contract_version, environment, backup_ref, schema_ref, operator_id, reuse_completed
):
    try:
        if type(operator_id) is not int or operator_id < 0:
            blocked("operator_invalid")
        inputs = {"environment": environment, "backup_ref": backup_ref, "schema_ref": schema_ref}
        if reuse_completed:
            frozen = await application._admit(run_id, writer_contract_version)
            complete = await PermissionPublicationApplication(application).arequire_completed(
                frozen=frozen, inputs=inputs, operator_id=operator_id
            )
            if complete is not None:
                return complete
            terminal = True
            for tenant in frozen.tenant_ids:
                with tenant_execution_scope(tenant):
                    async with application._session() as session, session.begin():
                        terminal = terminal and (await application._scope_run(session, frozen)).phase == "completed"
            if terminal:
                application._record_permissions = False
        # The actual original SQL entry is always fully consumed, including its
        # native committed-prefix verification, before permission publication.
        await application.arun(
            run_id=run_id,
            writer_contract_version=writer_contract_version,
            environment=environment,
            backup_ref=backup_ref,
            schema_ref=schema_ref,
            reuse_completed=reuse_completed,
        )
        frozen = await application._admit(run_id, writer_contract_version)
        return await PermissionPublicationApplication(application).arun(
            frozen=frozen,
            operator_id=operator_id,
            inputs={"environment": environment, "backup_ref": backup_ref, "schema_ref": schema_ref},
        )
    except asyncio.CancelledError:
        raise
    except BaseErrorCode:
        raise
    except Exception as error:
        raise ReferenceCoverageNotReadyError(reason="migration_permission_publication_failed") from error
