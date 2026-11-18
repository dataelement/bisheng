"""Closed source inventory pages; serialization grants no migration authority."""

import json
import re
from dataclasses import dataclass, fields
from enum import StrEnum

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_sources import (
    ReferenceInventoryRecord,
    RetiredInventoryRecord,
    RootInventoryRecord,
    SourceInventoryRecord,
)
from bisheng.knowledge.domain.repositories.unification_target_repository import KnowledgeMigrationTargetFact
from bisheng.llm.domain.repositories.migration_target_repository import ModelMigrationTargetFact
from bisheng.resource_reference.application.contracts import (
    ReferenceSpec,
    SourceKey,
    SourceRootKey,
    SourceType,
    TargetKey,
    TargetType,
)

_MAX_BYTES = 16 * 1024 * 1024
_KEYS = {
    SourceRootKey: ("tenant_id", "source_type", "source_id"),
    SourceKey: ("tenant_id", "source_type", "source_id", "source_version"),
    TargetKey: ("target_type", "target_id"),
}
_FACTS = {
    ModelMigrationTargetFact: (
        "key",
        "exists",
        "target_tenant_id",
        "model_type",
        "is_online",
        "server_id",
        "server_exists",
        "server_tenant_id",
        "revision_digest",
    ),
    KnowledgeMigrationTargetFact: (
        "key",
        "exists",
        "target_tenant_id",
        "knowledge_id",
        "knowledge_type",
        "file_type",
        "space_exists",
        "space_tenant_id",
        "revision_digest",
    ),
}
_RECORDS = {
    RootInventoryRecord: (
        "root",
        (
            "root_key",
            "creator_id",
            "lifecycle",
            "configuration_digest",
            "retained_version_count",
            "business_revision_digest",
            "frozen_index",
        ),
    ),
    SourceInventoryRecord: (
        "source",
        (
            "source_key",
            "extractor_version",
            "configuration_digest",
            "reference_digest",
            "reference_count",
            "lifecycle",
            "business_revision_digest",
            "frozen_index",
        ),
    ),
    ReferenceInventoryRecord: (
        "reference",
        ("source_key", "slot_key", "target", "origin", "physical_fact", "frozen_state"),
    ),
    RetiredInventoryRecord: (
        "retired",
        ("root_key", "source_key", "lifecycle", "configuration_digest", "business_revision_digest", "frozen_index"),
    ),
}
_BY_TAG = {tag: (cls, names) for cls, (tag, names) in _RECORDS.items()}


def _invalid():
    raise KnowledgeOperationPlanConflictError(reason="migration_source_codec_invalid")


def _integer(value, *, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        _invalid()


def _text(value, maximum):
    if type(value) is not str or not value or len(value) > maximum or "\x00" in value:
        _invalid()


def _digest(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        _invalid()


def _identity(run_id, tenant_id, page_index):
    if type(run_id) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", run_id) is None:
        _invalid()
    _integer(tenant_id, minimum=1)
    _integer(page_index, minimum=0)


def _object(value, names):
    if type(value) is not dict or set(value) != set(names):
        _invalid()


def _canonical(value):
    try:
        content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _invalid()
    if len(content) > _MAX_BYTES:
        _invalid()
    return content


def _wire(value):
    """Explicit type/field allowlist prevents future raw fields escaping."""
    cls = type(value)
    if cls in _KEYS or cls in _FACTS or cls in _RECORDS:
        names = _KEYS.get(cls, _FACTS.get(cls))
        if cls in _RECORDS:
            tag, names = _RECORDS[cls]
        if {field.name for field in fields(cls)} != set(names):
            _invalid()
        from bisheng.knowledge.application.unification_reference_state import (
            parse_frozen,
            parse_retired,
            parse_root_index,
        )

        result = {
            name: (
                parse_root_index(getattr(value, name))
                if cls is RootInventoryRecord and getattr(value, name) is not None
                else parse_retired(getattr(value, name))
                if cls is RetiredInventoryRecord and getattr(value, name) is not None
                else parse_frozen(getattr(value, name), index=name == "frozen_index", allow_none=True)
            )
            if name in {"frozen_index", "frozen_state"}
            else _wire(getattr(value, name))
            for name in names
        }
        return {"record_type": tag, **result} if cls in _RECORDS else result
    if isinstance(value, StrEnum):
        return value.value
    if value is None or cls in (str, int, bool):
        return value
    if cls is tuple:
        return [_wire(item) for item in value]
    _invalid()


def _key(value, cls):
    _object(value, _KEYS[cls])
    if cls is TargetKey:
        if type(value["target_type"]) is not str or value["target_type"] not in {item.value for item in TargetType}:
            _invalid()
        ident = value["target_id"]
        if type(ident) is not str or re.fullmatch(r"[1-9][0-9]{0,63}", ident) is None:
            _invalid()
    else:
        _integer(value["tenant_id"], minimum=1)
        if type(value["source_type"]) is not str or value["source_type"] not in {item.value for item in SourceType}:
            _invalid()
        _text(value["source_id"], 64)
        if cls is SourceKey:
            _text(value["source_version"], 64)
            if value["source_version"] == "__root__":
                _invalid()
    return cls(**value)


def _fact(value, target):
    cls = ModelMigrationTargetFact if target.target_type is TargetType.MODEL else KnowledgeMigrationTargetFact
    _object(value, _FACTS[cls])
    fact = dict(value)
    fact["key"] = _key(value["key"], TargetKey)
    if fact["key"] != target:
        _invalid()
    flags = {"exists", "server_exists"} if cls is ModelMigrationTargetFact else {"exists", "space_exists"}
    for name in flags:
        if type(fact[name]) is not bool:
            _invalid()
    _digest(fact["revision_digest"])
    for name in set(_FACTS[cls]) - flags - {"key", "revision_digest"}:
        item = fact[name]
        if item is None:
            continue
        if name == "is_online":
            if type(item) is not bool:
                _invalid()
        elif name == "model_type":
            if type(item) is not str:
                _invalid()
        else:
            _integer(item)
    return cls(**fact)


def _record(value, tenant_id):
    if type(value) is not dict or type(value.get("record_type")) is not str or value["record_type"] not in _BY_TAG:
        _invalid()
    cls, names = _BY_TAG[value["record_type"]]
    _object(value, ("record_type", *names))
    item = {name: value[name] for name in names}
    for name, key_cls in (("root_key", SourceRootKey), ("source_key", SourceKey)):
        if name not in item or (name == "source_key" and cls is RetiredInventoryRecord and item[name] is None):
            continue
        item[name] = _key(item[name], key_cls)
        if item[name].tenant_id != tenant_id:
            _invalid()
    if cls is RetiredInventoryRecord and item["source_key"] is not None:
        source, root = item["source_key"], item["root_key"]
        if (source.tenant_id, source.source_type, source.source_id) != (
            root.tenant_id,
            root.source_type,
            root.source_id,
        ):
            _invalid()
    for name in ("configuration_digest", "reference_digest", "business_revision_digest"):
        if name in item:
            _digest(item[name])
    if "lifecycle" in item:
        lifecycle = item["lifecycle"]
        if type(lifecycle) is not list or any(
            value is not None and type(value) not in (str, int, bool) for value in lifecycle
        ):
            _invalid()
        item["lifecycle"] = tuple(lifecycle)
    for name in ("reference_count", "retained_version_count"):
        if name in item:
            _integer(item[name], minimum=0)
    if "creator_id" in item and item["creator_id"] is not None:
        _integer(item["creator_id"])
    from bisheng.knowledge.application.unification_reference_state import frozen_json, parse_retired, parse_root_index

    for name in ("frozen_index", "frozen_state"):
        if name in item and item[name] is not None:
            item[name] = (
                _canonical(parse_root_index(item[name])).decode()
                if cls is RootInventoryRecord
                else _canonical(parse_retired(item[name])).decode()
                if cls is RetiredInventoryRecord
                else frozen_json(item[name], index=name == "frozen_index")
            )
    if cls is SourceInventoryRecord:
        _text(item["extractor_version"], 64)
    if cls is ReferenceInventoryRecord:
        if type(item["slot_key"]) is not str:
            _invalid()
        if type(item["origin"]) is not str or item["origin"] not in {"explicit_id", "resolved_name"}:
            _invalid()
        item["target"] = _key(item["target"], TargetKey)
        try:
            ReferenceSpec(item["slot_key"], item["target"])
        except (ValueError, TypeError):
            _invalid()
        item["physical_fact"] = _fact(item["physical_fact"], item["target"])
    return cls(**item)


@dataclass(frozen=True, slots=True)
class DecodedSourcePage:
    tenant_id: int
    page_index: int
    records: tuple[RootInventoryRecord | SourceInventoryRecord | ReferenceInventoryRecord | RetiredInventoryRecord, ...]


def encode_source_page(*, run_id: str, tenant_id: int, page_index: int, records: tuple) -> bytes:
    _identity(run_id, tenant_id, page_index)
    if type(records) is not tuple or len(records) > 199:
        _invalid()
    encoded = []
    for record in records:
        if type(record) not in _RECORDS:
            _invalid()
        value = _wire(record)
        _record(value, tenant_id)
        encoded.append(value)
    header = {"record_type": "page", "tenant_id": tenant_id, "page_index": page_index, "record_count": len(records)}
    return _canonical({"schema_version": 1, "run_id": run_id, "kind": "sources", "records": [header, *encoded]})


def decode_source_page(content: bytes, *, run_id: str, tenant_id: int, page_index: int) -> DecodedSourcePage:
    _identity(run_id, tenant_id, page_index)
    if type(content) is not bytes or not content or len(content) > _MAX_BYTES:
        _invalid()
    try:
        envelope = json.loads(content.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        _invalid()
    _object(envelope, ("schema_version", "run_id", "kind", "records"))
    if (
        type(envelope["schema_version"]) is not int
        or envelope["schema_version"] != 1
        or envelope["run_id"] != run_id
        or envelope["kind"] != "sources"
    ):
        _invalid()
    records = envelope["records"]
    if type(records) is not list or not 1 <= len(records) <= 200 or _canonical(envelope) != content:
        _invalid()
    header = records[0]
    _object(header, ("record_type", "tenant_id", "page_index", "record_count"))
    for name in ("tenant_id", "page_index", "record_count"):
        _integer(header[name], minimum=1 if name == "tenant_id" else 0)
    if header != {
        "record_type": "page",
        "tenant_id": tenant_id,
        "page_index": page_index,
        "record_count": len(records) - 1,
    }:
        _invalid()
    return DecodedSourcePage(tenant_id, page_index, tuple(_record(record, tenant_id) for record in records[1:]))
