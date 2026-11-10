"""Deterministic M2 checks over acquired facts; no binding/ready authority."""

import re

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.knowledge.application.unification_conversion_plan import ConversionPlanBuilder
from bisheng.knowledge.application.unification_inventory_codec import digest, record_from_row, record_from_values
from bisheng.knowledge.application.unification_permission_namespace import (
    PermissionNamespacePlan,
    namespace_plan_records,
)
from bisheng.knowledge.application.unification_sources import ReferenceInventoryRecord
from bisheng.knowledge.domain.repositories.unification_control_repository import (
    CreatorFact,
    UnificationControlRepository,
)
from bisheng.knowledge.domain.repositories.unification_inventory_repository import UnificationInventoryRepository
from bisheng.knowledge.domain.repositories.unification_resource_repository import UnificationResourceRepository
from bisheng.knowledge.domain.repositories.unification_space_membership_repository import (
    SpaceMembershipHeader,
    SpaceMembershipRow,
    UnificationSpaceMembershipRepository,
)
from bisheng.knowledge.domain.services.unification_space_membership_plan import plan_space_creator_membership
from bisheng.llm.domain.repositories.migration_target_repository import ModelMigrationTargetFact
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.migration.f118_plan import ResourceRetirementPlanner


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"migration_preflight_{reason}")


def _path(value):
    if value in (None, ""):
        return ()
    if type(value) is not str:
        _blocked("invalid_ancestor_path")
    parts = tuple(part for part in value.split("/") if part)
    if any(re.fullmatch(r"[1-9][0-9]*", part) is None for part in parts):
        _blocked("invalid_ancestor_path")
    ids = tuple(map(int, parts))
    if len(set(ids)) != len(ids):
        _blocked("ancestor_cycle")
    return ids


def source_decision(record, *, tenant_id):
    if (
        type(record) is not ReferenceInventoryRecord
        or record.source_key.tenant_id != tenant_id
        or record.physical_fact.key != record.target
    ):
        _blocked("source_identity")
    from bisheng.knowledge.application.unification_reference_state import parse_frozen

    state = parse_frozen(record.frozen_state)
    fact = record.physical_fact
    if not fact.exists:
        if record.origin != "explicit_id":
            _blocked("unresolved_name")
        disposition = "initial_missing"
    elif isinstance(fact, ModelMigrationTargetFact):
        if (
            not fact.server_exists
            or fact.target_tenant_id != fact.server_tenant_id
            or fact.target_tenant_id not in {tenant_id, 1}
        ):
            _blocked("model_physical_parent")
        # This records the original numeric slot, not new-bind share authority.
        # Offline and revoked Root sharing remain physically existing facts.
        disposition = "existing_saved_slot"
    else:
        if (
            fact.target_tenant_id != tenant_id
            or not fact.space_exists
            or fact.space_tenant_id != tenant_id
            or fact.knowledge_type not in {0, 1, 3}
            or (fact.file_type is not None and fact.file_type not in {0, 1})
        ):
            _blocked("knowledge_physical_parent")
        disposition = "existing_saved_slot"
    original, direct, ancestors, legacy = (
        state[name] for name in ("original", "target_tombstones", "ancestor_tombstones", "legacy")
    )
    if original is not None and (
        (
            original["tenant_id"],
            original["source_type"],
            original["source_id"],
            original["source_version"],
            original["slot_key"],
            original["target_type"],
            original["target_id"],
        )
        != (
            tenant_id,
            record.source_key.source_type.value,
            record.source_key.source_id,
            record.source_key.source_version,
            record.slot_key,
            record.target.target_type.value,
            record.target.target_id,
        )
        or (
            fact.exists
            and original["target_tenant_id"] is not None
            and original["target_tenant_id"] != fact.target_tenant_id
        )
    ):
        _blocked("original_binding_identity")
    for row in direct:
        if (row["target_type"], row["target_id"]) != (record.target.target_type.value, record.target.target_id):
            _blocked("deletion_target_identity")
    for row in ancestors:
        if (
            record.target.target_type.value != "knowledge_file"
            or row["target_type"] != "knowledge_space"
            or (original is None and not fact.exists)
            or (original is not None and original["target_space_id"] != row["target_id"])
            or (original is None and fact.exists and str(fact.knowledge_id) != row["target_id"])
        ):
            _blocked("deletion_ancestor_identity")
    # Direct evidence never shadows an unfinished or foreign ancestor delete.
    # Both rows can legitimately remain after two completed operations, but
    # every frozen deletion must agree on the one physical target owner.
    if len(direct) > 1 or len(ancestors) > 1:
        _blocked("deletion_owner_conflict")
    deletions = (*direct, *ancestors)
    if any(row["stage"] != "deleted" for row in deletions):
        _blocked("deletion_incomplete")
    if len({row["target_tenant_id"] for row in deletions}) > 1:
        _blocked("deletion_owner_conflict")
    if (
        original is not None
        and fact.exists
        and record.target.target_type.value == "knowledge_file"
        and (original["target_space_id"] != str(fact.knowledge_id))
    ):
        _blocked("original_file_parent_metadata")
    if legacy is not None:
        if (
            fact.exists
            or original is None
            or direct
            or (original["legacy_invalid_reason"], original["legacy_run_id"], original["legacy_evidence_key"])
            != ("target_missing", legacy["run_id"], legacy["evidence_key"])
        ):
            _blocked("original_legacy_conflict")
        disposition = "existing_invalid_legacy"
    elif original is not None and original["legacy_invalid_reason"] is not None:
        _blocked("original_legacy_proof_missing")
    elif direct or ancestors:
        evidence = direct or ancestors
        if len(evidence) != 1:
            _blocked("deletion_owner_conflict")
        row = evidence[0]
        if (
            (fact.exists and row["stage"] == "deleted")
            or (fact.exists and row["target_tenant_id"] != fact.target_tenant_id)
            or (
                original is not None
                and original["target_tenant_id"] is not None
                and original["target_tenant_id"] != row["target_tenant_id"]
            )
            or (
                not direct
                and (
                    (not fact.exists and original is None)
                    or (original is not None and original["target_space_id"] != row["target_id"])
                    or (fact.exists and str(fact.knowledge_id) != row["target_id"])
                )
            )
        ):
            _blocked("deletion_physical_conflict")
        disposition = "existing_invalid_deleted"
    elif original is not None and not fact.exists:
        _blocked("original_missing_without_evidence")
    return record_from_values(
        "source_decision",
        tenant_id=tenant_id,
        source_type=record.source_key.source_type.value,
        source_id=record.source_key.source_id,
        source_version=record.source_key.source_version,
        slot_key=record.slot_key,
        target_type=record.target.target_type.value,
        target_id=record.target.target_id,
        exists=fact.exists,
        disposition=disposition,
        revision_digest=fact.revision_digest,
        frozen_state_digest=digest(state),
    )


class UnificationPreflight:
    def __init__(self, *, resources=None, controls=None, permissions=None, inventory=None, memberships=None):
        self.resources = resources if resources is not None else UnificationResourceRepository()
        self.inventory = inventory if inventory is not None else UnificationInventoryRepository()
        self.controls = controls if controls is not None else UnificationControlRepository()
        self.permissions = permissions if permissions is not None else PermissionMigrationSnapshotRepository()
        self.memberships = memberships if memberships is not None else UnificationSpaceMembershipRepository()

    @staticmethod
    async def _pages(repository, method, session):
        after = None
        while True:
            page = await getattr(repository, method)(
                session, **{"after_key" if method == "alist_user_roles" else "after_id": after}, limit=200
            )
            if len(page.items) > 200:
                _blocked("invalid_page")
            yield page.items
            if page.next_after is None:
                return
            expected = (
                (page.items[-1].user_id, page.items[-1].role_id, page.items[-1].id)
                if method == "alist_user_roles" and page.items
                else page.items[-1].id
                if page.items
                else None
            )
            if not page.items or page.next_after != expected:
                _blocked("non_advancing_page")
            if after is not None and page.next_after <= after:
                _blocked("non_advancing_page")
            after = page.next_after

    async def _membership_batch(self, session, rows, after_id):
        selected = tuple(row for row in rows if row.type in (0, 3))
        if not selected:
            return (), {}, after_id
        page = await self.memberships.apage_headers(session, after_id=after_id, limit=len(selected))
        if (
            any(type(row) is not SpaceMembershipHeader for row in page.items)
            or tuple(row.knowledge_id for row in page.items) != tuple(row.id for row in selected)
            or (page.next_after is not None and page.next_after != page.items[-1].knowledge_id)
        ):
            _blocked("membership_headers_incomplete")
        for header, resource in zip(page.items, selected, strict=True):
            if (header.tenant_id, header.knowledge_type, header.creator_user_id) != (
                resource.tenant_id,
                resource.type,
                resource.user_id,
            ):
                _blocked("membership_header_resource_changed")
        by_root = {row.id: [] for row in selected}
        after = None
        while True:
            members = await self.memberships.apage_members(
                session, knowledge_ids=tuple(by_root), after_id=after, limit=200
            )
            if len(members.items) > 200:
                _blocked("membership_page_limit")
            for member in members.items:
                if type(member) is not SpaceMembershipRow or member.knowledge_id not in by_root:
                    _blocked("membership_parent_changed")
                by_root[member.knowledge_id].append(member)
            if members.next_after is None:
                break
            if (
                not members.items
                or members.next_after != members.items[-1].id
                or (after is not None and members.next_after <= after)
            ):
                _blocked("membership_page_not_advancing")
            after = members.next_after
        return page.items, by_root, page.items[-1].knowledge_id

    async def aiter_tenant(self, session, *, permission_planner: ResourceRetirementPlanner, planned_at):
        tenant = get_current_tenant_id()
        namespace = PermissionNamespacePlan(permission_planner=permission_planner)
        catalog_plan = permission_planner.catalog_plan
        builder = ConversionPlanBuilder(
            run_id=catalog_plan.run_id,
            writer_contract_version=catalog_plan.writer_contract_version,
            planned_at=planned_at,
        )
        tenant_fact = await self.controls.aget_tenant(session)
        yield "control", record_from_row(tenant_fact)
        seen_creators = {}
        member_after = None
        spaces, files, departments = {}, {}, set()
        role_keys, relationship_rows = set(), []
        storage_bytes = 0

        async def creator_facts(ids):
            wanted = tuple(sorted(ids - seen_creators.keys()))
            for offset in range(0, len(wanted), 200):
                facts = await self.controls.ainspect_users(session, user_ids=wanted[offset : offset + 200])
                for fact in facts:
                    if type(fact) is not CreatorFact or fact.user_id not in wanted or fact.exists is not True:
                        _blocked("creator_missing")
                    seen_creators[fact.user_id] = fact
                    yield record_from_row(fact)

        for method in (
            "resources",
            "files",
            "documents",
            "versions",
            "qa",
            "tags",
            "tag_links",
            "tag_libraries",
            "department_spaces",
        ):
            async for rows in self._pages(self.resources, "alist_" + method, session):
                if method == "resources":
                    headers, member_rows, member_after = await self._membership_batch(session, rows, member_after)
                    wanted = {row.creator_user_id for row in headers if row.creator_user_id is not None}
                    async for fact in creator_facts(wanted):
                        yield "control", fact
                    membership_plans = []
                    for header in headers:
                        original_members = tuple(member_rows[header.knowledge_id])
                        plan = plan_space_creator_membership(
                            header, original_members, seen_creators.get(header.creator_user_id), planned_at=planned_at
                        )
                        if plan is not None:
                            membership_plans.append(plan)
                        yield "control", record_from_row(header)
                        for member in original_members:
                            yield "control", record_from_row(member)
                    builder.add_resources(rows, creator_memberships=tuple(membership_plans))
                elif method in {"files", "documents", "versions", "tags", "tag_links"}:
                    getattr(builder, "add_" + method)(rows)
                creators = set()
                for row in rows:
                    record = record_from_row(row)
                    data = record.data
                    if method == "resources":
                        if row.type not in {0, 1, 2, 3}:
                            _blocked("unknown_knowledge_type")
                        if row.type == 0 and row.user_id is None:
                            _blocked("creator_missing")
                        spaces[row.id] = data
                    elif method == "files":
                        if row.file_type not in {0, 1} or row.knowledge_id not in spaces:
                            _blocked("invalid_file_parent")
                        files[row.id] = {
                            name: data[name] for name in ("id", "knowledge_id", "file_type", "level", "file_level_path")
                        }
                        if row.file_source in {"channel", "space_upload"}:
                            storage_bytes += row.file_size or 0
                    elif method == "department_spaces":
                        departments.add(row.space_id)
                        if row.space_id not in spaces:
                            _blocked("department_space_parent")
                    creator = getattr(row, "user_id", getattr(row, "created_by", None))
                    # F038 seeded public builtin libraries with the system
                    # sentinel 0. Preserve that original row, not a User(0).
                    system_library = (
                        method == "tag_libraries"
                        and type(creator) is int
                        and creator == 0
                        and row.is_builtin is True
                        and row.owner_knowledge_id is None
                    )
                    if creator is not None and not system_library:
                        creators.add(creator)
                    namespace.observe(section="resources", tenant_id=tenant, record=record)
                    yield "resources", record
                async for fact in creator_facts(creators):
                    yield "control", fact
            if method == "resources":
                tail = await self.memberships.apage_headers(session, after_id=member_after, limit=1)
                if tail.items or tail.next_after is not None:
                    _blocked("membership_resource_missing")

        ancestors = set()
        for item in files.values():
            path = _path(item["file_level_path"])
            if item["id"] in path or (
                item["level"] is not None
                and (type(item["level"]) is not int or item["level"] < 0 or item["level"] != len(path))
            ):
                _blocked("invalid_file_depth")
            ancestors.update(path)
        facts = {}
        ordered = tuple(sorted(ancestors))
        for offset in range(0, len(ordered), 200):
            facts.update(
                (fact.id, fact)
                for fact in await self.resources.ainspect_file_ancestors(
                    session, file_ids=ordered[offset : offset + 200]
                )
            )
        for item in files.values():
            path = _path(item["file_level_path"])
            for index, ident in enumerate(path):
                parent = facts[ident]
                if (
                    not parent.exists
                    or parent.tenant_id != tenant
                    or parent.knowledge_id != item["knowledge_id"]
                    or parent.file_type != 0
                    or _path(parent.file_level_path) != path[:index]
                    or (parent.level is not None and parent.level != index)
                ):
                    _blocked("invalid_ancestor_parent")

        async for rows in self._pages(self.inventory, "alist_model_defaults", session):
            builder.add_defaults(rows)
        for command in builder.finish():
            yield "conversion", record_from_row(command)

        for method in ("memberships", "departments", "roles", "user_roles"):
            async for rows in self._pages(self.controls, "alist_" + method, session):
                for row in rows:
                    if method == "roles":
                        role_keys.add(row.id)
                    elif method == "user_roles":
                        relationship_rows.append(row)
                    yield "control", record_from_row(row)
        other_roles = tuple(sorted({row.role_id for row in relationship_rows} - role_keys))
        for offset in range(0, len(other_roles), 200):
            for fact in await self.controls.ainspect_roles(session, role_ids=other_roles[offset : offset + 200]):
                if not fact.exists:
                    _blocked("role_parent_missing")
                yield "control", record_from_row(fact)

        for method in ("resource_modes", "grants", "assignees", "visible_sources"):
            after = None
            while True:
                rows = await getattr(self.permissions, "alist_" + method)(session, after_id=after, limit=200)
                for row in rows:
                    record = record_from_row(row)
                    namespace.observe(section="permission", tenant_id=tenant, record=record)
                    yield "permission", record
                if len(rows) < 200:
                    break
                if not rows or (after is not None and rows[-1].id <= after):
                    _blocked("non_advancing_permission_page")
                after = rows[-1].id
        for plan in namespace.finish():
            for section, record in namespace_plan_records(plan):
                yield section, record
        yield (
            "control",
            record_from_values(
                "quota_usage",
                tenant_id=tenant,
                personal_space_count=sum(
                    row["type"] == 3 and ident not in departments for ident, row in spaces.items()
                ),
                department_space_count=sum(row["type"] == 3 and ident in departments for ident, row in spaces.items()),
                stored_bytes=storage_bytes,
                configuration_digest=digest(tenant_fact.quota_config),
            ),
        )
