"""Formal M2 inventory entry; only the ledger is written in the caller's TX.

Real physical/queue transports and a pinned reader factory are required inputs.
This entry never detects downtime, seeds permissions, binds references, changes
business data or certifies Coverage. Backups remain an operational prerequisite.
"""

from collections import defaultdict
from contextlib import aclosing
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore
from bisheng.knowledge.application.unification_inventory_codec import (
    InventoryRecord,
    decode_inventory_page,
    digest,
    encode_inventory_page,
    iter_manifest_nodes,
    record_from_row,
    record_from_values,
)
from bisheng.knowledge.application.unification_permission_inventory import PermissionInventoryVerifier
from bisheng.knowledge.application.unification_permission_namespace import catalog_namespace_records
from bisheng.knowledge.application.unification_physical_retention import (
    PhysicalRetentionInventoryVerifier,
    retention_record,
)
from bisheng.knowledge.application.unification_preflight import UnificationPreflight, source_decision
from bisheng.knowledge.application.unification_source_codec import decode_source_page, encode_source_page
from bisheng.knowledge.application.unification_sources import (
    ReferenceInventoryRecord,
    RootInventoryRecord,
    SourceInventoryRecord,
    UnificationSourceInventory,
)
from bisheng.knowledge.application.unification_space_membership_inventory import MembershipInventoryVerifier
from bisheng.knowledge.application.unification_structural_retention import (
    CREATOR_RETENTION,
    FILE_RETENTION,
    RETENTIONS,
    StructuralRetentionInventoryVerifier,
)
from bisheng.knowledge.domain.models.knowledge_unification_run import unification_now
from bisheng.knowledge.domain.repositories.unification_inventory_repository import UnificationInventoryRepository
from bisheng.knowledge.domain.repositories.unification_run_repository import (
    FrozenGlobalInventoryResult,
    KnowledgeUnificationRunRepository,
    _descriptor,
)
from bisheng.permission.application.migration_read import (
    OriginalTupleFact,
    PinnedMigrationPermissionReader,
    target_authorization_model_checksum,
)
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.migration.f118_plan import ResourceRetirementPlanner, build_catalog_retirement_plan
from bisheng.resource_reference.application.contracts import ReferenceSpec, TransactionIdentity, reference_set_digest

_SECTIONS = {
    "resources": {
        "resource",
        "file",
        "document",
        "version",
        "qa",
        "tag",
        "tag_link",
        "tag_library",
        "department_space",
    },
    "control": {
        "tenant",
        "membership",
        "department",
        "role",
        "user_role",
        "creator",
        "role_fact",
        "quota_usage",
        "space_membership_header",
        "space_member",
        "existing_space_creator_retention",
        "stranded_file_retention",
    },
    "permission": {"resource_mode", "grant", "assignee", "visible_source"},
    "permission_namespace": {
        "namespace_catalog",
        "namespace_applicability",
        "namespace_target_mode",
        "namespace_after_grant",
        "namespace_after_assignee",
        "namespace_after_visible_source",
    },
    "catalog": {"catalog_release", "authorization", "catalog_action", "permission_model"},
    "physical": {"physical_index", "physical_object", "physical_index_retention"},
    "tasks": {"queued_task", "queued_task_orphan", "broker_task"},
    "fga": {"fga_tuple"},
    "conversion": {
        "resource_conversion",
        "initialize_v1",
        "tag_conversion",
        "tag_link_conversion",
        "default_conversion",
        "permission_plan",
        "source_decision",
    },
}
_OBJECT_FIELDS = (
    ("object_name", "original"),
    ("preview_file_object_name", "preview"),
    ("bbox_object_name", "bbox"),
    ("thumbnails", "thumbnail"),
    ("html_snapshot_object_name", "html_snapshot"),
)


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"migration_inventory_{reason}")


def _section(section, record):
    if type(record) is not InventoryRecord or record.record_type not in _SECTIONS.get(section, set()):
        _blocked("section_record_mismatch")
    _ = record.data  # validates closure even for a manually constructed record


@dataclass(frozen=True, slots=True)
class FrozenInventoryPage:
    kind: str
    section: str
    scope: str
    tenant_id: int | None
    page_index: int
    record_count: int
    descriptor: dict = field(repr=False)
    content: bytes = field(repr=False)


class _Pages:
    def __init__(self, store, run_id, current):
        self.store, self.run_id, self.current = store, run_id, current
        self.buffers = defaultdict(list)
        self.indices = defaultdict(int)
        self.entries = {"baseline": [], "plan": []}

    async def _put(self, content, kind):
        self.current()
        descriptor = await self.store.aput_canonical(run_id=self.run_id, kind=kind, content=content)
        self.current()
        if await self.store.aload_canonical(descriptor, run_id=self.run_id, kind=kind) != content:
            _blocked("uploaded_content_changed")
        self.current()
        return descriptor

    async def add(self, section, tenant_id, record, *, kind="baseline"):
        self.current()
        if section != "sources":
            _section(section, record)
        key = (kind, section, tenant_id)
        self.buffers[key].append(record)
        if len(self.buffers[key]) == 199:
            await self.flush(key)

    async def flush(self, key):
        kind, section, tenant = key
        records = tuple(self.buffers.pop(key, ()))
        if not records:
            return
        index = self.indices[key]
        if section == "sources":
            content = encode_source_page(run_id=self.run_id, tenant_id=tenant, page_index=index, records=records)
            storage_kind = "sources"
        else:
            content = encode_inventory_page(
                run_id=self.run_id,
                section=section,
                scope="global" if tenant is None else "tenant",
                tenant_id=tenant,
                page_index=index,
                records=records,
                kind=kind,
            )
            storage_kind = kind
        descriptor = await self._put(content, storage_kind)
        self.entries[kind].append(
            record_from_values(
                "manifest_entry",
                section=section,
                scope="global" if tenant is None else "tenant",
                tenant_id=tenant,
                page_index=index,
                record_count=len(records),
                descriptor=descriptor,
                level=0,
            )
        )
        self.indices[key] += 1

    async def finish(self):
        for key in tuple(self.buffers):
            await self.flush(key)

    async def manifest(self, kind, metadata):
        root = None
        for node in iter_manifest_nodes(
            run_id=self.run_id, kind=kind, entries=iter(self.entries[kind]), metadata=metadata
        ):
            descriptor = await self._put(node.content, kind)
            if descriptor != node.descriptor:
                _blocked("manifest_identity")
            if node.is_root:
                root = descriptor
        if root is None:
            _blocked("manifest_missing")
        return root


class UnificationInventoryApplication:
    def __init__(
        self,
        *,
        artifact_store,
        sharing_reader_factory=None,
        physical_reader=None,
        queued_task_reader=None,
        broker_reader=None,
    ):
        # No eager clients/factories: general Storage and RAG constructors may
        # create buckets/policies/indexes or enforce unrelated online gates.
        self.store = artifact_store
        self.reader_factory = sharing_reader_factory
        self.physical = physical_reader
        self.queued = queued_task_reader
        self.broker = broker_reader
        self.runs = KnowledgeUnificationRunRepository()
        self.raw = UnificationInventoryRepository()
        self.permissions = PermissionMigrationSnapshotRepository()
        self.preflight = UnificationPreflight(permissions=self.permissions, inventory=self.raw)

    async def _materials(
        self, *, run_id, writer_contract_version, environment, tenant_ids, backup_ref, schema_ref, current
    ):
        for material_kind, descriptor in (("backup", backup_ref), ("schema", schema_ref)):
            content = await self.store.aload_canonical(descriptor, run_id=run_id, kind="verification")
            current()
            page = decode_inventory_page(
                content,
                run_id=run_id,
                section="evidence",
                scope="global",
                tenant_id=None,
                page_index=0,
                kind="verification",
            )
            if not page.records:
                _blocked("material_manifest_empty")
            for record in page.records:
                data = record.data
                if (
                    record.record_type != "evidence_material"
                    or data["material_kind"] != material_kind
                    or data["environment"] != environment
                    or data["writer_contract_version"] != writer_contract_version
                    or data["tenant_inventory_digest"] != digest(tenant_ids)
                ):
                    _blocked("material_manifest_identity")

    async def _verify_frozen(self, result, *, environment, backup_ref, schema_ref, current, permission_planner=None):
        async for _ in self.aiter_frozen_pages(
            result,
            environment=environment,
            backup_ref=backup_ref,
            schema_ref=schema_ref,
            current=current,
            _permission_planner=permission_planner,
        ):
            continue
        return result

    async def aiter_frozen_pages(
        self,
        result,
        *,
        environment,
        backup_ref,
        schema_ref,
        current=None,
        _permission_planner=None,
    ):
        if (
            type(result) is not FrozenGlobalInventoryResult
            or type(result.tenant_ids) is not tuple
            or not result.tenant_ids
            or any(type(tenant) is not int or tenant <= 0 for tenant in result.tenant_ids)
            or tuple(sorted(set(result.tenant_ids))) != result.tenant_ids
            or (current is not None and not callable(current))
        ):
            _blocked("invalid_frozen_input")
        memberships = MembershipInventoryVerifier()
        tenants = frozenset(result.tenant_ids)
        physical = PhysicalRetentionInventoryVerifier()
        structural = StructuralRetentionInventoryVerifier()
        current = current if current is not None else lambda: None
        backup_ref, schema_ref = _descriptor(backup_ref), _descriptor(schema_ref)
        baseline, plan = _descriptor(result.baseline_ref), _descriptor(result.plan_ref)
        current()
        plan_root_content = await self.store.aload_canonical(plan, run_id=result.run_id, kind="plan")
        current()
        plan_root = decode_inventory_page(
            plan_root_content,
            run_id=result.run_id,
            section="manifest",
            scope="global",
            tenant_id=None,
            page_index=0,
            kind="plan",
        )
        metadata = [record.data for record in plan_root.records if record.record_type == "run"]
        if len(metadata) != 1:
            _blocked("manifest_metadata")
        permissions = PermissionInventoryVerifier(
            run_id=result.run_id,
            writer_contract_version=result.writer_contract_version,
            target_model_checksum=metadata[0]["authorization_model_checksum"],
            catalog_plan_checksum=metadata[0]["catalog_digest"],
            permission_planner=_permission_planner,
        )
        for kind, descriptor in (("baseline", baseline), ("plan", plan)):
            expected_baseline = None if kind == "baseline" else baseline
            seen, indices = set(), {}

            async def verify(
                ref,
                *,
                section="manifest",
                scope="global",
                tenant_id=None,
                page_index=0,
                depth=0,
                record_count=None,
                kind=kind,
                seen=seen,
                indices=indices,
                expected_baseline=expected_baseline,
            ):
                current()
                if scope == "tenant" and tenant_id not in tenants:
                    _blocked("manifest_tenant")
                if depth > 64 or ref["object_key"] in seen:
                    _blocked("manifest_graph")
                seen.add(ref["object_key"])
                if kind == "plan" and depth == 0:
                    content = plan_root_content
                else:
                    content = await self.store.aload_canonical(
                        ref, run_id=result.run_id, kind="sources" if section == "sources" else kind
                    )
                current()
                if section == "sources":
                    page = decode_source_page(content, run_id=result.run_id, tenant_id=tenant_id, page_index=page_index)
                    from bisheng.knowledge.application.unification_reference_state import validate_inventory_fact

                    for record in page.records:
                        validate_inventory_fact(record)
                        structural.observe_source(record)
                else:
                    page = decode_inventory_page(
                        content,
                        run_id=result.run_id,
                        section=section,
                        scope=scope,
                        tenant_id=tenant_id,
                        page_index=page_index,
                        kind=kind,
                    )
                if record_count is not None and len(page.records) != record_count:
                    _blocked("manifest_counter")
                if section != "manifest":
                    if section != "sources":
                        for record in page.records:
                            _section(section, record)
                            memberships.observe(kind=kind, section=section, tenant_id=tenant_id, record=record)
                            permissions.observe(kind=kind, section=section, tenant_id=tenant_id, record=record)
                            physical.observe(kind=kind, section=section, tenant_id=tenant_id, record=record)
                            structural.observe(kind=kind, section=section, tenant_id=tenant_id, record=record)
                    key = (kind, section, scope, tenant_id)
                    if page_index != indices.get(key, 0):
                        _blocked("manifest_page_order")
                    indices[key] = page_index + 1
                    yield FrozenInventoryPage(
                        kind, section, scope, tenant_id, page_index, len(page.records), _descriptor(ref), content
                    )
                    return
                metadata = [record.data for record in page.records if record.record_type == "run"]
                if depth == 0:
                    if len(metadata) != 1:
                        _blocked("manifest_metadata")
                    value = metadata[0]
                    expected = {
                        "writer_contract_version": result.writer_contract_version,
                        "environment": environment,
                        "tenant_count": len(result.tenant_ids),
                        "tenant_inventory_digest": digest(result.tenant_ids),
                        "backup_ref": backup_ref,
                        "schema_ref": schema_ref,
                        "baseline_ref": expected_baseline,
                    }
                    if any(value.get(name) != item for name, item in expected.items()):
                        _blocked("frozen_input_changed")
                    if kind == "baseline":
                        permissions.observe(
                            kind=kind,
                            section="manifest",
                            tenant_id=None,
                            record=next(record for record in page.records if record.record_type == "run"),
                        )
                elif metadata:
                    _blocked("nested_manifest_metadata")
                for record in page.records:
                    if record.record_type == "run":
                        continue
                    if record.record_type != "manifest_entry":
                        _blocked("manifest_entry")
                    entry = record.data
                    async for leaf in verify(
                        entry["descriptor"],
                        section=entry["section"],
                        scope=entry["scope"],
                        tenant_id=entry["tenant_id"],
                        page_index=entry["page_index"],
                        depth=depth + 1,
                        record_count=entry["record_count"],
                    ):
                        yield leaf

            async for leaf in verify(descriptor):
                yield leaf
        memberships.finish()
        permissions.finish()
        physical.finish()
        structural.finish()
        await self._materials(
            run_id=result.run_id,
            writer_contract_version=result.writer_contract_version,
            environment=environment,
            tenant_ids=result.tenant_ids,
            backup_ref=backup_ref,
            schema_ref=schema_ref,
            current=current,
        )

    async def _physical_batch(self, pages, tenant, resources, files, *, session):
        expected_indices = {row.data["id"]: row.data for row in resources}
        file_counts = None
        expected_objects = {
            (tenant, row.data["knowledge_id"], row.data["id"], kind, row.data[field])
            for row in files
            for field, kind in _OBJECT_FIELDS
            if row.data[field]
        }
        async for record in self.physical.aiter_facts(resource_requests=tuple(resources), object_requests=tuple(files)):
            _section("physical", record)
            value = record.data
            if value["tenant_id"] != tenant:
                _blocked("physical_tenant")
            if record.record_type == "physical_index":
                original = expected_indices.pop(value["space_id"], None)
                if (
                    original is None
                    or value["index_name"] != original["index_name"]
                    or value["collection_name"] != original["collection_name"]
                ):
                    _blocked("physical_index_identity")
                if value["identifier_compatible"] is not True:
                    if file_counts is None:
                        file_counts = await self.preflight.resources.acount_resource_files(
                            session, resource_ids=tuple(row.data["id"] for row in resources)
                        )
                    proof = retention_record(
                        resource=original,
                        physical=value,
                        managed_file_count=file_counts[value["space_id"]],
                    )
                    await pages.add("physical", tenant, proof, kind="plan")
            else:
                key = (
                    value["tenant_id"],
                    value["space_id"],
                    value["file_id"],
                    value["object_kind"],
                    value["object_key"],
                )
                if key not in expected_objects:
                    _blocked("physical_object_identity")
                expected_objects.remove(key)
            # Counts, existence and ETag are original facts, not an invented
            # nonempty/equality/content-SHA criterion for legacy indexes.
            await pages.add("physical", tenant, record)
        if expected_indices or expected_objects:
            _blocked("incomplete_physical_inventory")

    async def _tenant(self, session, pages, source_inventory, permission_planner, tenant, identity, planned_at):
        context = await source_inventory.aprepare_tenant_context(session, **identity)
        resource_requests, object_requests = [], []
        spaces = {}
        memberships = MembershipInventoryVerifier()
        retained_creators = {}
        async for section, record in self.preflight.aiter_tenant(
            session, permission_planner=permission_planner, planned_at=planned_at
        ):
            kind = (
                "plan"
                if section in {"conversion", "permission_namespace"} or record.record_type in RETENTIONS
                else "baseline"
            )
            if record.record_type == CREATOR_RETENTION:
                retained_creators[record.data["space_id"]] = record.data["creator_user_id"]
            elif record.record_type == FILE_RETENTION:
                await source_inventory.sharing_reader.aassert_no_file_tuples(
                    session, tenant, file_ids=(record.data["file_id"],)
                )
            memberships.observe(kind=kind, section=section, tenant_id=tenant, record=record)
            await pages.add(section, tenant, record, kind=kind)
            if record.record_type == "resource":
                value = record.data
                spaces[value["id"]] = value["type"]
                if value["type"] in {0, 3}:
                    resource_requests.append(record)
            elif record.record_type == "file" and spaces.get(record.data["knowledge_id"]) in {0, 3}:
                object_requests.append(record)
            if len(resource_requests) == 199 or len(object_requests) == 199:
                await self._physical_batch(pages, tenant, resource_requests, object_requests, session=session)
                resource_requests, object_requests = [], []
        memberships.finish()
        if resource_requests or object_requests:
            await self._physical_batch(pages, tenant, resource_requests, object_requests, session=session)
        header, refs = None, []
        creators = {}
        source_headers = {}
        pending_creators = {}
        batch = []

        def finish_source():
            if header is not None and (
                header.reference_count != len(refs) or header.reference_digest != reference_set_digest(tuple(refs))
            ):
                _blocked("source_reference_set")

        def retained(row):
            from bisheng.knowledge.application.unification_structural_retention import (
                retained_invalid_assistant_creator,
            )

            if type(row) is RootInventoryRecord and retained_invalid_assistant_creator(
                row, source_headers.get(row.root_key)
            ):
                return True
            return (
                type(row) is RootInventoryRecord
                and row.root_key.source_type.value == "knowledge"
                and row.root_key.source_id.isdecimal()
                and retained_creators.get(int(row.root_key.source_id)) == row.creator_id
            )

        async def consume(items):
            wanted = tuple(
                sorted(
                    {row.creator_id for row in items if type(row) is RootInventoryRecord and row.creator_id is not None}
                    - creators.keys()
                )
            )
            for offset in range(0, len(wanted), 200):
                for fact in await self.preflight.controls.ainspect_users(
                    session, user_ids=wanted[offset : offset + 200]
                ):
                    creators[fact.user_id] = fact.exists
                    await pages.add("control", tenant, record_from_row(fact))
            for row in items:
                if type(row) is RootInventoryRecord and row.creator_id is not None:
                    if row.creator_id not in creators:
                        _blocked("source_creator_fact_missing")
                    if not creators[row.creator_id] and not retained(row):
                        if (
                            row.root_key.source_type.value == "assistant"
                            and row.retained_version_count == 1
                            and row.root_key not in source_headers
                        ):
                            # Linked-source pages emit their roots before their
                            # source headers. Defer only until that exact header.
                            pending_creators[row.root_key] = row
                        else:
                            _blocked("source_creator_missing")
                await pages.add("sources", tenant, row)

        async for row in source_inventory.aiter_tenant_source_records(session, **identity, context=context):
            if type(row) is SourceInventoryRecord:
                from bisheng.resource_reference.application.contracts import SourceRootKey

                key = row.source_key
                root_key = SourceRootKey(key.tenant_id, key.source_type, key.source_id)
                source_headers[root_key] = row
                if root_key in pending_creators:
                    if not retained(pending_creators[root_key]):
                        _blocked("source_creator_missing")
                    del pending_creators[root_key]
            if type(row) is ReferenceInventoryRecord:
                if header is None or row.source_key != header.source_key:
                    _blocked("source_header_missing")
                refs.append(ReferenceSpec(row.slot_key, row.target))
                await pages.add("conversion", tenant, source_decision(row, tenant_id=tenant), kind="plan")
            else:
                finish_source()
                header, refs = (row, []) if type(row) is SourceInventoryRecord else (None, [])
            batch.append(row)
            if len(batch) == 199:
                await consume(batch)
                batch = []
        finish_source()
        if batch:
            await consume(batch)
        if pending_creators:
            _blocked("source_creator_missing")

    async def arun(
        self, session: AsyncSession, *, run_id, writer_contract_version, environment, backup_ref, schema_ref
    ) -> FrozenGlobalInventoryResult:
        self.runs._global_scope(session)
        self.runs.assert_inventory_clean(session)
        self.runs._identity(run_id, writer_contract_version)
        if type(environment) is not str or not environment or len(environment) > 128:
            _blocked("environment")
        backup_ref, schema_ref = _descriptor(backup_ref), _descriptor(schema_ref)
        transaction = TransactionIdentity.capture(session)

        def current():
            try:
                transaction.assert_current(session)
            except (TypeError, ValueError):
                _blocked("transaction_changed")

        identity = {"run_id": run_id, "writer_contract_version": writer_contract_version}
        with session.no_autoflush:
            await self.runs.aschema_precheck(session)
            from bisheng.knowledge.domain.repositories.unification_task_repository import UnificationTaskRepository

            await UnificationTaskRepository().avalidate_migration_idle(session)
            tenant_ids = await self.runs.alist_actual_tenant_ids(session)
            existing = await self.runs.aget_global_freeze(session, **identity, tenant_ids=tenant_ids)
            if existing is not None:
                await self._verify_frozen(
                    existing, environment=environment, backup_ref=backup_ref, schema_ref=schema_ref, current=current
                )
                return existing
            if (
                not callable(self.reader_factory)
                or any(
                    not callable(getattr(port, "aiter_facts", None))
                    for port in (self.physical, self.queued, self.broker)
                )
                or not isinstance(self.store, UnificationArtifactStore)
            ):
                raise ReferenceCoverageNotReadyError(reason="migration_required_native_ports_missing")
            await self._materials(
                **identity,
                environment=environment,
                tenant_ids=tenant_ids,
                backup_ref=backup_ref,
                schema_ref=schema_ref,
                current=current,
            )
            await self.raw.avalidate_global_orphans(session)
            await self.raw.avalidate_registered_source_tenants(session)
            await self.preflight.resources.avalidate_global_integrity(session)
            await self.preflight.controls.avalidate_global_integrity(session)
            await self.permissions.avalidate_global_integrity(session)
            catalog = await self.permissions.aload_catalog_baseline(session, environment=environment)
            target_checksum = target_authorization_model_checksum()
            catalog_plan = build_catalog_retirement_plan(
                **identity,
                before=catalog,
                target_model_checksum=target_checksum,
                namespace_type_mappings=(("knowledge_library", "knowledge_space"),),
            )
            permission_planner = ResourceRetirementPlanner(catalog_plan=catalog_plan)
            pages = _Pages(self.store, run_id, current)
            for row in (catalog.release, catalog.authorization, *catalog.actions, *catalog.models):
                await pages.add("catalog", None, record_from_row(row))
            for row in (*catalog_plan.after_actions, *catalog_plan.after_models):
                await pages.add("catalog", None, record_from_row(row), kind="plan")
            for record in catalog_namespace_records(permission_planner):
                await pages.add("permission_namespace", None, record, kind="plan")
            await pages.finish()
            async with self.reader_factory(catalog) as reader:
                if not isinstance(reader, PinnedMigrationPermissionReader) or reader._pin != catalog.authorization:
                    _blocked("actual_pinned_reader_required")
                async for fact in reader.aiter_original_tuples():
                    if type(fact) is not OriginalTupleFact:
                        _blocked("original_tuple_type")
                    await pages.add(
                        "fga",
                        None,
                        record_from_values("fga_tuple", user=fact.user, relation=fact.relation, object=fact.object),
                    )
                source_inventory = UnificationSourceInventory(repository=self.raw, sharing_reader=reader)
                planned_at = unification_now().replace(microsecond=0)
                for tenant in tenant_ids:
                    with tenant_execution_scope(tenant):
                        await self._tenant(
                            session, pages, source_inventory, permission_planner, tenant, identity, planned_at
                        )
                        await pages.finish()
            async for record in self.queued.aiter_facts(tenant_ids=tenant_ids):
                _section("tasks", record)
                if record.record_type == "queued_task_orphan":
                    await pages.add("tasks", None, record)
                    continue
                if record.data["tenant_id"] not in tenant_ids:
                    _blocked("task_tenant")
                await pages.add("tasks", record.data["tenant_id"], record)
            async with aclosing(self.broker.aiter_facts(tenant_ids=tenant_ids)) as broker_stream:
                async for record in broker_stream:
                    current()
                    _section("tasks", record)
                    if record.record_type != "broker_task":
                        _blocked("broker_record_type")
                    tenant = record.data["tenant_id"]
                    if tenant is not None and tenant not in tenant_ids:
                        _blocked("broker_tenant")
                    await pages.add("tasks", tenant, record)
            await pages.finish()
            common = {
                "writer_contract_version": writer_contract_version,
                "environment": environment,
                "tenant_count": len(tenant_ids),
                "tenant_inventory_digest": digest(tenant_ids),
                "backup_ref": backup_ref,
                "schema_ref": schema_ref,
            }
            baseline = await pages.manifest(
                "baseline",
                record_from_values(
                    "run",
                    **common,
                    catalog_digest=catalog.release.checksum,
                    authorization_model_checksum=catalog.authorization.model_checksum,
                    baseline_ref=None,
                ),
            )
            plan = await pages.manifest(
                "plan",
                record_from_values(
                    "run",
                    **common,
                    catalog_digest=catalog_plan.checksum,
                    authorization_model_checksum=target_checksum,
                    baseline_ref=baseline,
                ),
            )
            current()
            candidate = FrozenGlobalInventoryResult(run_id, writer_contract_version, tenant_ids, baseline, plan)
            await self._verify_frozen(
                candidate,
                environment=environment,
                backup_ref=backup_ref,
                schema_ref=schema_ref,
                current=current,
                permission_planner=permission_planner,
            )
            self.runs.assert_inventory_clean(session)
            return await self.runs.afreeze_all(
                session, **identity, tenant_ids=tenant_ids, baseline_ref=baseline, plan_ref=plan
            )
