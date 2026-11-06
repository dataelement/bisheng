"""Closed private M2 facts and bounded manifests, without migration authority."""

import hashlib
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import Enum

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.domain.repositories import unification_control_repository as control
from bisheng.knowledge.domain.repositories import unification_resource_repository as resource
from bisheng.permission.domain.schemas import VisibleSourceProjectionDTO
from bisheng.permission.domain.services.catalog_policy import CatalogAction
from bisheng.permission.migration import f118_plan as permission

MAX_BYTES = 16 * 1024 * 1024
SECTIONS = frozenset(
    {
        "resources",
        "control",
        "permission",
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


def _invalid():
    raise KnowledgeOperationPlanConflictError(reason="migration_inventory_codec_invalid")


def canonical(value):
    def scalar(item):
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, Enum):
            return item.value
        if type(item) in (tuple, set, frozenset):
            return sorted(item) if type(item) in (set, frozenset) else list(item)
        raise TypeError("unsupported inventory scalar")

    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=scalar
        ).encode()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _invalid()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


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


def _spec(text):
    return dict(item.split(":", 1) for item in text.split())


# These are wire allowlists, deliberately independent of dataclass introspection.
_SCHEMAS = {
    "evidence_material": _spec(
        "material_kind:str environment:str writer_contract_version:str tenant_inventory_digest:hash material_ref:descriptor"
    ),
    "queued_task_orphan": _spec(
        "task_kind:str task_id:str space_id:int? file_id:int? document_id:int? version_id:int? payload_tenant_id:positive? state:str reason:str configuration_digest:hash record_digest:hash"
    ),
    "permission_plan": _spec(
        "tenant_id:positive resource_type:str resource_id:str target_resource_type:str plan_checksum:hash before_digest:hash after_grants_digest:hash visibility_deltas_digest:hash expected_use_changes_digest:hash"
    ),
    "resource": _spec(
        "tenant_id:positive id:positive type:int user_id:int? state:int? model:str? index_name:str? collection_name:str? creation_request_id:str? creation_payload_hash:str? old_business_digest:hash neutral_digest:hash"
    ),
    "file": _spec(
        "id:positive tenant_id:positive knowledge_id:positive file_type:int level:int? file_level_path:str? status:int? file_source:str? file_size:int? object_name:str? preview_file_object_name:str? bbox_object_name:str? thumbnails:str? html_snapshot_object_name:str? row_digest:hash split_rule_digest:hash user_metadata_digest:hash"
    ),
    "document": _spec(
        "id:positive knowledge_id:positive file_level_path:str? level:int? primary_version_id:int? parent_tenant_id:int? parent_knowledge_type:int? row_digest:hash"
    ),
    "version": _spec(
        "id:positive document_id:positive knowledge_file_id:positive version_no:int is_primary:bool knowledge_id:int? parent_tenant_id:int? file_knowledge_id:int? file_tenant_id:int? file_type:int? file_space_tenant_id:int? row_digest:hash"
    ),
    "qa": _spec(
        "id:positive tenant_id:positive knowledge_id:positive user_id:int? source:int? status:int? row_digest:hash"
    ),
    "tag": _spec("id:positive tenant_id:positive user_id:int business_type:str business_id:str? row_digest:hash"),
    "tag_link": _spec(
        "id:positive tenant_id:positive user_id:int tag_id:int resource_id:str resource_type:int row_digest:hash"
    ),
    "tag_library": _spec(
        "id:positive tenant_id:positive owner_knowledge_id:int? user_id:int tag_count:int is_builtin:bool row_digest:hash"
    ),
    "department_space": _spec(
        "id:positive tenant_id:positive department_id:int space_id:int created_by:int approval_enabled:bool sensitive_check_enabled:bool is_hidden:bool row_digest:hash"
    ),
    "tenant": _spec(
        "id:positive status:str parent_tenant_id:int? root_dept_id:int? share_default_to_children:int quota_digest:hash row_digest:hash"
    ),
    "membership": _spec(
        "id:positive user_id:int tenant_id:positive is_default:int status:str is_active:int? last_access_time:str? join_time:str? row_digest:hash"
    ),
    "department": _spec(
        "id:positive tenant_id:positive parent_id:int? path:str status:str is_deleted:int is_tenant_root:int mounted_tenant_id:int? update_time:str? row_digest:hash"
    ),
    "role": _spec(
        "id:positive tenant_id:positive role_type:str department_id:int? knowledge_space_file_limit:int? update_time:str? quota_digest:hash row_digest:hash"
    ),
    "user_role": _spec(
        "id:int user_id:int role_id:int tenant_id:positive create_time:str? update_time:str? row_digest:hash"
    ),
    "creator": _spec("user_id:positive exists:bool delete:int?"),
    "role_fact": _spec(
        "id:positive exists:bool tenant_id:int? role_type:str? department_id:int? knowledge_space_file_limit:int? update_time:str? quota_digest:hash row_digest:hash"
    ),
    "physical_index": _spec(
        "tenant_id:positive space_id:positive index_name:str? collection_name:str? es_exists:bool milvus_exists:bool es_mapping_digest:hash? milvus_schema_digest:hash? es_count:nonnegative? milvus_count:nonnegative? identifier_compatible:bool"
    ),
    "physical_object": _spec(
        "tenant_id:positive space_id:positive file_id:positive object_kind:str object_key:key exists:bool size:nonnegative? etag:str?"
    ),
    "queued_task": _spec(
        "tenant_id:positive task_kind:str task_id:str space_id:int? file_id:int? document_id:int? version_id:int? state:str configuration_digest:hash record_digest:hash"
    ),
    "fga_tuple": _spec("user:str relation:str object:str"),
    "manifest_entry": _spec(
        "section:str scope:str tenant_id:positive? page_index:nonnegative record_count:nonnegative descriptor:descriptor level:nonnegative"
    ),
    "run": _spec(
        "writer_contract_version:str environment:str tenant_count:positive tenant_inventory_digest:hash backup_ref:descriptor schema_ref:descriptor catalog_digest:hash authorization_model_checksum:hash baseline_ref:descriptor?"
    ),
    "conversion_plan": _spec(
        "tenant_id:positive resource_id:positive original_type:int target_type:int action:str business_digest:hash"
    ),
    "source_decision": _spec(
        "tenant_id:positive source_type:str source_id:str source_version:str slot_key:str target_type:str target_id:str exists:bool disposition:str revision_digest:hash"
    ),
    "quota_usage": _spec(
        "tenant_id:positive personal_space_count:nonnegative department_space_count:nonnegative stored_bytes:nonnegative configuration_digest:hash"
    ),
    "resource_mode": _spec(
        "id:positive tenant_id:positive resource_type:str resource_id:str mode:str parent_type:str? parent_id:str? version:int projection_state:str operation_id:int?"
    ),
    "grant": _spec(
        "id:positive tenant_id:positive resource_type:str resource_id:str model_key:str state:str version:int projection_state:str"
    ),
    "assignee": _spec(
        "id:positive grant_id:positive tenant_id:positive subject_type:str subject_id:str userset_relation:str? include_children:bool source_type:str source_ref:str source_locator:str source_fingerprint:hash projected_subject:str protected:bool state:str version:int"
    ),
    "visible_source": _spec("id:positive source:source"),
    "source_contribution": _spec(
        "tenant_id:positive resource_type:str resource_id:str visibility_class:str projected_subject:str source_kind:str source_owner_key:str source_locator:str source_fingerprint:hash contribution_fingerprint:hash model_key:str? source_version:nonnegative tuple_fingerprint:hash state:str operation_id:positive? migration_item_id:positive?"
    ),
    "catalog_release": _spec(
        "id:positive release_key:str version:int checksum:hash required_authorization_model_release_id:int status:str write_fenced:bool predecessor_id:int? commit_checksum:str? draft_owner_id:int idempotency_key:str projection_checkpoint:int expires_at:str? published_at:str?"
    ),
    "authorization": _spec(
        "id:positive environment:str store_id:str model_id:str model_checksum:hash required_relations_checksum:hash status:str model_version:str predecessor_model_id:str? openfga_version:str"
    ),
    "catalog_action": _spec("code:str name:str level:int? active:bool resource_types:strings sort_order:int"),
    "permission_model": _spec(
        "id:positive model_key:str name:str normalized_name:str kind:str config_scope:str derived_level:int? active:bool allow_same_level:bool selected_action_codes:strings effective_action_codes:strings visibility_only_resource_types:strings visibility_level:int? legacy_source_key:str?"
    ),
}

_CONVERSION_COMMON = _spec(
    "schema_version:int run_id:str writer_contract_version:str tenant_id:positive command_key:hash operation:str"
)
_CONVERSION_FIELDS = {
    "resource_conversion": "knowledge_id:positive before_business_digest:hash after_business_digest:hash before_neutral_digest:hash after_neutral_digest:hash after_inventory_business_revision_digest:hash after_owner_configuration_digest:hash target_type:int target_is_released:bool target_migration_origin:str",
    "initialize_v1": "knowledge_id:positive file_id:positive file_business_digest:hash before_relation_digest:hash natural_key:hash document_template_digest:hash version_template_digest:hash file_level_path:str? level:int? planned_at:str",
    "tag_conversion": "tag_id:positive knowledge_id:positive before_digest:hash after_digest:hash from_business_type:str to_business_type:str",
    "tag_link_conversion": "link_id:positive file_id:positive knowledge_id:positive tag_id:positive before_digest:hash after_digest:hash? from_type:int to_type:int action:str survivor_link_id:positive survivor_digest:hash",
    "default_conversion": "row_id:positive key:str before_raw_row_digest:hash before_configuration_digest:hash after_configuration_digest:hash after_business_revision_digest:hash before_refs_digest:hash after_refs_digest:hash action:str selected_linsight_id:str? selected_chat_id:str? drop_task_model:bool drop_executor_mode:bool algorithm_version:str provenance:provenance",
}
for _tag, _fields in _CONVERSION_FIELDS.items():
    _SCHEMAS[_tag] = _CONVERSION_COMMON | _spec(_fields)


def _validate(tag, data):
    schema = _SCHEMAS.get(tag)
    if schema is None or type(data) is not dict or set(data) != set(schema):
        _invalid()
    for name, spec in schema.items():
        _value(data[name], spec)
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
    facts = []
    for record in records:
        if type(record) is not InventoryRecord:
            _invalid()
        if record.record_type in _CONVERSION_FIELDS and (
            section != "conversion" or kind != "plan" or record.data["run_id"] != run_id
        ):
            _invalid()
        if record.record_type == "queued_task_orphan" and (section != "tasks" or scope != "global"):
            _invalid()
        if (record.record_type == "evidence_material") != (section == "evidence"):
            _invalid()
        data = record.data
        actual_tenant = data.get("tenant_id")
        if record.record_type == "visible_source":
            actual_tenant = data["source"]["tenant_id"]
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
