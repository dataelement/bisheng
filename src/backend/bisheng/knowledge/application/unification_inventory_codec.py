"""Closed private M2 facts and bounded manifests, without migration authority."""

import hashlib
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, fields
from datetime import datetime

from bisheng.knowledge.application.unification_inventory_schema import (
    _CONVERSION_COMMON as _CONVERSION_COMMON,
)
from bisheng.knowledge.application.unification_inventory_schema import (
    _CONVERSION_FIELDS as _CONVERSION_FIELDS,
)
from bisheng.knowledge.application.unification_inventory_schema import (
    _SCHEMAS as _SCHEMAS,
)
from bisheng.knowledge.application.unification_inventory_schema import (
    _spec as _spec,
)
from bisheng.knowledge.domain.repositories import unification_control_repository as control
from bisheng.knowledge.domain.repositories import unification_resource_repository as resource
from bisheng.knowledge.domain.repositories import unification_space_membership_repository as space_membership
from bisheng.knowledge.domain.services.unification_fingerprints import (
    _invalid as _invalid,
)
from bisheng.knowledge.domain.services.unification_fingerprints import (
    canonical as canonical,
)
from bisheng.knowledge.domain.services.unification_fingerprints import (
    digest as digest,
)
from bisheng.permission.domain.schemas import VisibleSourceProjectionDTO
from bisheng.permission.domain.services.catalog_policy import CatalogAction
from bisheng.permission.migration import f118_plan as permission

MAX_BYTES = 16 * 1024 * 1024
SECTIONS = frozenset(
    {
        "resources",
        "control",
        "permission",
        "permission_namespace",
        "catalog",
        "physical",
        "tasks",
        "fga",
        "manifest",
        "conversion",
        "sources",
        "evidence",
    }
)
KINDS = frozenset({"baseline", "plan", "permission_catalog", "permission_resources", "conversion", "verification"})
OBJECT_KINDS = frozenset({"original", "preview", "bbox", "thumbnail", "html_snapshot"})
_BROKER_GLOBAL_STATES = frozenset({"global_control", "target_missing", "unacked_metadata_orphan"})
_NAMESPACE_GLOBAL = frozenset({"namespace_catalog", "namespace_applicability"})
_NAMESPACE_RECORDS = _NAMESPACE_GLOBAL | {
    "namespace_target_mode",
    "namespace_after_grant",
    "namespace_after_assignee",
    "namespace_after_visible_source",
}


def _descriptor(value):
    if type(value) is not dict or set(value) != {"object_key", "sha256"}:
        _invalid()
    _value(value["object_key"], "key")
    _value(value["sha256"], "hash")


def _value(value, spec):
    if spec.endswith("?"):
        if value is None:
            return
        spec = spec[:-1]
    if spec == "int":
        valid = type(value) is int
    elif spec == "positive":
        valid = type(value) is int and value > 0
    elif spec == "nonnegative":
        valid = type(value) is int and value >= 0
    elif spec == "bool":
        valid = type(value) is bool
    elif spec in {"str", "key", "hash"}:
        valid = type(value) is str and "\x00" not in value and len(value) <= 4096
        if valid and spec == "key":
            valid = bool(value) and "://" not in value and not value.startswith("/") and ".." not in value.split("/")
        if valid and spec == "hash":
            valid = re.fullmatch(r"[0-9a-f]{64}", value) is not None
    elif spec == "descriptor":
        _descriptor(value)
        return
    elif spec == "strings":
        valid = type(value) is list and all(type(item) is str for item in value)
    elif spec == "source":
        _validate("source_contribution", value)
        return
    elif spec == "provenance":
        if type(value) is not list or len(value) > 2:
            _invalid()
        for item in value:
            if (
                type(item) is not dict
                or set(item) != {"source_slot", "target_slot", "target_id"}
                or item["target_slot"] not in {"linsight_default_model_id", "chat_default_model_id"}
                or type(item["target_id"]) is not str
                or re.fullmatch(r"[1-9][0-9]{0,63}", item["target_id"]) is None
                or item["source_slot"] != f"models.{item['target_id']}.id"
            ):
                _invalid()
        return
    else:
        _invalid()
    if not valid:
        _invalid()


def _validate(tag, data):
    schema = _SCHEMAS.get(tag)
    if schema is None or type(data) is not dict or set(data) != set(schema):
        _invalid()
    for name, spec in schema.items():
        _value(data[name], spec)
    if tag in _NAMESPACE_GLOBAL and (data["from_resource_type"], data["to_resource_type"]) != (
        "knowledge_library",
        "knowledge_space",
    ):
        _invalid()
    if tag == "namespace_target_mode" and data["mode_id"] != data["id"]:
        _invalid()
    if tag == "permission_model" and data["retired_use_level_floor"] not in {None, 1, 2, 3, 4}:
        _invalid()
    if tag == "broker_task" and (
        data["state"] not in _BROKER_GLOBAL_STATES | {"queued", "unacked", "legacy_requires_reissue", "obsolete"}
        or (data["tenant_id"] is None) != (data["state"] in _BROKER_GLOBAL_STATES)
        or (data["task_kind"] is None) != (data["state"] == "unacked_metadata_orphan")
        or (data["task_kind"] is not None and not data["task_kind"].startswith("bisheng.worker.knowledge."))
        or not data["task_id"]
    ):
        _invalid()
    if tag in _CONVERSION_FIELDS:
        _identity(data["run_id"], "conversion", "tenant", data["tenant_id"], 0, "plan")
        if (
            data["schema_version"] != 1
            or data["operation"] != tag
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}", data["writer_contract_version"]) is None
        ):
            _invalid()
        if tag == "resource_conversion" and (
            data["target_type"] != 3
            or data["target_is_released"] is not False
            or data["target_migration_origin"] != data["run_id"]
        ):
            _invalid()
        if tag == "resource_conversion":
            if data["membership_action"] == "insert":
                if data["existing_creator_member_id"] is not None or data["creator_planned_at"] is None:
                    _invalid()
                try:
                    value = datetime.fromisoformat(data["creator_planned_at"])
                except ValueError:
                    _invalid()
                if value.tzinfo is not None or value.microsecond or value.isoformat() != data["creator_planned_at"]:
                    _invalid()
            elif data["membership_action"] == "keep":
                if (
                    data["existing_creator_member_id"] is None
                    or data["creator_planned_at"] is not None
                    or data["before_member_count"] == 0
                ):
                    _invalid()
            else:
                _invalid()
        if tag == "initialize_v1":
            try:
                datetime.fromisoformat(data["planned_at"])
            except ValueError:
                _invalid()
        if tag == "tag_conversion" and (data["from_business_type"], data["to_business_type"]) != (
            "knowledge",
            "knowledge_space",
        ):
            _invalid()
        if tag == "tag_link_conversion" and (
            (data["from_type"], data["to_type"]) != (9, 8)
            or data["action"] not in {"retag", "drop_duplicate"}
            or (data["after_digest"] is None) != (data["action"] == "drop_duplicate")
        ):
            _invalid()
        if tag == "default_conversion" and (
            data["key"] != "linsight_llm"
            or data["algorithm_version"] != "sql-default-conversion-v1"
            or data["action"] not in {f"{a}:{b}" for a in ("skip", "kept", "first", "empty") for b in ("skip", "last")}
        ):
            _invalid()
    if tag == "physical_object" and data["object_kind"] not in OBJECT_KINDS:
        _invalid()
    if tag == "queued_task_orphan" and data["reason"] not in {"file_missing", "space_missing", "unresolved_tenant"}:
        _invalid()
    if tag == "evidence_material" and data["material_kind"] not in {"backup", "schema"}:
        _invalid()
    if tag == "file":
        for name in ("object_name", "preview_file_object_name", "bbox_object_name", "html_snapshot_object_name"):
            if data[name] not in (None, ""):
                _value(data[name], "key")
    if tag == "manifest_entry":
        _identity("manifest", data["section"], data["scope"], data["tenant_id"], data["page_index"], "baseline")


@dataclass(frozen=True, slots=True)
class InventoryRecord:
    record_type: str
    data_json: str = field(repr=False)

    @property
    def data(self):
        value = _parse(self.data_json.encode())
        _validate(self.record_type, value)
        return value


def record_from_values(record_type, **values):
    _validate(record_type, values)
    return InventoryRecord(record_type, canonical(values).decode())


def _original(row, names):
    return {name: getattr(row, name) for name in names}


_ROWS = {
    resource.ResourceRow: ("resource", (*resource.RESOURCE_COLUMNS, "neutral", "old_business_digest")),
    resource.FileRow: ("file", resource.FILE_COLUMNS),
    resource.DocumentRow: ("document", (*resource.DOCUMENT_COLUMNS, "parent_tenant_id", "parent_knowledge_type")),
    resource.VersionRow: (
        "version",
        (
            *resource.VERSION_COLUMNS,
            "knowledge_id",
            "parent_tenant_id",
            "file_knowledge_id",
            "file_tenant_id",
            "file_type",
            "file_space_tenant_id",
        ),
    ),
    resource.QARow: ("qa", resource.QA_COLUMNS),
    resource.TagRow: ("tag", resource.TAG_COLUMNS),
    resource.TagLinkRow: ("tag_link", resource.LINK_COLUMNS),
    resource.TagLibraryRow: ("tag_library", resource.LIBRARY_COLUMNS),
    resource.DepartmentSpaceRow: ("department_space", resource.DEPARTMENT_COLUMNS),
    control.TenantControlFact: ("tenant", control.TENANT_COLUMNS),
    control.MembershipRow: ("membership", control.MEMBERSHIP_COLUMNS),
    space_membership.SpaceMembershipHeader: ("space_membership_header", space_membership.HEADER_COLUMNS),
    space_membership.SpaceMembershipRow: (
        "space_member",
        ("tenant_id", "knowledge_id", *space_membership.MEMBER_COLUMNS),
    ),
    control.DepartmentRow: ("department", control.DEPARTMENT_COLUMNS),
    control.RoleRow: ("role", control.ROLE_COLUMNS),
    control.UserRoleRow: ("user_role", control.USER_ROLE_COLUMNS),
    control.CreatorFact: ("creator", ("user_id", "exists", "delete")),
    control.RoleFact: (
        "role_fact",
        (
            "id",
            "exists",
            "tenant_id",
            "role_type",
            "department_id",
            "quota_config",
            "knowledge_space_file_limit",
            "update_time",
        ),
    ),
    permission.ResourceModeBaseline: ("resource_mode", tuple(_SCHEMAS["resource_mode"])),
    permission.PermissionGrantBaseline: ("grant", tuple(_SCHEMAS["grant"])),
    permission.PermissionAssigneeBaseline: ("assignee", tuple(_SCHEMAS["assignee"])),
    permission.PermissionVisibleSourceBaseline: ("visible_source", ("id", "source")),
    permission.CatalogReleaseBaseline: ("catalog_release", tuple(_SCHEMAS["catalog_release"])),
    permission.AuthorizationPinBaseline: ("authorization", tuple(_SCHEMAS["authorization"])),
    permission.PermissionModelBaseline: ("permission_model", tuple(_SCHEMAS["permission_model"])),
    CatalogAction: ("catalog_action", tuple(_SCHEMAS["catalog_action"])),
}


def record_from_row(row):
    definition = _ROWS.get(type(row))
    if definition is None:
        from bisheng.knowledge.application.unification_conversion_plan import COMMAND_RECORD_TYPES

        tag = COMMAND_RECORD_TYPES.get(type(row))
        if tag is not None:
            definition = (tag, tuple(_SCHEMAS[tag]))
    if definition is None:
        _invalid()
    tag, names = definition
    if {item.name for item in fields(row)} != set(names):
        _invalid()
    original = _original(row, names)
    if tag == "default_conversion":
        from bisheng.knowledge.application.unification_conversion_plan import DefaultSlotProvenance

        if type(row.provenance) is not tuple or any(
            type(item) is not DefaultSlotProvenance
            or {part.name for part in fields(item)} != {"source_slot", "target_slot", "target_id"}
            for item in row.provenance
        ):
            _invalid()
        original["provenance"] = [
            _original(item, ("source_slot", "target_slot", "target_id")) for item in row.provenance
        ]
    values = {name: original[name] for name in _SCHEMAS[tag] if name in original}
    if tag == "resource":
        if {item.name for item in fields(row.neutral)} != set(resource.NEUTRAL_COLUMNS):
            _invalid()
        values["neutral_digest"] = digest(_original(row.neutral, resource.NEUTRAL_COLUMNS))
    elif tag == "file":
        html = row.user_metadata.get("html_snapshot_object_name") if row.user_metadata is not None else None
        values.update(
            html_snapshot_object_name=html,
            split_rule_digest=digest(row.split_rule),
            user_metadata_digest=digest(row.user_metadata),
        )
    elif tag == "visible_source":
        if type(row.source) is not VisibleSourceProjectionDTO or set(type(row.source).model_fields) != set(
            _SCHEMAS["source_contribution"]
        ):
            _invalid()
        values["source"] = {name: getattr(row.source, name) for name in _SCHEMAS["source_contribution"]}
    if "row_digest" in _SCHEMAS[tag]:
        values["row_digest"] = digest(original)
    if "quota_digest" in _SCHEMAS[tag]:
        values["quota_digest"] = digest(row.quota_config)
    # Normalize only explicit fields; original private bodies never enter values.
    values = json.loads(canonical(values))
    return record_from_values(tag, **values)


def _identity(run_id, section, scope, tenant_id, page_index, kind):
    if (
        type(run_id) is not str
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", run_id) is None
        or section not in SECTIONS
        or kind not in KINDS
    ):
        _invalid()
    _value(page_index, "nonnegative")
    if scope == "tenant":
        _value(tenant_id, "positive")
    elif scope != "global" or tenant_id is not None:
        _invalid()


def _parse(content):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _invalid()
            result[key] = value
        return result

    try:
        return json.loads(content, object_pairs_hook=pairs, parse_constant=lambda _: _invalid())
    except (ValueError, UnicodeError, TypeError, RecursionError):
        _invalid()


def encode_inventory_page(*, run_id, section, scope, tenant_id, page_index, records, kind="baseline"):
    _identity(run_id, section, scope, tenant_id, page_index, kind)
    if type(records) is not tuple or len(records) > 199 or section == "sources":
        _invalid()
    if section == "evidence" and (scope != "global" or kind != "verification"):
        _invalid()
    if section == "permission_namespace" and kind != "plan":
        _invalid()
    facts = []
    for record in records:
        if type(record) is not InventoryRecord:
            _invalid()
        data = record.data
        if (record.record_type in _NAMESPACE_RECORDS) != (section == "permission_namespace"):
            _invalid()
        if record.record_type in _NAMESPACE_RECORDS and (
            (scope == "global") != (record.record_type in _NAMESPACE_GLOBAL)
            or (record.record_type == "namespace_catalog" and data["run_id"] != run_id)
        ):
            _invalid()
        if record.record_type == "permission_plan" and (section != "conversion" or kind != "plan"):
            _invalid()
        if record.record_type in _CONVERSION_FIELDS and (
            section != "conversion" or kind != "plan" or record.data["run_id"] != run_id
        ):
            _invalid()
        if record.record_type == "queued_task_orphan" and (section != "tasks" or scope != "global"):
            _invalid()
        if record.record_type == "broker_task" and (
            section != "tasks" or (scope == "global") != (record.data["tenant_id"] is None)
        ):
            _invalid()
        if (record.record_type == "evidence_material") != (section == "evidence"):
            _invalid()
        actual_tenant = data.get("tenant_id")
        if record.record_type in {"visible_source", "namespace_after_visible_source"}:
            actual_tenant = data["source"]["tenant_id"]
        if record.record_type == "role_fact" and data["exists"] is True and actual_tenant == 1:
            # This is an exact referenced global Role observation, not a local
            # role row. Keep its real owner=Root while routing the fact into
            # the tenant that owns the UserRole association being inventoried.
            actual_tenant = tenant_id
        if scope == "tenant" and actual_tenant is not None and actual_tenant != tenant_id:
            _invalid()
        facts.append({"record_type": record.record_type, **data})
    header = {
        "record_type": "page",
        "section": section,
        "scope": scope,
        "tenant_id": tenant_id,
        "page_index": page_index,
        "record_count": len(records),
    }
    content = canonical({"schema_version": 1, "run_id": run_id, "kind": kind, "records": [header, *facts]})
    if len(content) > MAX_BYTES:
        _invalid()
    return content


@dataclass(frozen=True, slots=True)
class DecodedInventoryPage:
    records: tuple[InventoryRecord, ...]


def decode_inventory_page(content, *, run_id, section, scope, tenant_id, page_index, kind="baseline"):
    _identity(run_id, section, scope, tenant_id, page_index, kind)
    if type(content) is not bytes or not content or len(content) > MAX_BYTES:
        _invalid()
    value = _parse(content)
    if (
        type(value) is not dict
        or set(value) != {"schema_version", "run_id", "kind", "records"}
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["run_id"] != run_id
        or value["kind"] != kind
        or type(value["records"]) is not list
        or not value["records"]
    ):
        _invalid()
    records = []
    for item in value["records"][1:]:
        if type(item) is not dict or type(item.get("record_type")) is not str:
            _invalid()
        records.append(
            record_from_values(
                item["record_type"], **{name: val for name, val in item.items() if name != "record_type"}
            )
        )
    rebuilt = encode_inventory_page(
        run_id=run_id,
        section=section,
        scope=scope,
        tenant_id=tenant_id,
        page_index=page_index,
        records=tuple(records),
        kind=kind,
    )
    if rebuilt != content:
        _invalid()
    return DecodedInventoryPage(tuple(records))


@dataclass(frozen=True, slots=True)
class ManifestNode:
    descriptor: dict = field(repr=False)
    content: bytes = field(repr=False)
    level: int
    is_root: bool


def iter_manifest_nodes(
    *, run_id, kind, entries: Iterable[InventoryRecord], metadata: InventoryRecord
) -> Iterator[ManifestNode]:
    if kind not in {"baseline", "plan"} or type(metadata) is not InventoryRecord or metadata.record_type != "run":
        _invalid()
    level = 0
    parents = []
    batch = []

    def node(items, page, depth, root=False):
        content = encode_inventory_page(
            run_id=run_id,
            section="manifest",
            scope="global",
            tenant_id=None,
            page_index=page,
            records=tuple(items),
            kind=kind,
        )
        checksum = hashlib.sha256(content).hexdigest()
        descriptor = {"object_key": f"f118/unification/{run_id}/{kind}/{checksum}.json", "sha256": checksum}
        return ManifestNode(descriptor, content, depth, root)

    def reference(item, page):
        return record_from_values(
            "manifest_entry",
            section="manifest",
            scope="global",
            tenant_id=None,
            page_index=page,
            record_count=len(json.loads(item.content)["records"]) - 1,
            descriptor=item.descriptor,
            level=item.level,
        )

    for entry in entries:
        if type(entry) is not InventoryRecord or entry.record_type != "manifest_entry":
            _invalid()
        batch.append(entry)
        if len(batch) == 199:
            item = node(batch, len(parents), level)
            yield item
            parents.append(reference(item, len(parents)))
            batch = []
    if batch:
        item = node(batch, len(parents), level)
        yield item
        parents.append(reference(item, len(parents)))
    while len(parents) > 198:
        level += 1
        children, parents = parents, []
        for offset in range(0, len(children), 199):
            item = node(children[offset : offset + 199], len(parents), level)
            yield item
            parents.append(reference(item, len(parents)))
    yield node([metadata, *parents], 0, level + 1, True)
