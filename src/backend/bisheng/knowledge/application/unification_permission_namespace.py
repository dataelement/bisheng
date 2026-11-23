"""Pure native namespace facts and closed M2 records, without write authority."""

import re
from collections import defaultdict
from dataclasses import replace
from datetime import datetime

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_inventory_codec import (
    InventoryRecord,
    record_from_row,
    record_from_values,
)
from bisheng.permission.domain.schemas import VisibleSourceProjectionDTO
from bisheng.permission.domain.services.catalog_policy import CatalogAction
from bisheng.permission.migration import f118_plan as permission

_MAPPING = (("knowledge_library", "knowledge_space"),)
_KNOWLEDGE = frozenset({"knowledge_library", "knowledge_space", "folder", "knowledge_file"})
_CATALOG = {
    "catalog_release": permission.CatalogReleaseBaseline,
    "authorization": permission.AuthorizationPinBaseline,
    "catalog_action": CatalogAction,
    "permission_model": permission.PermissionModelBaseline,
}
_ROWS = _CATALOG | {
    "resource_mode": permission.ResourceModeBaseline,
    "grant": permission.PermissionGrantBaseline,
    "assignee": permission.PermissionAssigneeBaseline,
    "visible_source": permission.PermissionVisibleSourceBaseline,
}
_ALIASES = {
    "namespace_target_mode": "resource_mode",
    "namespace_after_grant": "grant",
    "namespace_after_assignee": "assignee",
    "namespace_after_visible_source": "visible_source",
}


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason="permission_namespace_" + reason)


def restore_permission_row(record: InventoryRecord):
    """Restore only original typed columns and prove their exact wire roundtrip."""
    if type(record) is not InventoryRecord:
        _blocked("record_type")
    tag = _ALIASES.get(record.record_type, record.record_type)
    if tag not in _ROWS:
        _blocked("unknown_row")
    values = record.data
    if record.record_type in _ALIASES:
        values.pop("mode_id")
    original = record_from_values(tag, **values)
    try:
        if tag == "catalog_release":
            for name in ("expires_at", "published_at"):
                if values[name] is not None:
                    values[name] = datetime.fromisoformat(values[name])
        elif tag == "catalog_action":
            values["resource_types"] = frozenset(values["resource_types"])
        elif tag == "permission_model":
            for name in ("selected_action_codes", "effective_action_codes", "visibility_only_resource_types"):
                values[name] = tuple(values[name])
        elif tag == "visible_source":
            values["source"] = VisibleSourceProjectionDTO.model_validate(values["source"])
        row = _ROWS[tag](**values)
        if record_from_row(row) != original:
            _blocked("row_roundtrip")
        return row
    except (TypeError, ValueError, KeyError) as error:
        raise KnowledgeOperationPlanConflictError(reason="permission_namespace_invalid_typed_row") from error


def catalog_from_records(records):
    groups = {tag: [] for tag in _CATALOG}
    for record in records:
        if type(record) is not InventoryRecord or record.record_type not in groups:
            _blocked("catalog_record")
        groups[record.record_type].append(restore_permission_row(record))
    if (
        len(groups["catalog_release"]) != 1
        or len(groups["authorization"]) != 1
        or not groups["catalog_action"]
        or not groups["permission_model"]
        or len({row.code for row in groups["catalog_action"]}) != len(groups["catalog_action"])
        or len({row.id for row in groups["permission_model"]}) != len(groups["permission_model"])
        or len({row.model_key for row in groups["permission_model"]}) != len(groups["permission_model"])
    ):
        _blocked("catalog_incomplete_or_duplicate")
    return permission.PermissionCatalogBaseline(
        groups["catalog_release"][0],
        groups["authorization"][0],
        tuple(groups["catalog_action"]),
        tuple(groups["permission_model"]),
    )


def _catalog(planner):
    if (
        not isinstance(planner, permission.ResourceRetirementPlanner)
        or planner.catalog_plan.namespace_type_mappings != _MAPPING
    ):
        _blocked("compiled_namespace_required")
    return planner.catalog_plan


def catalog_namespace_records(permission_planner):
    plan = _catalog(permission_planner)
    header = record_from_values(
        "namespace_catalog",
        run_id=plan.run_id,
        writer_contract_version=plan.writer_contract_version,
        before_catalog_checksum=plan.before.release.checksum,
        target_model_checksum=plan.target_model_checksum,
        catalog_plan_checksum=plan.checksum,
        action_checksum=plan.action_checksum,
        model_checksum=plan.model_checksum,
        from_resource_type="knowledge_library",
        to_resource_type="knowledge_space",
        model_count=len(plan.before.models),
    )
    return (
        header,
        *(
            record_from_values(
                "namespace_applicability",
                catalog_plan_checksum=plan.checksum,
                model_key=row.model_key,
                from_resource_type=row.from_resource_type,
                to_resource_type=row.to_resource_type,
                before_action_codes=list(row.before_action_codes),
                after_action_codes=list(row.after_action_codes),
                reason=row.reason,
            )
            for row in plan.namespace_applicability_changes
        ),
    )


def permission_plan_record(plan):
    if type(plan) is not permission.ResourceRetirementPlan or plan.namespace_target is None or plan.after is None:
        _blocked("complete_namespace_plan_required")
    return record_from_values(
        "permission_plan",
        tenant_id=plan.before.tenant_id,
        resource_type=plan.before.resource_type,
        resource_id=plan.before.resource_id,
        target_resource_type=plan.namespace_target.resource_type,
        plan_checksum=plan.checksum,
        before_digest=permission._checksum(plan.before),
        after_grants_digest=permission._checksum(plan.after_grants),
        visibility_deltas_digest=permission._checksum(plan.visibility_deltas),
        expected_use_changes_digest=permission._checksum(plan.expected_use_changes),
        mode_id=plan.before.mode.id,
        catalog_plan_checksum=plan.catalog_plan.checksum,
        target_mode_digest=permission._checksum(plan.namespace_target),
        after_digest=permission._checksum(plan.after),
        grant_count=len(plan.after.grants),
        assignee_count=len(plan.after.assignees),
        visible_source_count=len(plan.after.visible_sources),
    )


def namespace_plan_records(plan):
    header = permission_plan_record(plan)
    for tag, rows in (
        ("namespace_target_mode", (plan.namespace_target,)),
        ("namespace_after_grant", plan.after.grants),
        ("namespace_after_assignee", plan.after.assignees),
        ("namespace_after_visible_source", plan.after.visible_sources),
    ):
        for row in rows:
            yield (
                "permission_namespace",
                record_from_values(tag, mode_id=plan.before.mode.id, **record_from_row(row).data),
            )
    yield "conversion", header


def _numeric(value):
    if type(value) is not str or re.fullmatch(r"[1-9][0-9]*", value) is None:
        _blocked("noncanonical_knowledge_id")
    return int(value)


class PermissionNamespacePlan:
    """One tenant's acquired physical facts; the planner alone is run-wide."""

    def __init__(self, *, permission_planner):
        _catalog(permission_planner)
        self._planner, self._tenant, self._finished = permission_planner, None, False
        self._roots, self._files, self._modes, self._mode_ids = {}, {}, {}, set()
        self._grants, self._assignees, self._visible = defaultdict(list), defaultdict(list), defaultdict(list)
        self._grant_parents, self._assignee_ids, self._visible_ids = {}, set(), set()

    def observe(self, *, section, tenant_id, record):
        if self._finished or type(record) is not InventoryRecord:
            _blocked("invalid_stream")
        tag = record.record_type
        if tag not in {"resource", "file", "resource_mode", "grant", "assignee", "visible_source"}:
            return
        data = record.data
        owner = data["source"]["tenant_id"] if tag == "visible_source" else data["tenant_id"]
        if (
            type(tenant_id) is not int
            or tenant_id <= 0
            or owner != tenant_id
            or (self._tenant is not None and self._tenant != tenant_id)
            or section != ("resources" if tag in {"resource", "file"} else "permission")
        ):
            _blocked("original_record_scope")
        self._tenant = tenant_id
        if tag in {"resource", "file"}:
            index = self._roots if tag == "resource" else self._files
            if data["id"] in index:
                _blocked("duplicate_physical_row")
            index[data["id"]] = data["type"] if tag == "resource" else (data["knowledge_id"], data["file_type"])
            return
        row = restore_permission_row(record)
        if tag == "resource_mode":
            key = row.resource_type, row.resource_id
            if key in self._modes or row.id in self._mode_ids:
                _blocked("duplicate_mode")
            self._modes[key] = row
            self._mode_ids.add(row.id)
        elif tag == "grant":
            if row.id in self._grant_parents:
                _blocked("duplicate_grant")
            key = row.resource_type, row.resource_id
            self._grant_parents[row.id] = key
            self._grants[key].append(row)
        elif tag == "assignee":
            if row.id in self._assignee_ids:
                _blocked("duplicate_assignee")
            self._assignee_ids.add(row.id)
            self._assignees[row.grant_id].append(row)
        else:
            if row.id in self._visible_ids:
                _blocked("duplicate_visible_source")
            self._visible_ids.add(row.id)
            self._visible[(row.source.resource_type, row.source.resource_id)].append(row)

    def _target(self, mode):
        kind, ident = mode.resource_type, mode.resource_id
        if kind not in _KNOWLEDGE:
            return mode, None
        ident = _numeric(ident)
        if kind in {"knowledge_library", "knowledge_space"}:
            physical = self._roots.get(ident)
            if physical not in ({0, 1, 2} if kind == "knowledge_library" else {3}):
                _blocked("original_container_mismatch")
            if physical == 0:
                if mode.mode != "CUSTOM" or mode.parent_type is not None or mode.parent_id is not None:
                    _blocked("normal_root_mode_invalid")
                return replace(mode, resource_type="knowledge_space"), ident
            return mode, ident
        file = self._files.get(ident)
        if file is None or file[1] != (0 if kind == "folder" else 1) or file[0] not in self._roots:
            _blocked("original_file_mismatch")
        root, _ = file
        root_type = self._roots[root]
        if root_type not in {0, 1, 2, 3}:
            _blocked("file_root_kind")
        if mode.parent_type in {"knowledge_library", "knowledge_space"}:
            if mode.parent_id != str(root) or root_type not in (
                {0, 1, 2} if mode.parent_type == "knowledge_library" else {3}
            ):
                _blocked("file_root_parent_mismatch")
            if root_type == 0:
                return replace(mode, parent_type="knowledge_space"), root
        elif mode.parent_type == "folder":
            parent = self._files.get(_numeric(mode.parent_id))
            if parent != (root, 0):
                _blocked("folder_parent_mismatch")
        else:
            _blocked("unknown_file_parent")
        return mode, root

    def finish(self):
        if self._finished:
            _blocked("stream_already_finished")
        self._finished = True
        if (
            set(self._grants) - self._modes.keys()
            or set(self._visible) - self._modes.keys()
            or set(self._assignees) - self._grant_parents.keys()
        ):
            _blocked("original_permission_parent_missing")
        for ident, kind in self._roots.items():
            if kind not in {0, 1, 2, 3}:
                _blocked("unknown_root_kind")
            if kind == 0 and ("knowledge_library", str(ident)) not in self._modes:
                _blocked("normal_root_mode_missing")
        targets, roots, edges = [], {}, {}
        for key, mode in self._modes.items():
            target, root = self._target(mode)
            targets.append(target)
            roots[key] = root
        for key, mode in self._modes.items():
            if mode.parent_type is not None:
                parent = mode.parent_type, mode.parent_id
                if parent not in self._modes:
                    _blocked("original_mode_parent_missing")
                if roots[key] != roots[parent]:
                    _blocked("cross_root_or_unknown_knowledge_parent")
                edges[key] = parent
        done = set()
        for key in edges:
            path, current = set(), key
            while current not in done:
                if current in path:
                    _blocked("original_mode_cycle")
                path.add(current)
                if current not in edges:
                    break
                current = edges[current]
            done.update(path)
        before = (
            permission.PermissionResourceBaseline(
                self._tenant,
                key[0],
                key[1],
                mode,
                tuple(self._grants[key]),
                tuple(source for grant in self._grants[key] for source in self._assignees[grant.id]),
                tuple(self._visible[key]),
            )
            for key, mode in self._modes.items()
        )
        return self._planner.build_many(before=before, target_modes=iter(targets))
