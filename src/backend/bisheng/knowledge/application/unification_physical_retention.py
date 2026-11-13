"""Prove preservation of an opaque old index with no managed SQL files.

Retaining physical history does not certify its identifier schema, reconstruct
files, create permissions, or authorize index writes. The original resource
binding and native schema/count facts remain in the immutable baseline.
"""

from collections import Counter

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_inventory_codec import digest, record_from_values


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason="migration_physical_retention_" + reason)


def retention_record(*, resource, physical, managed_file_count):
    if (
        type(managed_file_count) is not int
        or managed_file_count != 0
        or physical["identifier_compatible"] is not False
        or resource["type"] not in {0, 3}
        or (physical["tenant_id"], physical["space_id"]) != (resource["tenant_id"], resource["id"])
        or (physical["index_name"], physical["collection_name"])
        != (resource["index_name"], resource["collection_name"])
        or not (physical["es_exists"] or physical["milvus_exists"])
    ):
        _blocked("empty_original_resource_required")
    return record_from_values(
        "physical_index_retention",
        tenant_id=resource["tenant_id"],
        space_id=resource["id"],
        reason="preserve_legacy_index_without_managed_files",
        managed_file_count=managed_file_count,
        resource_digest=digest(resource),
        physical_fact_digest=digest(physical),
    )


class PhysicalRetentionInventoryVerifier:
    """Validate the same closed proof on freeze, resume and M3 consumption."""

    def __init__(self, *, policy="legacy_physical"):
        if policy not in {"legacy_physical", "bindings_only"}:
            _blocked("unknown_policy")
        self.policy = policy
        self.resources = {}
        self.files = Counter()
        self.physical = {}
        self.retained = {}

    @staticmethod
    def _add(rows, key, value):
        if key in rows:
            _blocked("duplicate_record")
        rows[key] = value

    def observe(self, *, kind, section, tenant_id, record):
        if section == "physical" and self.policy == "bindings_only":
            _blocked("unexpected_physical_inventory")
        tag = record.record_type
        if tag not in {"resource", "file", "physical_index", "physical_index_retention"}:
            return
        value = record.data
        if value["tenant_id"] != tenant_id:
            _blocked("tenant_changed")
        if tag in {"resource", "file"}:
            if kind != "baseline" or section != "resources":
                _blocked("resource_scope_changed")
            if tag == "resource":
                self._add(self.resources, (tenant_id, value["id"]), value)
            else:
                self.files[tenant_id, value["knowledge_id"]] += 1
        elif tag == "physical_index":
            if kind != "baseline" or section != "physical":
                _blocked("physical_scope_changed")
            self._add(self.physical, (tenant_id, value["space_id"]), value)
        else:
            if kind != "plan" or section != "physical":
                _blocked("retention_scope_changed")
            self._add(self.retained, (tenant_id, value["space_id"]), value)

    def finish(self):
        if set(self.files) - self.resources.keys():
            _blocked("file_resource_scope_changed")
        if self.policy == "bindings_only":
            return
        expected = {key for key, value in self.resources.items() if value["type"] in {0, 3}}
        if set(self.physical) != expected:
            _blocked("physical_resource_set_changed")
        incompatible = set()
        for key, physical in self.physical.items():
            resource = self.resources[key]
            if (physical["index_name"], physical["collection_name"]) != (
                resource["index_name"],
                resource["collection_name"],
            ):
                _blocked("binding_changed")
            if physical["identifier_compatible"] is False:
                incompatible.add(key)
                wanted = retention_record(resource=resource, physical=physical, managed_file_count=self.files[key])
                actual = self.retained.get(key)
                if actual != wanted.data:
                    _blocked("original_empty_proof_changed")
        if set(self.retained) != incompatible:
            _blocked("retention_resource_set_changed")
