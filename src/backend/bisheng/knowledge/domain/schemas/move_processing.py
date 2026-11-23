"""Closed move data. Repositories own digest calculation and all authority."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any

from bisheng.knowledge.domain.schemas.processing_job import ResourceVersionTarget

# Closed snapshot field names; repositories decide how to read them.
ROOT_FIELDS = tuple(
    (
        "id tenant_id type model model_config_revision index_generation index_name collection_name "
        "metadata_fields metadata_schema_revision state model_transition"
    ).split()
)
FILE_FIELDS = tuple(
    (
        "id tenant_id knowledge_id file_type file_source file_name file_level_path level object_name "
        "preview_file_object_name bbox_object_name thumbnails md5 file_size user_metadata status"
    ).split()
)
DOC_FIELDS = ("id", "knowledge_id", "primary_version_id", "file_level_path", "level")
VERSION_FIELDS = ("id", "document_id", "knowledge_file_id", "version_no", "is_primary")


def _positive(value):
    if type(value) is not int or value <= 0:
        raise ValueError("a positive concrete identifier is required")


def _checksum(value):
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("a caller-calculated canonical digest is required")


@dataclass(frozen=True, slots=True)
class MoveRoot:
    type: str
    id: int

    def __post_init__(self):
        _positive(self.id)
        if self.type not in ("file", "folder"):
            raise ValueError("a concrete file/folder is required")


@dataclass(frozen=True, slots=True)
class MoveParentChange:
    resource_type: str
    resource_id: int
    old_parent_type: str
    old_parent_id: int
    new_parent_type: str
    new_parent_id: int
    mode: str
    expected_permission_version: int

    def __post_init__(self):
        for value in (self.resource_id, self.old_parent_id, self.new_parent_id):
            _positive(value)
        if (
            self.resource_type not in ("folder", "knowledge_file")
            or self.old_parent_type not in ("folder", "knowledge_space")
            or self.new_parent_type not in ("folder", "knowledge_space")
            or (self.old_parent_type, self.old_parent_id) == (self.new_parent_type, self.new_parent_id)
            or self.mode not in ("CUSTOM", "INHERIT")
            or type(self.expected_permission_version) is not int
            or self.expected_permission_version < 0
        ):
            raise ValueError("invalid parent-change facts")


@dataclass(frozen=True, slots=True)
class MoveRow:
    file_id: int
    before: dict = field(repr=False)
    after: dict = field(repr=False)

    def __post_init__(self):
        _positive(self.file_id)
        if (
            type(self.before) is not dict
            or type(self.after) is not dict
            or self.before.get("id") != self.file_id
            or self.after.get("id") != self.file_id
        ):
            raise ValueError("a row keeps its actual primary key")
        object.__setattr__(self, "before", deepcopy(self.before))
        object.__setattr__(self, "after", deepcopy(self.after))


@dataclass(frozen=True, slots=True)
class MoveLeaf:
    target: ResourceVersionTarget
    selected_root: MoveRoot
    destination_parent_id: int | None
    version_no: int
    is_primary: bool
    original_status: int | None
    participates: bool
    before_revision: str
    after_revision: str
    projection_anchor: MoveParentChange

    def __post_init__(self):
        if (
            not isinstance(self.target, ResourceVersionTarget)
            or not isinstance(self.selected_root, MoveRoot)
            or not isinstance(self.projection_anchor, MoveParentChange)
        ):
            raise ValueError("actual version and move anchors required")
        if self.destination_parent_id is not None:
            _positive(self.destination_parent_id)
        _positive(self.version_no)
        if (
            type(self.is_primary) is not bool
            or type(self.participates) is not bool
            or self.participates != (self.original_status == 2)
        ):
            raise ValueError("original success alone participates in index movement")
        for value in (self.before_revision, self.after_revision):
            _checksum(value)


@dataclass(frozen=True, slots=True)
class MoveScope:
    tenant_id: int
    source_space_id: int
    destination_space_id: int
    destination_folder_id: int | None
    roots: tuple[MoveRoot, ...]
    source: dict = field(repr=False)
    destination: dict = field(repr=False)
    files: tuple[MoveRow, ...] = field(repr=False)
    documents: tuple[MoveRow, ...] = field(repr=False)
    versions: tuple[dict, ...] = field(repr=False)
    leaves: tuple[MoveLeaf, ...]
    parent_changes: tuple[MoveParentChange, ...]
    retained_fields: tuple[str, ...]
    removed_fields: tuple[str, ...]
    tag_link_ids: tuple[int, ...]
    scope_digest: str
    changes_digest: str

    def __post_init__(self):
        for value in (self.tenant_id, self.source_space_id, self.destination_space_id):
            _positive(value)
        if self.source_space_id == self.destination_space_id:
            raise ValueError("cross-space data required")
        if self.destination_folder_id is not None:
            _positive(self.destination_folder_id)
        if not self.roots or not self.files:
            raise ValueError("move has an actual nonempty logical scope")
        for name in (
            "roots",
            "files",
            "documents",
            "versions",
            "leaves",
            "parent_changes",
            "retained_fields",
            "removed_fields",
            "tag_link_ids",
        ):
            if type(getattr(self, name)) is not tuple:
                raise ValueError("scope collections are tuples")
        for row, key in ((self.source, self.source_space_id), (self.destination, self.destination_space_id)):
            if (
                type(row) is not dict
                or row.get("id") != key
                or row.get("tenant_id") != self.tenant_id
                or row.get("type") != 3
            ):
                raise ValueError("actual same-tenant knowledge spaces required")
        object.__setattr__(self, "source", deepcopy(self.source))
        object.__setattr__(self, "destination", deepcopy(self.destination))
        object.__setattr__(self, "versions", deepcopy(self.versions))
        for value in (self.scope_digest, self.changes_digest):
            _checksum(value)

    @property
    def source_model_config_revision(self):
        return self.source["model_config_revision"]

    def to_parameters(self):
        return move_scope_parameters(self)

    @classmethod
    def from_parameters(cls, parameters, *, scope_digest, changes_digest):
        value = deepcopy(parameters)
        if value.pop("move_schema", None) != 1:
            raise ValueError("invalid move snapshot version")
        value["roots"] = tuple(MoveRoot(**item) for item in value["roots"])
        for name in ("files", "documents"):
            value[name] = tuple(MoveRow(**item) for item in value[name])
        value["parent_changes"] = tuple(MoveParentChange(**item) for item in value["parent_changes"])
        value["leaves"] = tuple(
            MoveLeaf(
                **{
                    **item,
                    "target": ResourceVersionTarget.model_validate(item["target"]),
                    "selected_root": MoveRoot(**item["selected_root"]),
                    "projection_anchor": MoveParentChange(**item["projection_anchor"]),
                }
            )
            for item in value["leaves"]
        )
        for name in ("versions", "retained_fields", "removed_fields", "tag_link_ids"):
            value[name] = tuple(value[name])
        return cls(**value, scope_digest=scope_digest, changes_digest=changes_digest)


def _data(value):
    if isinstance(value, ResourceVersionTarget):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return {name: _data(item) for name, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {name: _data(item) for name, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_data(item) for item in value]
    return deepcopy(value)


def move_scope_parameters(scope: MoveScope | Mapping[str, Any]) -> dict:
    """One structural serializer, never a hash/canonical-bytes implementation."""
    names = {item.name for item in fields(MoveScope)} - {"scope_digest", "changes_digest"}
    if isinstance(scope, MoveScope):
        value = {name: getattr(scope, name) for name in names}
    elif isinstance(scope, Mapping) and set(scope) == names:
        value = scope
    else:
        raise ValueError("complete closed move data required")
    return {"move_schema": 1, **_data(value)}


def move_path_ids(path):
    if path in (None, "", "/"):
        return ()
    if not isinstance(path, str) or not path.startswith("/") or path.endswith("/"):
        raise ValueError("move_path_invalid")
    values = path[1:].split("/")
    if any(
        not value.isascii() or not value.isdecimal() or str(int(value)) != value or int(value) <= 0 for value in values
    ):
        raise ValueError("move_path_invalid")
    result = tuple(map(int, values))
    if len(set(result)) != len(result):
        raise ValueError("move_path_cycle")
    return result


def metadata_schema_fields(fields):
    if fields is None:
        return {}
    if not isinstance(fields, list):
        raise ValueError("move_metadata_schema_invalid")
    result = {}
    for item in fields:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("field_name"), str)
            or item.get("field_type") not in ("string", "number", "time")
            or item["field_name"] in result
        ):
            raise ValueError("move_metadata_schema_invalid")
        result[item["field_name"]] = item["field_type"]
    return result
