"""Pure, finite SQL-stage commands. These values never authorize M3 writes."""

import json
import re
from dataclasses import dataclass, replace
from datetime import datetime

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.reference_source_owner import KnowledgeReferenceSourceOwner
from bisheng.knowledge.application.unification_inventory_codec import digest, record_from_row
from bisheng.knowledge.application.unification_sources import knowledge_business_revision_digest
from bisheng.knowledge.domain.repositories import unification_resource_repository as raw
from bisheng.knowledge.domain.repositories.unification_inventory_repository import DefaultRow
from bisheng.llm.domain.services.chat_default_model_backfill import transform_chat_default
from bisheng.llm.domain.services.default_reference_extractor import extract_model_default_references
from bisheng.llm.domain.services.linsight_default_model_backfill import transform_linsight_llm_config
from bisheng.resource_reference.application.contracts import canonical_target_id, reference_set_digest


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"conversion_plan_{reason}")


def _identity(run_id, writer_contract_version):
    for value, maximum in ((run_id, 64), (writer_contract_version, 32)):
        if (
            type(value) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value) is None
            or len(value) > maximum
        ):
            _blocked("identity")


def _values(row, names):
    return {name: getattr(row, name) for name in names}


@dataclass(frozen=True, slots=True)
class ConversionCommand:
    schema_version: int
    run_id: str
    writer_contract_version: str
    tenant_id: int
    command_key: str
    operation: str


@dataclass(frozen=True, slots=True)
class ResourceConversionCommand(ConversionCommand):
    knowledge_id: int
    before_business_digest: str
    after_business_digest: str
    before_neutral_digest: str
    after_neutral_digest: str
    after_inventory_business_revision_digest: str
    after_owner_configuration_digest: str
    target_type: int
    target_is_released: bool
    target_migration_origin: str


@dataclass(frozen=True, slots=True)
class InitializeV1Command(ConversionCommand):
    knowledge_id: int
    file_id: int
    file_business_digest: str
    before_relation_digest: str
    natural_key: str
    document_template_digest: str
    version_template_digest: str
    file_level_path: str | None
    level: int | None
    planned_at: datetime


@dataclass(frozen=True, slots=True)
class TagConversionCommand(ConversionCommand):
    tag_id: int
    knowledge_id: int
    before_digest: str
    after_digest: str
    from_business_type: str
    to_business_type: str


@dataclass(frozen=True, slots=True)
class TagLinkConversionCommand(ConversionCommand):
    link_id: int
    file_id: int
    knowledge_id: int
    tag_id: int
    before_digest: str
    after_digest: str | None
    from_type: int
    to_type: int
    action: str
    survivor_link_id: int
    survivor_digest: str


@dataclass(frozen=True, slots=True)
class DefaultSlotProvenance:
    source_slot: str
    target_slot: str
    target_id: str


@dataclass(frozen=True, slots=True)
class DefaultConversionCommand(ConversionCommand):
    row_id: int
    key: str
    before_raw_row_digest: str
    before_configuration_digest: str
    after_configuration_digest: str
    after_business_revision_digest: str
    before_refs_digest: str
    after_refs_digest: str
    action: str
    selected_linsight_id: str | None
    selected_chat_id: str | None
    drop_task_model: bool
    drop_executor_mode: bool
    algorithm_version: str
    provenance: tuple[DefaultSlotProvenance, ...]


COMMAND_RECORD_TYPES = {
    ResourceConversionCommand: "resource_conversion",
    InitializeV1Command: "initialize_v1",
    TagConversionCommand: "tag_conversion",
    TagLinkConversionCommand: "tag_link_conversion",
    DefaultConversionCommand: "default_conversion",
}


def _common(operation, run_id, writer, tenant, ident):
    _identity(run_id, writer)
    if type(tenant) is not int or tenant <= 0:
        _blocked("tenant")
    values = {
        "schema_version": 1,
        "run_id": run_id,
        "writer_contract_version": writer,
        "tenant_id": tenant,
        "operation": operation,
    }
    return values | {"command_key": digest(values | {"identity": ident})}


def initial_version_templates(*, knowledge_id, file_id, file_level_path, level, planned_at, natural_key):
    document = {
        "knowledge_id": knowledge_id,
        "file_level_path": file_level_path,
        "level": level,
        "primary_version_key": natural_key,
        "create_time": planned_at,
        "update_time": planned_at,
    }
    version = {
        "document_key": natural_key,
        "knowledge_file_id": file_id,
        "version_no": 1,
        "is_primary": True,
        "create_time": planned_at,
        "update_time": planned_at,
    }
    return document, version


def plan_default_conversion(row: DefaultRow, *, run_id, writer_contract_version):
    _identity(run_id, writer_contract_version)
    if type(row) is not DefaultRow:
        _blocked("default_row")
    if row.key != "linsight_llm" or row.value in (None, ""):
        return None

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _blocked("duplicate_default_key")
            result[key] = value
        return result

    try:
        payload = json.loads(row.value, object_pairs_hook=pairs)
        before_refs = extract_model_default_references(row.key, payload)
        if "task_model" in payload:
            legacy = payload["task_model"]
            if legacy is not None and type(legacy) is not dict:
                _blocked("legacy_default_shape")
            if legacy is not None and legacy.get("id") is not None:
                canonical_target_id(legacy["id"])
        after, first = transform_linsight_llm_config(payload)
        after, second = transform_chat_default(after)
        after_refs = extract_model_default_references(row.key, after)
        if after == payload:
            return None
        encoded = json.dumps(after, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, KeyError, RecursionError) as error:
        raise KnowledgeOperationPlanConflictError(reason="conversion_plan_invalid_default") from error
    provenance = []
    for slot in ("linsight_default_model_id", "chat_default_model_id"):
        selected = after.get(slot)
        if selected not in (None, "") and payload.get(slot) != selected:
            ident = canonical_target_id(selected)
            provenance.append(DefaultSlotProvenance(f"models.{ident}.id", slot, ident))
    command = DefaultConversionCommand(
        **_common("default_conversion", run_id, writer_contract_version, row.tenant_id, row.id),
        row_id=row.id,
        key=row.key,
        before_raw_row_digest=digest(_values(row, ("id", "tenant_id", "key", "value", "update_time"))),
        before_configuration_digest=digest({"key": row.key, "value": payload}),
        after_configuration_digest=digest({"key": row.key, "value": after}),
        after_business_revision_digest=digest(
            _values(replace(row, value=encoded), ("id", "tenant_id", "key", "value", "update_time"))
        ),
        before_refs_digest=reference_set_digest(before_refs),
        after_refs_digest=reference_set_digest(after_refs),
        action=f"{first}:{second}",
        selected_linsight_id=after.get("linsight_default_model_id"),
        selected_chat_id=after.get("chat_default_model_id"),
        drop_task_model="task_model" in payload,
        drop_executor_mode="linsight_executor_mode" in payload and "linsight_executor_mode" not in after,
        algorithm_version="sql-default-conversion-v1",
        provenance=tuple(provenance),
    )
    record_from_row(command)
    return command


class ConversionPlanBuilder:
    def __init__(self, *, run_id: str, writer_contract_version: str, planned_at: datetime):
        _identity(run_id, writer_contract_version)
        if type(planned_at) is not datetime:
            _blocked("planned_time")
        self.run_id, self.writer, self.planned_at = run_id, writer_contract_version, planned_at
        self._stage, self._finished, self._tenant = -1, False, None
        self._resources, self._files, self._documents, self._versions, self._tags, self._links = {}, {}, {}, {}, {}, {}
        self._creation, self._defaults, self._default_keys = {}, [], set()

    def _batch(self, rows, stage, cls):
        if (
            self._finished
            or type(rows) is not tuple
            or len(rows) > 200
            or stage < self._stage
            or any(type(row) is not cls for row in rows)
        ):
            _blocked("batch_order_or_shape")
        self._stage = stage

    def _scope(self, tenant):
        if type(tenant) is not int or tenant <= 0 or (self._tenant is not None and self._tenant != tenant):
            _blocked("mixed_tenant")
        self._tenant = tenant

    @staticmethod
    def _add(index, ident, value):
        if type(ident) is not int or ident <= 0 or ident in index:
            _blocked("duplicate_row")
        index[ident] = value

    def _base(self, operation, ident):
        return _common(operation, self.run_id, self.writer, self._tenant, ident)

    def add_resources(self, rows: tuple[raw.ResourceRow, ...]):
        self._batch(rows, 0, raw.ResourceRow)
        for row in rows:
            self._scope(row.tenant_id)
            record_from_row(row)
            if row.type not in (0, 1, 2, 3) or digest(_values(row, raw.RESOURCE_COLUMNS)) != row.old_business_digest:
                _blocked("resource_before_changed")
            target = 3 if row.type == 0 else row.type
            if row.creation_request_id and row.user_id is not None:
                key = (row.tenant_id, row.user_id, target, row.creation_request_id)
                if key in self._creation:
                    _blocked("creation_target_collision")
                self._creation[key] = row.id
            command = None
            if row.type == 0:
                after = replace(
                    row, type=3, is_released=False, neutral=replace(row.neutral, migration_origin=self.run_id)
                )
                owner = _values(
                    after,
                    (
                        "id",
                        "tenant_id",
                        "type",
                        "user_id",
                        "name",
                        "description",
                        "state",
                        "model",
                        "index_name",
                        "collection_name",
                    ),
                ) | _values(after.neutral, ("model_transition", "model_config_revision", "index_generation"))
                command = ResourceConversionCommand(
                    **self._base("resource_conversion", row.id),
                    knowledge_id=row.id,
                    before_business_digest=row.old_business_digest,
                    after_business_digest=digest(_values(after, raw.RESOURCE_COLUMNS)),
                    before_neutral_digest=digest(_values(row.neutral, raw.NEUTRAL_COLUMNS)),
                    after_neutral_digest=digest(_values(after.neutral, raw.NEUTRAL_COLUMNS)),
                    after_inventory_business_revision_digest=knowledge_business_revision_digest(after),
                    after_owner_configuration_digest=KnowledgeReferenceSourceOwner._snapshot(
                        owner
                    ).configuration_digest,
                    target_type=3,
                    target_is_released=False,
                    target_migration_origin=self.run_id,
                )
            self._add(self._resources, row.id, {"type": row.type, "command": command})

    def add_files(self, rows: tuple[raw.FileRow, ...]):
        self._batch(rows, 1, raw.FileRow)
        for row in rows:
            self._scope(row.tenant_id)
            safe = record_from_row(row).data
            if row.knowledge_id not in self._resources or row.file_type not in (0, 1):
                _blocked("file_parent")
            self._add(
                self._files,
                row.id,
                _values(row, ("knowledge_id", "file_type", "file_level_path", "level"))
                | {"digest": safe["row_digest"]},
            )

    def add_documents(self, rows: tuple[raw.DocumentRow, ...]):
        self._batch(rows, 2, raw.DocumentRow)
        for row in rows:
            self._scope(row.parent_tenant_id)
            record_from_row(row)
            if row.knowledge_id not in self._resources:
                _blocked("document_parent")
            self._add(self._documents, row.id, _values(row, ("knowledge_id", "primary_version_id")))

    def add_versions(self, rows: tuple[raw.VersionRow, ...]):
        self._batch(rows, 3, raw.VersionRow)
        for row in rows:
            self._scope(row.parent_tenant_id)
            record_from_row(row)
            doc, physical = self._documents.get(row.document_id), self._files.get(row.knowledge_file_id)
            if not doc or not physical or physical["file_type"] != 1 or doc["knowledge_id"] != physical["knowledge_id"]:
                _blocked("version_parent")
            self._add(
                self._versions, row.id, _values(row, ("document_id", "knowledge_file_id", "version_no", "is_primary"))
            )

    def add_tags(self, rows: tuple[raw.TagRow, ...]):
        self._batch(rows, 4, raw.TagRow)
        for row in rows:
            self._scope(row.tenant_id)
            record_from_row(row)
            ident = (
                int(row.business_id)
                if type(row.business_id) is str and re.fullmatch(r"[1-9][0-9]*", row.business_id)
                else None
            )
            migrating = row.business_type == "knowledge" and self._resources.get(ident, {}).get("type") == 0
            if row.business_type in {"knowledge", "knowledge_space"} and ident not in self._resources:
                _blocked("tag_container_missing")
            self._add(
                self._tags,
                row.id,
                {
                    "knowledge_id": ident,
                    "business_type": row.business_type,
                    "name_digest": digest(row.name),
                    "digest": digest(_values(row, raw.TAG_COLUMNS)),
                    "after_digest": digest(_values(replace(row, business_type="knowledge_space"), raw.TAG_COLUMNS))
                    if migrating
                    else None,
                },
            )

    def add_tag_links(self, rows: tuple[raw.TagLinkRow, ...]):
        self._batch(rows, 5, raw.TagLinkRow)
        for row in rows:
            self._scope(row.tenant_id)
            record_from_row(row)
            self._add(
                self._links,
                row.id,
                _values(row, ("tag_id", "resource_id", "resource_type"))
                | {
                    "digest": digest(_values(row, raw.LINK_COLUMNS)),
                    "after_digest": digest(_values(replace(row, resource_type=8), raw.LINK_COLUMNS)),
                },
            )

    def add_defaults(self, rows: tuple[DefaultRow, ...]):
        self._batch(rows, 6, DefaultRow)
        for row in rows:
            self._scope(row.tenant_id)
            if row.key in self._default_keys:
                _blocked("duplicate_default")
            self._default_keys.add(row.key)
            command = plan_default_conversion(row, run_id=self.run_id, writer_contract_version=self.writer)
            if command is not None:
                self._defaults.append(command)

    def finish(self):
        if self._finished:
            _blocked("already_finished")
        self._finished = True
        commands = [row["command"] for row in self._resources.values() if row["command"] is not None]
        registered, by_doc = set(), {}
        for ident, row in self._versions.items():
            if row["knowledge_file_id"] in registered or type(row["version_no"]) is not int or row["version_no"] < 1:
                _blocked("duplicate_version_relation")
            registered.add(row["knowledge_file_id"])
            by_doc.setdefault(row["document_id"], []).append((ident, row))
        for ident, doc in self._documents.items():
            versions = by_doc.get(ident, ())
            primaries = [key for key, row in versions if row["is_primary"]]
            if (
                not versions
                or len({row["version_no"] for _, row in versions}) != len(versions)
                or len(primaries) != 1
                or doc["primary_version_id"] != primaries[0]
            ):
                _blocked("primary_chain")
        for ident, row in self._files.items():
            if (
                row["file_type"] != 1
                or ident in registered
                or self._resources[row["knowledge_id"]]["type"] not in (0, 3)
            ):
                continue
            natural = digest(
                {
                    "run_id": self.run_id,
                    "writer_contract_version": self.writer,
                    "tenant_id": self._tenant,
                    "file_id": ident,
                    "action": "register_v1",
                }
            )
            templates = initial_version_templates(
                knowledge_id=row["knowledge_id"],
                file_id=ident,
                file_level_path=row["file_level_path"],
                level=row["level"],
                planned_at=self.planned_at,
                natural_key=natural,
            )
            commands.append(
                InitializeV1Command(
                    **self._base("initialize_v1", ident),
                    knowledge_id=row["knowledge_id"],
                    file_id=ident,
                    file_business_digest=row["digest"],
                    before_relation_digest=digest(()),
                    natural_key=natural,
                    document_template_digest=digest(templates[0]),
                    version_template_digest=digest(templates[1]),
                    file_level_path=row["file_level_path"],
                    level=row["level"],
                    planned_at=self.planned_at,
                )
            )
        links_by_tag, target_links = {}, {}
        for ident, row in self._links.items():
            tag = self._tags.get(row["tag_id"])
            if tag is None:
                _blocked("tag_parent_missing")
            links_by_tag.setdefault(row["tag_id"], []).append((ident, row))
            if row["resource_type"] in (8, 9):
                if (
                    re.fullmatch(r"[1-9][0-9]*", row["resource_id"]) is None
                    or int(row["resource_id"]) not in self._files
                ):
                    _blocked("tag_file_missing")
                if row["resource_type"] == 8:
                    target_links[(row["resource_id"], 8, row["tag_id"])] = (ident, row)
        names = {}
        for ident, tag in self._tags.items():
            kind = "knowledge_space" if tag["after_digest"] else tag["business_type"]
            key = (tag["knowledge_id"], kind, tag["name_digest"])
            if (
                kind == "knowledge_space"
                and key in names
                and (tag["after_digest"] or self._tags[names[key]]["after_digest"])
            ):
                _blocked("tag_name_collision")
            names[key] = ident
            if tag["after_digest"]:
                for _, link in links_by_tag.get(ident, ()):
                    physical = self._files.get(int(link["resource_id"])) if link["resource_type"] in (8, 9) else None
                    if physical is None or physical["knowledge_id"] != tag["knowledge_id"]:
                        _blocked("shared_tag_owner")
                commands.append(
                    TagConversionCommand(
                        **self._base("tag_conversion", ident),
                        tag_id=ident,
                        knowledge_id=tag["knowledge_id"],
                        before_digest=tag["digest"],
                        after_digest=tag["after_digest"],
                        from_business_type="knowledge",
                        to_business_type="knowledge_space",
                    )
                )
        for ident, row in self._links.items():
            if row["resource_type"] != 9:
                continue
            physical = self._files[int(row["resource_id"])]
            if self._resources[physical["knowledge_id"]]["type"] != 0:
                continue
            tag = self._tags[row["tag_id"]]
            if tag["knowledge_id"] != physical["knowledge_id"] or tag["business_type"] not in (
                "knowledge",
                "knowledge_space",
            ):
                _blocked("tag_owner_mismatch")
            survivor = target_links.get((row["resource_id"], 8, row["tag_id"]))
            commands.append(
                TagLinkConversionCommand(
                    **self._base("tag_link_conversion", ident),
                    link_id=ident,
                    file_id=int(row["resource_id"]),
                    knowledge_id=physical["knowledge_id"],
                    tag_id=row["tag_id"],
                    before_digest=row["digest"],
                    after_digest=None if survivor else row["after_digest"],
                    from_type=9,
                    to_type=8,
                    action="drop_duplicate" if survivor else "retag",
                    survivor_link_id=survivor[0] if survivor else ident,
                    survivor_digest=survivor[1]["digest"] if survivor else row["after_digest"],
                )
            )
        commands.extend(self._defaults)
        ordered = tuple(
            sorted(
                commands,
                key=lambda value: (
                    isinstance(value, DefaultConversionCommand),
                    getattr(value, "knowledge_id", 0),
                    value.operation,
                    value.command_key,
                ),
            )
        )
        for command in ordered:
            record_from_row(command)
        return iter(ordered)
