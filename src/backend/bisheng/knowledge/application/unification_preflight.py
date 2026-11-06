"""Deterministic M2 checks over acquired facts; no binding/ready authority."""

import re
from collections import defaultdict

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.knowledge.application.unification_conversion_plan import ConversionPlanBuilder
from bisheng.knowledge.application.unification_inventory_codec import digest, record_from_row, record_from_values
from bisheng.knowledge.application.unification_sources import ReferenceInventoryRecord
from bisheng.knowledge.domain.repositories.unification_control_repository import UnificationControlRepository
from bisheng.knowledge.domain.repositories.unification_inventory_repository import UnificationInventoryRepository
from bisheng.knowledge.domain.repositories.unification_resource_repository import UnificationResourceRepository
from bisheng.llm.domain.repositories.migration_target_repository import ModelMigrationTargetFact
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.migration.f118_plan import (
    PermissionResourceBaseline,
    _checksum,
    build_resource_retirement_plans,
)


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
            or fact.knowledge_type not in {0, 3}
            or (fact.file_type is not None and fact.file_type not in {0, 1})
        ):
            _blocked("knowledge_physical_parent")
        disposition = "existing_saved_slot"
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
    )


class UnificationPreflight:
    def __init__(self, *, resources=None, controls=None, permissions=None, inventory=None):
        self.resources = resources if resources is not None else UnificationResourceRepository()
        self.inventory = inventory if inventory is not None else UnificationInventoryRepository()
        self.controls = controls if controls is not None else UnificationControlRepository()
        self.permissions = permissions if permissions is not None else PermissionMigrationSnapshotRepository()

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

    async def aiter_tenant(self, session, *, catalog_plan, planned_at):
        tenant = get_current_tenant_id()
        builder = ConversionPlanBuilder(
            run_id=catalog_plan.run_id,
            writer_contract_version=catalog_plan.writer_contract_version,
            planned_at=planned_at,
        )
        tenant_fact = await self.controls.aget_tenant(session)
        yield "control", record_from_row(tenant_fact)
        seen_creators = set()
        spaces, files, departments = {}, {}, set()
        role_keys, relationship_rows = set(), []
        storage_bytes = 0

        async def creator_facts(ids):
            wanted = tuple(sorted(ids - seen_creators))
            for offset in range(0, len(wanted), 200):
                facts = await self.controls.ainspect_users(session, user_ids=wanted[offset : offset + 200])
                for fact in facts:
                    if not fact.exists:
                        _blocked("creator_missing")
                    seen_creators.add(fact.user_id)
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
                if method in {"resources", "files", "documents", "versions", "tags", "tag_links"}:
                    getattr(builder, "add_" + method)(rows)
                creators = set()
                for row in rows:
                    record = record_from_row(row)
                    data = record.data
                    if method == "resources":
                        if row.type not in {0, 1, 2, 3}:
                            _blocked("unknown_knowledge_type")
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
                    if creator is not None:
                        creators.add(creator)
                    yield "resources", record
                async for fact in creator_facts(creators):
                    yield "control", fact

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

        groups = {}
        grants, assignees, visible = defaultdict(list), defaultdict(list), defaultdict(list)
        grant_parent = {}
        for method in ("resource_modes", "grants", "assignees", "visible_sources"):
            after = None
            while True:
                rows = await getattr(self.permissions, "alist_" + method)(session, after_id=after, limit=200)
                for row in rows:
                    yield "permission", record_from_row(row)
                    if method == "resource_modes":
                        key = (row.resource_type, row.resource_id)
                        if key in groups:
                            _blocked("duplicate_permission_mode")
                        groups[key] = row
                    elif method == "grants":
                        key = (row.resource_type, row.resource_id)
                        grants[key].append(row)
                        grant_parent[row.id] = key
                    elif method == "assignees":
                        assignees[row.grant_id].append(row)
                    else:
                        visible[(row.source.resource_type, row.source.resource_id)].append(row)
                if len(rows) < 200:
                    break
                if not rows or (after is not None and rows[-1].id <= after):
                    _blocked("non_advancing_permission_page")
                after = rows[-1].id
        if set(grants) - set(groups) or set(visible) - set(groups) or set(assignees) - set(grant_parent):
            _blocked("permission_parent_missing")
        baselines = (
            PermissionResourceBaseline(
                tenant,
                key[0],
                key[1],
                mode,
                tuple(grants[key]),
                tuple(source for grant in grants[key] for source in assignees[grant.id]),
                tuple(visible[key]),
            )
            for key, mode in groups.items()
        )
        for plan in build_resource_retirement_plans(catalog_plan=catalog_plan, before=baselines):
            original = plan.before
            target_type = original.resource_type
            if (
                original.resource_type == "knowledge_library"
                and original.resource_id.isdecimal()
                and spaces.get(int(original.resource_id), {}).get("type") == 0
            ):
                target_type = "knowledge_space"
            yield (
                "conversion",
                record_from_values(
                    "permission_plan",
                    tenant_id=tenant,
                    resource_type=original.resource_type,
                    resource_id=original.resource_id,
                    target_resource_type=target_type,
                    plan_checksum=plan.checksum,
                    before_digest=_checksum(original),
                    after_grants_digest=_checksum(plan.after_grants),
                    visibility_deltas_digest=_checksum(plan.visibility_deltas),
                    expected_use_changes_digest=_checksum(plan.expected_use_changes),
                ),
            )
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
