"""Verify frozen namespace semantics without SQL, FGA, or write authority.

Only the active tenant retains full original permission facts. Completed modes
retain small expected headers; plan after rows retain one mode at a time.
"""

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_inventory_codec import InventoryRecord, record_from_row
from bisheng.knowledge.application.unification_permission_namespace import (
    PermissionNamespacePlan,
    catalog_from_records,
    catalog_namespace_records,
    permission_plan_record,
    restore_permission_row,
)
from bisheng.permission.migration.f118_plan import (
    PermissionResourceBaseline,
    ResourceRetirementPlanner,
    _checksum,
    build_catalog_retirement_plan,
)

_CATALOG = {"catalog_release", "authorization", "catalog_action", "permission_model"}
_PERMISSION = {"resource_mode", "grant", "assignee", "visible_source"}
_AFTER = {
    "namespace_after_grant": 0,
    "namespace_after_assignee": 1,
    "namespace_after_visible_source": 2,
}


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason="permission_inventory_" + reason)


class PermissionInventoryVerifier:
    def __init__(
        self,
        *,
        run_id,
        writer_contract_version,
        target_model_checksum,
        catalog_plan_checksum,
        permission_planner=None,
    ):
        self.run_id, self.writer = run_id, writer_contract_version
        self.target_checksum, self.catalog_checksum = target_model_checksum, catalog_plan_checksum
        if permission_planner is not None and type(permission_planner) is not ResourceRetirementPlanner:
            _blocked("invalid_compiled_planner")
        self._supplied_planner = permission_planner
        self._baseline_catalog, self._baseline_metadata = [], None
        self._planner, self._collector, self._tenant = None, None, None
        self._tenants, self._summaries = set(), {}
        self._expected_catalog, self._expected_namespace = (), ()
        self._catalog_position, self._namespace_position = 0, 0
        self._mode, self._after = None, None
        self._mode_seen, self._header_seen = set(), set()
        self._phase, self._finished, self._after_stage = "baseline", False, -1

    def _compile(self):
        if self._planner is not None:
            return
        if self._baseline_metadata is None:
            _blocked("missing_original_metadata")
        before = catalog_from_records(self._baseline_catalog)
        metadata = self._baseline_metadata
        if (
            metadata["writer_contract_version"] != self.writer
            or metadata["catalog_digest"] != before.release.checksum
            or metadata["authorization_model_checksum"] != before.authorization.model_checksum
        ):
            _blocked("original_catalog_metadata_changed")
        if self._supplied_planner is None:
            plan = build_catalog_retirement_plan(
                run_id=self.run_id,
                writer_contract_version=self.writer,
                before=before,
                target_model_checksum=self.target_checksum,
                namespace_type_mappings=(("knowledge_library", "knowledge_space"),),
            )
        else:
            plan = self._supplied_planner.catalog_plan
            if (
                plan.before != before
                or plan.run_id != self.run_id
                or plan.writer_contract_version != self.writer
                or plan.target_model_checksum != self.target_checksum
                or plan.namespace_type_mappings != (("knowledge_library", "knowledge_space"),)
            ):
                _blocked("compiled_original_changed")
        if plan.checksum != self.catalog_checksum:
            _blocked("catalog_plan_changed")
        self._planner = self._supplied_planner or ResourceRetirementPlanner(catalog_plan=plan)
        self._expected_catalog = tuple(record_from_row(row) for row in (*plan.after_actions, *plan.after_models))
        self._expected_namespace = catalog_namespace_records(self._planner)
        self._baseline_catalog = []

    def _close_tenant(self):
        if self._collector is None:
            return
        for plan in self._collector.finish():
            mode_id = plan.before.mode.id
            if mode_id in self._summaries:
                _blocked("duplicate_original_mode")
            self._summaries[mode_id] = permission_plan_record(plan).data
        self._collector, self._tenant = None, None

    def _baseline(self, section, tenant, record):
        tag = record.record_type
        if tag == "run":
            if section != "manifest" or tenant is not None or self._baseline_metadata is not None:
                _blocked("original_metadata_scope")
            self._baseline_metadata = record.data
            return
        if tag in _CATALOG:
            if section != "catalog" or tenant is not None or self._planner is not None:
                _blocked("late_or_scoped_catalog")
            self._baseline_catalog.append(record)
            return
        relevant = (section == "resources" and tag in {"resource", "file"}) or (
            section == "permission" and tag in _PERMISSION
        )
        if not relevant:
            if tag in _PERMISSION or tag in {"resource", "file"}:
                _blocked("original_record_section")
            return
        self._compile()
        if type(tenant) is not int or tenant <= 0:
            _blocked("original_tenant")
        if tenant != self._tenant:
            self._close_tenant()
            if tenant in self._tenants:
                _blocked("reopened_original_tenant")
            self._tenants.add(tenant)
            self._tenant = tenant
            self._collector = PermissionNamespacePlan(permission_planner=self._planner)
        self._collector.observe(section=section, tenant_id=tenant, record=record)

    def _close_mode(self):
        if self._mode is None:
            return
        mode_id, target = self._mode
        summary = self._summaries[mode_id]
        grants, assignees, visible = self._after
        after = PermissionResourceBaseline(
            target.tenant_id,
            target.resource_type,
            target.resource_id,
            target,
            tuple(grants),
            tuple(assignees),
            tuple(visible),
        )
        if (
            _checksum(target) != summary["target_mode_digest"]
            or _checksum(after) != summary["after_digest"]
            or tuple(map(len, self._after))
            != (summary["grant_count"], summary["assignee_count"], summary["visible_source_count"])
        ):
            _blocked("incomplete_or_changed_after")
        self._mode, self._after, self._after_stage = None, None, -1

    def _global_plan(self, section, tenant, record):
        if tenant is not None:
            _blocked("global_plan_scope")
        if section == "catalog":
            expected, position = self._expected_catalog, self._catalog_position
            if position >= len(expected) or record != expected[position]:
                _blocked("target_catalog_changed")
            self._catalog_position += 1
        else:
            expected, position = self._expected_namespace, self._namespace_position
            if position >= len(expected) or record != expected[position]:
                _blocked("namespace_catalog_or_matrix_changed")
            self._namespace_position += 1

    def _plan(self, section, tenant, record):
        tag, data = record.record_type, record.data
        if section == "catalog" or tag in {"namespace_catalog", "namespace_applicability"}:
            expected_section = "catalog" if tag in {"catalog_action", "permission_model"} else "permission_namespace"
            if section != expected_section or self._mode_seen:
                _blocked("late_or_wrong_global_plan")
            self._global_plan(section, tenant, record)
            return
        if tag == "permission_plan":
            mode_id = data["mode_id"]
            expected = self._summaries.get(mode_id)
            if (
                section != "conversion"
                or mode_id in self._header_seen
                or expected is None
                or tenant != expected["tenant_id"]
                or data != expected
            ):
                _blocked("permission_summary_changed")
            self._header_seen.add(mode_id)
            return
        if not tag.startswith("namespace_"):
            return
        if section != "permission_namespace":
            _blocked("namespace_section")
        if self._catalog_position != len(self._expected_catalog) or self._namespace_position != len(
            self._expected_namespace
        ):
            _blocked("missing_global_plan")
        mode_id = data["mode_id"]
        expected = self._summaries.get(mode_id)
        if expected is None or tenant != expected["tenant_id"]:
            _blocked("unknown_or_foreign_mode")
        if tag == "namespace_target_mode":
            self._close_mode()
            if mode_id in self._mode_seen or data["id"] != mode_id:
                _blocked("duplicate_target_mode")
            self._mode_seen.add(mode_id)
            target = restore_permission_row(record)
            if target.tenant_id != tenant:
                _blocked("target_tenant")
            self._mode, self._after = (mode_id, target), ([], [], [])
        elif tag in _AFTER:
            stage = _AFTER[tag]
            if self._mode is None or self._mode[0] != mode_id or stage < self._after_stage:
                _blocked("after_group_or_order")
            row = restore_permission_row(record)
            actual_tenant = row.source.tenant_id if tag == "namespace_after_visible_source" else row.tenant_id
            if actual_tenant != tenant:
                _blocked("after_tenant")
            self._after_stage = stage
            self._after[stage].append(row)
        else:
            _blocked("unknown_namespace_record")

    def observe(self, *, kind, section, tenant_id, record):
        if self._finished or type(record) is not InventoryRecord or kind not in {"baseline", "plan"}:
            _blocked("invalid_stream")
        _ = record.data
        if kind == "baseline":
            if self._phase != "baseline":
                _blocked("late_baseline")
            self._baseline(section, tenant_id, record)
        else:
            if self._phase == "baseline":
                self._compile()
                self._close_tenant()
                self._phase = "plan"
            self._plan(section, tenant_id, record)

    def finish(self):
        if self._finished:
            _blocked("already_finished")
        self._compile()
        self._close_tenant()
        self._close_mode()
        if (
            self._catalog_position != len(self._expected_catalog)
            or self._namespace_position != len(self._expected_namespace)
            or self._mode_seen != self._summaries.keys()
            or self._header_seen != self._summaries.keys()
        ):
            _blocked("incomplete_plan")
        self._finished = True
