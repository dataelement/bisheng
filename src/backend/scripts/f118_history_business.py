"""Selected business repairs for prepare_f118_history; never an independent writer.

The owning CLI saves this plan before apply. Existing frozen runs are excluded
by that CLI. Physical deletion is a separate, verified port and precedes the
single SQL repair transaction. No resource, model or authorization is invented.
"""

import json
import re
from collections import defaultdict
from copy import deepcopy
from hashlib import sha256
from itertools import chain

from sqlalchemy import delete, update
from sqlmodel import select

from scripts.f118_history_snapshot import SnapshotRows, SnapshotStore

PAGE_SIZE = 200


def row_index(rows):
    return rows.by_id() if isinstance(rows, SnapshotRows) else {row["id"]: row for row in rows}


def group_index(rows, fields):
    if isinstance(rows, SnapshotRows):
        return rows.grouped(fields)
    result = defaultdict(list)
    for row in rows:
        key = row[fields[0]] if len(fields) == 1 else tuple(row[field] for field in fields)
        result[key].append(row)
    return result


def models():
    from bisheng.common.models.space_channel_member import SpaceChannelMember
    from bisheng.database.models.flow import Flow
    from bisheng.database.models.flow_version import FlowVersion
    from bisheng.database.models.tag import Tag, TagLink
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, QAKnowledge
    from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob
    from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
    from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference

    return {
        m.__tablename__: m
        for m in (
            Knowledge,
            KnowledgeFile,
            QAKnowledge,
            KnowledgeDocument,
            KnowledgeDocumentVersion,
            Tag,
            TagLink,
            SpaceChannelMember,
            Flow,
            FlowVersion,
            BusinessReferenceSet,
            BusinessResourceReference,
            KnowledgeSpaceDeleteJob,
        )
    }


async def read(session, *, lock=False):
    import yaml

    from bisheng.common.models.config import Config
    from bisheng.llm.domain.models.llm_server import LLMModel
    from scripts.prepare_f118_history import canonical

    result, store = {}, SnapshotStore()
    for name, model in models().items():
        after = None
        while True:
            query = select(model).order_by(model.id).limit(PAGE_SIZE)
            if after is not None:
                query = query.where(model.id > after)
            if lock:
                query = query.with_for_update()
            rows = (await session.exec(query)).all()
            store.append(name, [canonical(row.model_dump()) for row in rows])
            if len(rows) < PAGE_SIZE:
                break
            after = rows[-1].id
        result[name] = store.rows(name)
    catalog = (await session.exec(select(LLMModel.name, LLMModel.model_name).order_by(LLMModel.id))).all()
    result["_model_names"] = sorted({v for row in catalog for v in row if v})
    configs = (await session.exec(select(Config.value).where(Config.key == "initdb_config"))).all()
    aliases = set()
    for raw in configs:
        value = yaml.safe_load(raw) or {}
        aliases.update((value.get("knowledges") or {}).get("embeddings") or {})
    result["_legacy_embedding_names"] = sorted(aliases)
    return result


def state_digest(snapshot):
    # Preserve the schema-1 canonical digest byte for byte, without cloning or
    # encoding the full inventory. Only these two historical counters are mutable.
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    result = sha256()

    def add(value):
        result.update(value.encode())

    add("{")
    for index, table in enumerate(sorted(snapshot)):
        add(("," if index else "") + encoder.encode(table) + ":")
        if table.startswith("_"):
            for fragment in encoder.iterencode(snapshot[table]):
                add(fragment)
            continue
        add("[")
        for position, row in enumerate(snapshot[table]):
            if table in {"knowledgefile", "knowledge_document"}:
                row = {key: value for key, value in row.items() if key not in {"level", "update_time"}}
            if position:
                add(",")
            for fragment in encoder.iterencode(row):
                add(fragment)
        add("]")
    add("}")
    return result.hexdigest()


def build(snapshot, *, permission_modes=(), model_names=(), legacy_embedding_names=()):
    """Compile exact selected before rows and the expected complete SQL after."""
    from scripts.prepare_f118_history import folder_path

    plan = {"deletes": [], "updates": [], "physical": [], "blocked": [], "retained": [], "warnings": []}
    roots = row_index(snapshot["knowledge"])
    files = row_index(snapshot["knowledgefile"])
    docs = row_index(snapshot["knowledge_document"])
    modes = group_index(permission_modes, ("resource_type", "resource_id"))
    references = snapshot["business_resource_reference"]
    removed = defaultdict(set)
    root_ids = {str(ident) for ident in roots}
    updates = {}
    references_by_file = group_index(references, ("target_type", "target_id"))
    links_by_tag = group_index(snapshot["taglink"], ("tag_id",))
    registrations = set()
    deleted_bindings = defaultdict(list)
    for ref in chain(snapshot["business_reference_set"], references):
        if ref["source_type"] == "workflow_version":
            registrations.add((ref["tenant_id"], ref["source_id"]))
    for job in snapshot["knowledge_space_delete_job"]:
        manifest = job.get("manifest") or {}
        owner = manifest.get("knowledge") or {}
        if owner.get("id") == job["space_id"] and owner.get("tenant_id") == job["tenant_id"]:
            for ident in manifest.get("rows", ()):
                deleted_bindings[(job["space_id"], job["tenant_id"], ident)].append(owner)

    def reject(table, row, reason):
        plan["blocked"].append({"table": table, "id": row["id"], "reason": reason})

    def remove(table, row, reason):
        if row["id"] not in removed[table]:
            plan["deletes"].append({"table": table, "before": deepcopy(row), "reason": reason})
            removed[table].add(row["id"])

    def change(table, row, values, reason):
        key = (table, row["id"])
        if key in updates:
            item = updates[key]
            if any(k in item["values"] and item["values"][k] != v for k, v in values.items()):
                reject(table, row, "conflicting_repair_values")
                return
            item["values"].update(values)
            return
        item = {"table": table, "before": deepcopy(row), "values": values, "reason": reason}
        updates[key] = item
        plan["updates"].append(item)

    def file_references(ident):
        return references_by_file.get(("knowledge_file", str(ident)), ())

    for ident, row in files.items():
        root = roots.get(row["knowledge_id"])
        try:
            path = folder_path(row["file_level_path"])
            if ident in path:
                raise ValueError("cycle")
        except ValueError:
            reject("knowledgefile", row, "ambiguous_parent_path")
            continue
        orphan = root is None or any(parent not in files for parent in path)
        if orphan:
            # A saved direct reference is not silently discarded. Its owning
            # business must resolve it, or explicitly register target deletion.
            if file_references(ident):
                reject("knowledgefile", row, "orphan_has_saved_reference")
                continue
            kind = "folder" if row["file_type"] == 0 else "knowledge_file"
            current_modes = modes[kind, str(ident)]
            if any(m["projection_state"] != "CURRENT" for m in current_modes):
                reject("knowledgefile", row, "orphan_permission_not_current")
                continue
            binding = root
            if binding is None:
                candidates = deleted_bindings.get((row["knowledge_id"], row["tenant_id"], ident), ())
                signatures = {(r.get("index_name"), r.get("collection_name"), r.get("type")) for r in candidates}
                if len(signatures) == 1:
                    binding = candidates[0]
            if row["file_type"] == 1:
                if binding is None:
                    # A missing physical binding prevents deletion, not the
                    # preservation of an already unreachable historical row.
                    # The owner capture still proves the absence of SQL/FGA
                    # authorization; formal M2 freezes and rechecks the row.
                    if root is None and not path and not current_modes:
                        plan["retained"].append(
                            {
                                "table": "knowledgefile",
                                "before": deepcopy(row),
                                "reason": "retain_rootless_file_without_index_binding",
                            }
                        )
                        plan["warnings"].append(
                            {"table": "knowledgefile", "id": ident, "reason": "historical_orphan_preserved"}
                        )
                    else:
                        reject("knowledgefile", row, "orphan_original_index_binding_unavailable")
                    continue
                plan["physical"].append({"file": deepcopy(row), "knowledge": deepcopy(binding)})
            remove("knowledgefile", row, "missing_parent_resource")
            continue
        if row["tenant_id"] != root["tenant_id"]:
            owned = modes["folder" if row["file_type"] == 0 else "knowledge_file", str(ident)]
            if any(m["tenant_id"] != root["tenant_id"] or m["projection_state"] != "CURRENT" for m in owned):
                reject("knowledgefile", row, "file_tenant_has_conflicting_permission_owner")
                continue
            change("knowledgefile", row, {"tenant_id": root["tenant_id"]}, "parent_tenant")
            for ref in file_references(ident):
                if ref["target_tenant_id"] != root["tenant_id"]:
                    change("business_resource_reference", ref, {"target_tenant_id": root["tenant_id"]}, "target_owner")

    # A retained child/reference also retains all of its existing ancestors.
    # Never leave a live child dangling merely because its parent was selected
    # earlier in this pass.
    while True:
        keep = set()
        for row in files.values():
            if row["id"] in removed["knowledgefile"]:
                continue
            try:
                keep.update(folder_path(row["file_level_path"]))
            except ValueError:
                # Already reported above; all selected ancestors remain guarded.
                continue
        retained = keep & removed["knowledgefile"]
        if not retained:
            break
        for ident in retained:
            removed["knowledgefile"].remove(ident)
            reject("knowledgefile", files[ident], "orphan_directory_has_retained_child")
        plan["deletes"] = [
            i for i in plan["deletes"] if not (i["table"] == "knowledgefile" and i["before"]["id"] in retained)
        ]

    valid_versions = defaultdict(list)
    for row in snapshot["knowledge_document_version"]:
        doc, file = docs.get(row["document_id"]), files.get(row["knowledge_file_id"])
        if (
            doc is None
            or doc["knowledge_id"] not in roots
            or file is None
            or file["id"] in removed["knowledgefile"]
            or file["file_type"] != 1
            or file["knowledge_id"] != doc["knowledge_id"]
        ):
            remove("knowledge_document_version", row, "invalid_document_file_relation")
        else:
            valid_versions[doc["id"]].append(row)
    for row in docs.values():
        if row["knowledge_id"] not in roots or not valid_versions[row["id"]]:
            remove("knowledge_document", row, "document_without_valid_file")
        elif row["primary_version_id"] in removed["knowledge_document_version"]:
            reject("knowledge_document", row, "remaining_versions_require_primary_decision")

    tags = row_index(snapshot["tag"])
    corrected_files = {
        item["before"]["id"]: item["values"]["tenant_id"]
        for item in plan["updates"]
        if item["table"] == "knowledgefile"
    }
    surviving_tags = set()
    for row in snapshot["taglink"]:
        tag = tags.get(row["tag_id"])
        numeric_file = row["resource_id"].isascii() and row["resource_id"].isdecimal()
        file = files.get(int(row["resource_id"])) if numeric_file else None
        missing_tag_parent = (
            tag is not None
            and tag["business_type"] in {"knowledge", "knowledge_space"}
            and tag["business_id"] not in root_ids
        )
        if tag is None or (
            row["resource_type"] in {8, 9}
            and (file is None or file["id"] in removed["knowledgefile"] or missing_tag_parent)
        ):
            remove("taglink", row, "invalid_tag_or_file")
        else:
            if file is not None and file["id"] in corrected_files and row["resource_type"] in {8, 9}:
                tenant = corrected_files[file["id"]]
                if tag["tenant_id"] != tenant:
                    siblings = links_by_tag[tag["id"]]
                    if (
                        tag["business_type"] not in {"knowledge", "knowledge_space"}
                        or tag["business_id"] != str(file["knowledge_id"])
                        or any(
                            link["resource_type"] not in {8, 9}
                            or not link["resource_id"].isdecimal()
                            or files.get(int(link["resource_id"]), {}).get("knowledge_id") != file["knowledge_id"]
                            for link in siblings
                        )
                    ):
                        reject("taglink", row, "file_owner_has_conflicting_tag_owner")
                    else:
                        change("tag", tag, {"tenant_id": tenant}, "container_owner")
                if row["tenant_id"] != tenant:
                    change("taglink", row, {"tenant_id": tenant}, "target_file_owner")
            surviving_tags.add(row["tag_id"])
    for row in tags.values():
        if row["business_type"] in {"knowledge", "knowledge_space"} and row["business_id"] not in root_ids:
            if row["id"] in surviving_tags:
                reject("tag", row, "orphan_tag_has_surviving_links")
            else:
                remove("tag", row, "missing_tag_container")
    for row in snapshot["space_channel_member"]:
        if row["business_type"] == "space" and row["business_id"] not in root_ids:
            remove("space_channel_member", row, "missing_member_space")

    flows = row_index(snapshot["flow"])
    for row in snapshot["flowversion"]:
        parent = flows.get(row["flow_id"])
        if parent is None or parent["flow_type"] != 10 or row["tenant_id"] == parent["tenant_id"]:
            continue
        indexed = (row["tenant_id"], row["flow_id"]) in registrations
        if indexed or any(m["tenant_id"] == row["tenant_id"] for m in modes["workflow", row["flow_id"]]):
            reject("flowversion", row, "version_owner_has_existing_registration")
        else:
            change("flowversion", row, {"tenant_id": parent["tenant_id"]}, "parent_workflow_tenant")

    names = (
        set(model_names)
        | set(legacy_embedding_names)
        | set(snapshot.get("_model_names", ()))
        | set(snapshot.get("_legacy_embedding_names", ()))
    )
    populated_roots = {row["knowledge_id"] for row in files.values() if row["id"] not in removed["knowledgefile"]} | {
        row["knowledge_id"] for row in snapshot["qaknowledge"]
    }
    for row in roots.values():
        model = row.get("model")
        if not model or (isinstance(model, str) and model.isascii() and model.isdecimal() and int(model) > 0):
            continue
        if row["type"] not in {0, 1, 3}:
            continue
        if isinstance(model, str) and re.fullmatch(r"[+-]?[0-9]+", model.strip()):
            reject("knowledge", row, "invalid_numeric_embedding_requires_resolution")
            continue
        remaining = row["id"] in populated_roots
        from bisheng.knowledge.domain.services.model_reference_extractor import legacy_knowledge_model_version

        if legacy_knowledge_model_version(model, row.get("model_transition")) is not None and (
            remaining or model in names
        ):
            plan["warnings"].append({"table": "knowledge", "id": row["id"], "reason": "legacy_embedding_preserved"})
        elif not isinstance(model, str) or model in names or remaining or row.get("model_transition"):
            reject("knowledge", row, "legacy_embedding_requires_explicit_resolution")
        else:
            change("knowledge", row, {"model": None}, "unmapped_legacy_embedding")

    by_table = defaultdict(dict)
    for (table, ident), item in updates.items():
        by_table[table][ident] = item["values"]
    after = {
        table: rows.overlay(by_table[table], removed[table])
        if isinstance(rows, SnapshotRows)
        else [
            {**row, **updates[(table, row["id"])]["values"]} if (table, row["id"]) in updates else row
            for row in rows
            if row["id"] not in removed[table]
        ]
        if not table.startswith("_")
        else rows
        for table, rows in snapshot.items()
    }
    plan.update(before_digest=state_digest(snapshot), after_digest=state_digest(after))
    return plan, after


async def apply(session, plan):
    """The caller owns one native transaction and the no-active-freeze guard."""
    from scripts.prepare_f118_history import blocked

    # No-op/replay still validates the complete current digest, but acquires no
    # write locks. Real repairs retain the original full-scope locked recheck.
    current = await read(session)
    digest = state_digest(current)
    if digest == plan["after_digest"]:
        return
    if digest != plan["before_digest"]:
        blocked("business_scope_changed")
    current = await read(session, lock=True)
    digest = state_digest(current)
    if digest == plan["after_digest"]:
        return
    if digest != plan["before_digest"]:
        blocked("business_scope_changed")
    registry = models()
    for item in plan["updates"]:
        table = registry[item["table"]].__table__
        values = dict(item["values"])
        if "update_time" in table.c:
            values["update_time"] = table.c.update_time
        await session.exec(update(table).where(table.c.id == item["before"]["id"]).values(**values))
    # Break only pointers on documents which themselves are being removed.
    for item in plan["deletes"]:
        if item["table"] == "knowledge_document":
            table = registry[item["table"]].__table__
            await session.exec(update(table).where(table.c.id == item["before"]["id"]).values(primary_version_id=None))
    order = {
        name: i
        for i, name in enumerate(
            (
                "taglink",
                "knowledge_document_version",
                "knowledge_document",
                "space_channel_member",
                "tag",
                "knowledgefile",
            )
        )
    }
    for item in sorted(plan["deletes"], key=lambda r: order[r["table"]]):
        table = registry[item["table"]].__table__
        await session.exec(delete(table).where(table.c.id == item["before"]["id"]))
    if state_digest(await read(session)) != plan["after_digest"]:
        blocked("business_after_changed")
