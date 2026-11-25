"""Closed history recipes/evidence paging over the existing verified store."""

import hashlib
import json

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_upgrade_materials import canonical, decode, envelope

_LIMIT = 16 * 1024 * 1024
_PAGE_BYTES = 1024 * 1024
_CONTRACT = "f118-history-pages-v1"
_REPLAY = {"schema_version", "history_sha256", "executable", "plan", "replay_sha256"}
_SEMANTIC = {
    "schema",
    "rows",
    "graph_writes",
    "graph_deletes",
    "logical_ids",
    "projection_plans",
    "run_id",
    "writer_contract_version",
    "environment",
    "planned_at",
    "history_sha256",
    "operator_binding",
    "operator_id",
}
_AFTER = {
    "schema_version",
    "history_sha256",
    "semantic_sha256",
    "verified_fact_count",
    "logical_id_map",
    "native_operation_ids",
    "complete",
}


def _reject(reason):
    raise KnowledgeOperationPlanConflictError(reason="history_material_" + reason, not_evaluated=True)


def _digest(value):
    digest = hashlib.sha256()
    try:
        for fragment in json.JSONEncoder(
            sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).iterencode(value):
            digest.update(fragment.encode())
    except (ValueError, TypeError, RecursionError) as error:
        raise KnowledgeOperationPlanConflictError(
            reason="history_material_unknown_atomic_value", not_evaluated=True
        ) from error
    return digest.hexdigest()


def _type(record, kind):
    if type(record) is not dict:
        _reject("record_required")
    if kind == "history_replay":
        if (
            set(record) != _REPLAY
            or type(record.get("schema_version")) is not int
            or record.get("schema_version") != 1
            or record.get("executable") is not True
        ):
            _reject("replay_schema")
        return "replay"
    if kind == "verification" and ("logical_ids" in record or "projection_plans" in record):
        if set(record) != _SEMANTIC or type(record.get("schema")) is not int or record.get("schema") != 1:
            _reject("semantic_schema")
        return "semantic"
    if kind == "verification" and "verified_fact_count" in record:
        if (
            set(record) != _AFTER
            or type(record.get("schema_version")) is not int
            or record.get("schema_version") != 1
            or record.get("complete") is not True
        ):
            _reject("after_schema")
        return "after"
    return None


def _list_path(path, category):
    key = tuple("$" if type(part) is int else part for part in path)
    if (
        len(path) >= 2
        and type(path[-1]) is int
        and path[-2] in {"incoming", "deletes", "parent_deletes", "graph_writes", "graph_deletes"}
    ):
        return _list_path(path[:-1], category)
    if category == "semantic":
        return key in {
            ("rows",),
            ("graph_writes",),
            ("graph_deletes",),
            ("logical_ids",),
            ("projection_plans",),
            ("rows", "$", "ignore_fields"),
            ("projection_plans", "$", "plan", "deltas"),
        }
    if category == "after":
        return key in {("logical_id_map",), ("native_operation_ids",)}
    actions = {
        "levels",
        "parents",
        "purges",
        "blocked",
        "initializations",
        "recoveries",
        "delete_closures",
        "permission_delete_retained",
        "builtin_finalizations",
        "empty_root_initializations",
        "retained_evidence",
    }
    business = {"updates", "deletes", "physical", "blocked", "retained", "warnings"}
    if len(key) == 2 and key[0] == "plan" and key[1] in actions:
        return True
    if len(key) == 3 and key[:2] == ("plan", "business") and key[2] in business:
        return True
    if len(key) >= 3 and key[0] == "plan" and key[1] in actions and key[2] == "$":
        rest = key[3:]
        if rest in {
            ("ancestors",),
            ("objects",),
            ("tuples",),
            ("incoming",),
            ("deletes",),
            ("correct",),
            ("parent_deletes",),
            ("business_digests",),
            ("preview", "correction_deltas"),
        }:
            return True
        if (
            len(rest) == 2
            and rest[0] in {"sql", "mirrors"}
            and rest[1]
            in {
                "resource_permission_mode",
                "permission_grant",
                "permission_grant_assignee",
                "permission_visible_source_projection",
            }
        ):
            return True
    elif len(key) >= 4 and key[:2] == ("plan", "business") and key[2] in business and key[3] == "$":
        rest = key[4:]
    else:
        return False
    if rest[-2:] not in {("history_row", "allowed"), ("history_row", "ignore")}:
        return False
    return rest[:-2] in {("before",), ("root",), ("file",), ("before_file",), ("business",), ("ancestors", "$")}


def _identity(path, value):
    name = path[-1] if path else None
    if name == "deletes" and type(value) in {list, tuple}:
        return _digest(value)
    if name in {
        "graph_writes",
        "graph_deletes",
        "incoming",
        "objects",
        "native_operation_ids",
        "allowed",
        "ignore",
        "ignore_fields",
        "parent_deletes",
    }:
        return _digest(value)
    if type(value) is not dict:
        return None
    if name in {"levels", "updates", "deletes", "retained"}:
        before = value.get("before", {})
        row = before.get("history_row", {}).get("identity", before)
        return _digest([value.get("table"), row.get("id")])
    if name == "permission_delete_retained":
        return _digest([value.get(key) for key in ("tenant_id", "resource_type", "resource_id", "operation_id")])
    if name == "ancestors":
        row = value.get("history_row", {}).get("identity", value)
        return _digest(row.get("id"))
    if name == "rows":
        return _digest([value.get("table"), value.get("id")])
    if name in {"logical_ids", "logical_id_map"}:
        return _digest([value.get("table"), value.get("identity", value.get("preview_id"))])
    if name == "projection_plans":
        return _digest(value.get("preview_operation_id"))
    if name in {"deltas", "correction_deltas"}:
        return _digest([value.get("phase"), value.get("sequence")])
    if name == "tuples":
        return _digest([value.get("user"), value.get("relation"), value.get("object")])
    if name in {"purges", "parents", "recoveries", "delete_closures", "builtin_finalizations"}:
        return _digest(value.get("mode", {}).get("id"))
    if name in {"initializations", "empty_root_initializations"}:
        field = "business" if name == "empty_root_initializations" else "file"
        row = value.get(field, {})
        return _digest(row.get("id", row.get("history_row", {}).get("identity", {}).get("id")))
    if name in {
        "resource_permission_mode",
        "permission_grant",
        "permission_grant_assignee",
        "permission_visible_source_projection",
    }:
        return _digest(value.get("id"))
    return None


async def aput_history_record(store, *, run_id, kind, record):
    category = _type(record, kind)
    body_hash = _digest(record)
    # Preserve already-issued single-record material and every other Owner's
    # envelope/schema. Only oversized, recognized history bodies are paged.
    content = canonical(envelope(run_id, kind, [record]))
    if len(content) <= _LIMIT:
        return await store.aput_canonical(run_id=run_id, kind=kind, content=content)
    if category is None:
        _reject("unsupported_oversized_record")
    del content

    async def put(value):
        content = canonical(envelope(run_id, kind, [value]))
        if len(content) > _PAGE_BYTES:
            _reject("unsplittable_atomic_value")
        return await store.aput_canonical(run_id=run_id, kind=kind, content=content)

    async def walk(value, path):
        if type(value) is dict:
            if any(type(key) is not str or key.startswith("history_material_") for key in value):
                _reject("unknown_field")
            return {key: await walk(item, [*path, key]) for key, item in value.items()}
        if type(value) in {list, tuple}:
            if not _list_path(path, category):
                _reject("unknown_array")
            # An endpoint tuple/ignore list is an atomic small list, retaining
            # its exact native value. Large known lists become typed pages.
            if value and all(type(item) in {str, int, bool, type(None)} for item in value) and len(value) <= 200:
                if len(canonical(value)) > _PAGE_BYTES // 2:
                    _reject("unsplittable_atomic_value")
                return list(value)
            refs, pending, offset, identities, pending_bytes = [], [], 0, set(), 2

            async def flush():
                nonlocal offset, pending, pending_bytes
                if not pending:
                    return
                page = {
                    "history_material_page": 1,
                    "contract": _CONTRACT,
                    "category": category,
                    "body_sha256": body_hash,
                    "path": path,
                    "page_index": len(refs),
                    "start": offset,
                    "count": len(pending),
                    "items_sha256": _digest(pending),
                    "items": pending,
                }
                ref = await put(page)
                refs.append({"page_index": len(refs), "start": offset, "count": len(pending), "ref": ref})
                offset += len(pending)
                pending = []
                pending_bytes = 2

            for index, item in enumerate(value):
                identity = _identity(path, item)
                if identity is not None:
                    if identity in identities:
                        _reject("duplicate_fact")
                    identities.add(identity)
                item = await walk(item, [*path, index])
                item_bytes = len(canonical(item))
                if item_bytes > _PAGE_BYTES // 2:
                    _reject("unsplittable_atomic_value")
                if pending and (len(pending) == 200 or pending_bytes + item_bytes + 1 > _PAGE_BYTES // 2):
                    await flush()
                pending.append(item)
                pending_bytes += item_bytes + 1
            await flush()
            return {
                "history_material_array": 1,
                "contract": _CONTRACT,
                "category": category,
                "body_sha256": body_hash,
                "path": path,
                "count": len(value),
                "array_sha256": _digest(value),
                "pages": refs,
            }
        if type(value) not in {str, int, float, bool, type(None)}:
            _reject("unknown_atomic_value")
        if len(canonical(value)) > _PAGE_BYTES // 2:
            _reject("unsplittable_atomic_value")
        return value

    transformed = await walk(record, [])
    return await put(
        {
            "history_material_directory": 1,
            "contract": _CONTRACT,
            "category": category,
            "body_sha256": body_hash,
            "body": transformed,
        }
    )


async def aload_history_record(store, ref, *, run_id, kind):
    async def read(descriptor):
        value = decode(await store.aload_canonical(descriptor, run_id=run_id, kind=kind))
        if (
            set(value) != {"schema_version", "run_id", "kind", "records"}
            or value["schema_version"] != 1
            or value["run_id"] != run_id
            or value["kind"] != kind
            or len(value["records"]) != 1
            or type(value["records"][0]) is not dict
        ):
            _reject("envelope_changed")
        return value["records"][0]

    root = await read(ref)
    if "history_material_directory" not in root:
        _type(root, kind)
        return root
    if (
        set(root) != {"history_material_directory", "contract", "category", "body_sha256", "body"}
        or type(root["history_material_directory"]) is not int
        or root["history_material_directory"] != 1
        or root["contract"] != _CONTRACT
        or root["category"] not in {"replay", "semantic", "after"}
    ):
        _reject("directory_changed")
    body_hash, category, page_refs = root["body_sha256"], root["category"], set()

    async def walk(value, path):
        if type(value) is list:
            if (
                not _list_path(path, category)
                or len(value) > 200
                or any(type(item) not in {str, int, bool, type(None)} for item in value)
            ):
                _reject("atomic_array_changed")
            return value
        if type(value) is not dict:
            if type(value) not in {str, int, float, bool, type(None)}:
                _reject("unknown_atomic_value")
            return value
        if "history_material_array" not in value:
            if any(key.startswith("history_material_") for key in value):
                _reject("unknown_field")
            return {key: await walk(item, [*path, key]) for key, item in value.items()}
        if (
            set(value)
            != {
                "history_material_array",
                "contract",
                "category",
                "body_sha256",
                "path",
                "count",
                "array_sha256",
                "pages",
            }
            or type(value["history_material_array"]) is not int
            or value["history_material_array"] != 1
            or value["contract"] != _CONTRACT
            or value["category"] != category
            or value["body_sha256"] != body_hash
            or value["path"] != path
            or not _list_path(path, category)
            or type(value["count"]) is not int
            or value["count"] < 0
            or type(value["pages"]) is not list
        ):
            _reject("array_directory_changed")
        result, identities = [], set()
        for index, entry in enumerate(value["pages"]):
            if (
                type(entry) is not dict
                or set(entry) != {"page_index", "start", "count", "ref"}
                or type(entry["page_index"]) is not int
                or type(entry["start"]) is not int
                or entry["page_index"] != index
                or entry["start"] != len(result)
                or type(entry["count"]) is not int
                or not 1 <= entry["count"] <= 200
            ):
                _reject("page_order_or_count_changed")
            identity = _digest(entry["ref"])
            if identity in page_refs:
                _reject("duplicate_page")
            page_refs.add(identity)
            page = await read(entry["ref"])
            if (
                set(page)
                != {
                    "history_material_page",
                    "contract",
                    "category",
                    "body_sha256",
                    "path",
                    "page_index",
                    "start",
                    "count",
                    "items_sha256",
                    "items",
                }
                or type(page["history_material_page"]) is not int
                or page["history_material_page"] != 1
                or page["contract"] != _CONTRACT
                or page["category"] != category
                or page["body_sha256"] != body_hash
                or page["path"] != path
                or type(page["page_index"]) is not int
                or page["page_index"] != index
                or type(page["start"]) is not int
                or page["start"] != len(result)
                or type(page["count"]) is not int
                or page["count"] != entry["count"]
                or type(page["items"]) is not list
                or len(page["items"]) != entry["count"]
                or _digest(page["items"]) != page["items_sha256"]
            ):
                _reject("page_changed")
            for item in page["items"]:
                item = await walk(item, [*path, len(result)])
                identity = _identity(path, item)
                if identity is not None:
                    if identity in identities:
                        _reject("duplicate_fact")
                    identities.add(identity)
                result.append(item)
        if len(result) != value["count"] or _digest(result) != value["array_sha256"]:
            _reject("array_incomplete")
        return result

    record = await walk(root["body"], [])
    if _type(record, kind) != category or _digest(record) != body_hash:
        _reject("body_changed")
    return record
