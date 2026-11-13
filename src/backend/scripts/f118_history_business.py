"""Selected business repairs for prepare_f118_history; never an independent writer.

The owning CLI saves this plan before apply. Existing frozen runs are excluded
by that CLI. Physical deletion is a separate, verified port and precedes the
single SQL repair transaction. No resource, model or authorization is invented.
"""

import re
from collections import defaultdict
from copy import deepcopy

from sqlalchemy import delete, update
from sqlmodel import select


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

    result = {}
    for name, model in models().items():
        query = select(model).order_by(model.id)
        if lock:
            query = query.with_for_update()
        result[name] = [canonical(row.model_dump()) for row in (await session.exec(query)).all()]
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
    from scripts.prepare_f118_history import checksum

    value = deepcopy(snapshot)
    # The following original history phase legitimately repairs these counters.
    for table in ("knowledgefile", "knowledge_document"):
        for row in value[table]:
            row.pop("level", None)
            row.pop("update_time", None)
    return checksum(value)


def build(snapshot, *, permission_modes=(), model_names=(), legacy_embedding_names=()):
    """Compile exact selected before rows and the expected complete SQL after."""
    from scripts.prepare_f118_history import folder_path

    original, after = deepcopy(snapshot), deepcopy(snapshot)
    plan = {"deletes": [], "updates": [], "physical": [], "blocked": []}
    roots = {r["id"]: r for r in snapshot["knowledge"]}
    files = {r["id"]: r for r in snapshot["knowledgefile"]}
    docs = {r["id"]: r for r in snapshot["knowledge_document"]}
    modes = defaultdict(list)
    for row in permission_modes:
        modes[row["resource_type"], row["resource_id"]].append(row)
    references = snapshot["business_resource_reference"]
    removed = defaultdict(set)

    def reject(table, row, reason):
        plan["blocked"].append({"table": table, "id": row["id"], "reason": reason})

    def remove(table, row, reason):
        if row["id"] not in removed[table]:
            plan["deletes"].append({"table": table, "before": deepcopy(row), "reason": reason})
            removed[table].add(row["id"])

    def change(table, row, values, reason):
        for item in plan["updates"]:
            if item["table"] == table and item["before"]["id"] == row["id"]:
                if any(k in item["values"] and item["values"][k] != v for k, v in values.items()):
                    reject(table, row, "conflicting_repair_values")
                    return
                item["values"].update(values)
                return
        plan["updates"].append({"table": table, "before": deepcopy(row), "values": values, "reason": reason})

    def file_references(ident):
        return [r for r in references if r["target_type"] == "knowledge_file" and r["target_id"] == str(ident)]

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
                candidates = []
                for job in snapshot["knowledge_space_delete_job"]:
                    manifest = job.get("manifest") or {}
                    owner = manifest.get("knowledge") or {}
                    if (
                        job["space_id"] == row["knowledge_id"]
                        and job["tenant_id"] == row["tenant_id"]
                        and ident in manifest.get("rows", ())
                        and owner.get("id") == row["knowledge_id"]
                        and owner.get("tenant_id") == row["tenant_id"]
                    ):
                        candidates.append(owner)
                signatures = {(r.get("index_name"), r.get("collection_name"), r.get("type")) for r in candidates}
                if len(signatures) == 1:
                    binding = candidates[0]
            if row["file_type"] == 1:
                if binding is None:
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

    tags = {r["id"]: r for r in snapshot["tag"]}
    corrected_files = {
        item["before"]["id"]: item["values"]["tenant_id"]
        for item in plan["updates"]
        if item["table"] == "knowledgefile"
    }
    surviving_links = defaultdict(list)
    for row in snapshot["taglink"]:
        tag = tags.get(row["tag_id"])
        numeric_file = row["resource_id"].isascii() and row["resource_id"].isdecimal()
        file = files.get(int(row["resource_id"])) if numeric_file else None
        missing_tag_parent = (
            tag is not None
            and tag["business_type"] in {"knowledge", "knowledge_space"}
            and tag["business_id"] not in {str(k) for k in roots}
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
                    siblings = [link for link in snapshot["taglink"] if link["tag_id"] == tag["id"]]
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
            surviving_links[row["tag_id"]].append(row)
    for row in tags.values():
        if row["business_type"] in {"knowledge", "knowledge_space"} and row["business_id"] not in {
            str(k) for k in roots
        }:
            if surviving_links[row["id"]]:
                reject("tag", row, "orphan_tag_has_surviving_links")
            else:
                remove("tag", row, "missing_tag_container")
    for row in snapshot["space_channel_member"]:
        if row["business_type"] == "space" and row["business_id"] not in {str(k) for k in roots}:
            remove("space_channel_member", row, "missing_member_space")

    flows = {r["id"]: r for r in snapshot["flow"]}
    for row in snapshot["flowversion"]:
        parent = flows.get(row["flow_id"])
        if parent is None or parent["flow_type"] != 10 or row["tenant_id"] == parent["tenant_id"]:
            continue
        indexed = any(
            r["tenant_id"] == row["tenant_id"]
            and r["source_type"] == "workflow_version"
            and r["source_id"] == row["flow_id"]
            for r in (*snapshot["business_reference_set"], *references)
        )
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
    for row in roots.values():
        model = row.get("model")
        if not model or (isinstance(model, str) and model.isascii() and model.isdecimal() and int(model) > 0):
            continue
        if row["type"] not in {0, 1, 3}:
            continue
        if isinstance(model, str) and re.fullmatch(r"[+-]?[0-9]+", model.strip()):
            reject("knowledge", row, "invalid_numeric_embedding_requires_resolution")
            continue
        remaining = any(
            f["knowledge_id"] == row["id"] and f["id"] not in removed["knowledgefile"] for f in files.values()
        ) or any(item["knowledge_id"] == row["id"] for item in snapshot["qaknowledge"])
        if not isinstance(model, str) or model in names or remaining or row.get("model_transition"):
            reject("knowledge", row, "legacy_embedding_requires_explicit_resolution")
        else:
            change("knowledge", row, {"model": None}, "unmapped_legacy_embedding")

    for item in plan["updates"]:
        for row in after[item["table"]]:
            if row["id"] == item["before"]["id"]:
                row.update(item["values"])
    for table, ids in removed.items():
        after[table] = [r for r in after[table] if r["id"] not in ids]
    plan.update(before_digest=state_digest(original), after_digest=state_digest(after))
    return plan, after


async def apply(session, plan):
    """The caller owns one native transaction and the no-active-freeze guard."""
    from scripts.prepare_f118_history import blocked

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
