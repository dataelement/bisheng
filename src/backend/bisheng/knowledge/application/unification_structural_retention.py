"""Closed evidence for approved original structural invalidity; no new rights.

Existing empty SPACE creators are retained without reassignment. FAILED files
with one absent directory and no SQL/FGA authorization retain their exact rows.
The full frozen graph proves the exceptions rather than bypassing validation.
"""

import re
from collections import Counter

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_inventory_codec import digest, record_from_values

CREATOR_RETENTION = "existing_space_creator_retention"
FILE_RETENTION = "stranded_file_retention"
RETENTIONS = frozenset({CREATOR_RETENTION, FILE_RETENTION})


def retained_invalid_assistant_creator(root, source):
    """Bind the approved invalid-name source to its unchanged original owner."""
    from bisheng.assistant.domain.services.reference_extractor import LEGACY_NAME_PREFIX
    from bisheng.knowledge.application.unification_sources import RootInventoryRecord, SourceInventoryRecord
    from bisheng.resource_reference.application.contracts import SourceRootKey

    return (
        type(root) is RootInventoryRecord
        and type(source) is SourceInventoryRecord
        and root.root_key.source_type.value == "assistant"
        and source.source_key.source_version == "current"
        and root.root_key
        == SourceRootKey(source.source_key.tenant_id, source.source_key.source_type, source.source_key.source_id)
        and type(root.creator_id) is int
        and root.creator_id > 0
        and root.retained_version_count == 1
        and re.fullmatch(re.escape(LEGACY_NAME_PREFIX) + r"[0-9a-f]{32}", source.extractor_version) is not None
        and (root.configuration_digest, root.business_revision_digest, root.lifecycle)
        == (source.configuration_digest, source.business_revision_digest, source.lifecycle)
    )


def blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason="structural_retention_" + reason)


def creator_retention(*, resource, creator, managed_file_count):
    if (
        resource["type"] != 3
        or type(managed_file_count) is not int
        or managed_file_count != 0
        or creator != {"user_id": resource["user_id"], "exists": False, "delete": None}
        or type(resource["user_id"]) is not int
        or resource["user_id"] <= 0
    ):
        blocked("original_empty_space_creator_required")
    return record_from_values(
        CREATOR_RETENTION,
        tenant_id=resource["tenant_id"],
        space_id=resource["id"],
        creator_user_id=resource["user_id"],
        managed_file_count=0,
        reason="preserve_existing_empty_space_missing_creator",
        resource_digest=digest(resource),
        creator_digest=digest(creator),
    )


def absent_parent(ident):
    return {
        "id": ident,
        "exists": False,
        "tenant_id": None,
        "knowledge_id": None,
        "file_type": None,
        "level": None,
        "file_level_path": None,
        "update_time": None,
    }


def stranded_retention(*, resource, file, ancestor, sql_permission_count, fga_tuple_count):
    path = file["file_level_path"]
    if (
        resource["type"] != 3
        or (file["tenant_id"], file["knowledge_id"]) != (resource["tenant_id"], resource["id"])
        or file["file_type"] != 1
        or file["status"] != 3
        or file["file_source"] != "space_upload"
        or file["level"] != 1
        or type(path) is not str
        or re.fullmatch(r"/[1-9][0-9]*", path) is None
        or type(sql_permission_count) is not int
        or sql_permission_count != 0
        or type(fga_tuple_count) is not int
        or fga_tuple_count != 0
    ):
        blocked("original_failed_unassigned_file_required")
    parent = int(path[1:])
    if parent == file["id"] or ancestor != absent_parent(parent):
        blocked("absent_original_directory_required")
    return record_from_values(
        FILE_RETENTION,
        tenant_id=file["tenant_id"],
        space_id=file["knowledge_id"],
        file_id=file["id"],
        missing_parent_id=parent,
        sql_permission_count=0,
        fga_tuple_count=0,
        reason="preserve_failed_file_without_parent_or_permissions",
        resource_digest=digest(resource),
        file_digest=digest(file),
        ancestor_digest=digest(ancestor),
    )


def _path(value):
    if value in (None, ""):
        return ()
    if type(value) is not str:
        blocked("invalid_ancestor_path")
    parts = tuple(part for part in value.split("/") if part)
    if any(re.fullmatch(r"[1-9][0-9]*", part) is None for part in parts):
        blocked("invalid_ancestor_path")
    ids = tuple(map(int, parts))
    if len(set(ids)) != len(ids):
        blocked("ancestor_cycle")
    return ids


class StructuralRetentionInventoryVerifier:
    def __init__(self):
        self.resources, self.files, self.creators = {}, {}, {}
        self.proofs = {tag: {} for tag in RETENTIONS}
        self.permissions, self.fga = Counter(), set()
        self.sources = []
        self.source_roots, self.source_headers = {}, {}
        self.file_reference_targets = set()

    def observe_source(self, record):
        from bisheng.knowledge.application.unification_sources import (
            ReferenceInventoryRecord,
            RootInventoryRecord,
            SourceInventoryRecord,
        )
        from bisheng.resource_reference.application.contracts import SourceRootKey

        if type(record) is ReferenceInventoryRecord and record.target.target_type.value == "knowledge_file":
            self.file_reference_targets.add(int(record.target.target_id))
        if type(record) is RootInventoryRecord and record.creator_id is not None:
            self.sources.append((record.root_key, record.creator_id))
            self.source_roots[record.root_key] = record
        if type(record) is SourceInventoryRecord:
            key = record.source_key
            self.source_headers[SourceRootKey(key.tenant_id, key.source_type, key.source_id)] = record

    def observe(self, *, kind, section, tenant_id, record):
        tag, value = record.record_type, record.data
        if tag in RETENTIONS:
            if (kind, section) != ("plan", "control") or value["tenant_id"] != tenant_id:
                blocked("proof_scope")
            ident = value["space_id"] if tag == CREATOR_RETENTION else value["file_id"]
            key = tenant_id, ident
            if key in self.proofs[tag]:
                blocked("duplicate_proof")
            self.proofs[tag][key] = value
        elif kind == "baseline":
            if tag in {"resource", "file"}:
                if section != "resources" or value["tenant_id"] != tenant_id:
                    blocked("resource_scope")
                rows = self.resources if tag == "resource" else self.files
                key = tenant_id, value["id"]
                if key in rows:
                    blocked("duplicate_resource")
                rows[key] = value
            elif tag == "creator":
                if section != "control":
                    blocked("creator_scope")
                key = tenant_id, value["user_id"]
                if key in self.creators and self.creators[key] != value:
                    blocked("creator_drift")
                self.creators[key] = value
            elif tag in {"resource_mode", "grant", "visible_source"}:
                row = value["source"] if tag == "visible_source" else value
                self.permissions[row["tenant_id"], row["resource_type"], row["resource_id"]] += 1
            elif tag == "fga_tuple":
                if section != "fga" or tenant_id is not None:
                    blocked("fga_scope")
                self.fga.add(value["object"])
                self.fga.add(value["user"].split("#", 1)[0])

    def finish(self):
        counts = Counter((v["tenant_id"], v["knowledge_id"]) for v in self.files.values())
        explained_creators = set()
        for key, proof in self.proofs[CREATOR_RETENTION].items():
            resource = self.resources.get(key)
            if resource is None:
                blocked("creator_resource_missing")
            creator = self.creators.get((key[0], resource["user_id"]))
            if (
                creator is None
                or creator_retention(resource=resource, creator=creator, managed_file_count=counts[key]).data != proof
            ):
                blocked("creator_proof_changed")
            explained_creators.add((key[0], resource["user_id"]))
        missing_creators = {key for key, value in self.creators.items() if value["exists"] is False}
        invalid_assistants = {
            key
            for key, root in self.source_roots.items()
            if retained_invalid_assistant_creator(root, self.source_headers.get(key))
        }
        explained_creators.update(
            (key.tenant_id, self.source_roots[key].creator_id)
            for key in invalid_assistants
            if (key.tenant_id, self.source_roots[key].creator_id) in missing_creators
        )
        if missing_creators != explained_creators:
            blocked("unexplained_missing_creator")
        for source, creator in self.sources:
            if (
                (source.tenant_id, creator) in missing_creators
                and source not in invalid_assistants
                and (
                    source.source_type.value != "knowledge"
                    or not source.source_id.isdecimal()
                    or (source.tenant_id, int(source.source_id)) not in self.proofs[CREATOR_RETENTION]
                    or self.proofs[CREATOR_RETENTION][source.tenant_id, int(source.source_id)]["creator_user_id"]
                    != creator
                )
            ):
                blocked("missing_creator_borrowed_by_other_source")
        if self.file_reference_targets & {key[1] for key in self.proofs[FILE_RETENTION]}:
            blocked("stranded_file_has_saved_reference")
        all_ids = {v["id"] for v in self.files.values()}
        for key, proof in self.proofs[FILE_RETENTION].items():
            file = self.files.get(key)
            resource = self.resources.get((key[0], proof["space_id"]))
            if file is None or resource is None or proof["missing_parent_id"] in all_ids:
                blocked("file_or_absent_parent_changed")
            obj = "knowledge_file:" + str(key[1])
            wanted = stranded_retention(
                resource=resource,
                file=file,
                ancestor=absent_parent(proof["missing_parent_id"]),
                sql_permission_count=self.permissions[key[0], "knowledge_file", str(key[1])],
                fga_tuple_count=int(obj in self.fga),
            )
            if wanted.data != proof:
                blocked("file_proof_changed")
        # Reject removing the sole explanation for an invalid original path.
        for key, file in self.files.items():
            path = _path(file["file_level_path"])
            invalid = file["id"] in path or (file["level"] is not None and file["level"] != len(path))
            for index, parent in enumerate(path):
                row = self.files.get((key[0], parent))
                invalid |= row is None or row["knowledge_id"] != file["knowledge_id"] or row["file_type"] != 0
                if row is not None:
                    actual = _path(row["file_level_path"])
                    invalid |= actual != path[:index] or (row["level"] is not None and row["level"] != index)
            if invalid and key not in self.proofs[FILE_RETENTION]:
                blocked("unexplained_file_structure")


async def validate_native_retentions(session, proofs, *, resources, controls, permissions):
    """Reacquire native facts before any tenant business write, including resume."""
    from dataclasses import asdict

    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.knowledge.application.unification_inventory_codec import record_from_row

    tenant = get_current_tenant_id()
    if any(proof["tenant_id"] != tenant for proof in proofs):
        blocked("live_tenant_changed")
    resource_ids = tuple(sorted({p["space_id"] for p in proofs}))
    file_ids = tuple(sorted({p["file_id"] for p in proofs if "file_id" in p}))
    roots, files = {}, {}
    for offset in range(0, len(resource_ids), 199):
        rows, _ = await resources.aload_retention_rows(session, resource_ids=resource_ids[offset : offset + 199])
        roots.update((r.id, record_from_row(r).data) for r in rows)
    for offset in range(0, len(file_ids), 199):
        _, rows = await resources.aload_retention_rows(session, file_ids=file_ids[offset : offset + 199])
        files.update((r.id, record_from_row(r).data) for r in rows)
    creator_proofs = tuple(p for p in proofs if "creator_user_id" in p)
    ids = tuple(sorted({p["creator_user_id"] for p in creator_proofs}))
    creators, counts = {}, {}
    for offset in range(0, len(ids), 199):
        creators.update(
            (r.user_id, record_from_row(r).data)
            for r in await controls.ainspect_users(session, user_ids=ids[offset : offset + 199])
        )
    ids = tuple(sorted({p["space_id"] for p in creator_proofs}))
    for offset in range(0, len(ids), 199):
        counts.update(await resources.acount_resource_files(session, resource_ids=ids[offset : offset + 199]))
    parents = tuple(sorted({p["missing_parent_id"] for p in proofs if "file_id" in p}))
    ancestors = {}
    for offset in range(0, len(parents), 199):
        ancestors.update(
            (r.id, asdict(r))
            for r in await resources.ainspect_file_ancestors(session, file_ids=parents[offset : offset + 199])
        )
    auth = {}
    for offset in range(0, len(file_ids), 199):
        batch = file_ids[offset : offset + 199]
        auth.update(await permissions.acount_file_authorization_rows(session, file_ids=batch))
    for proof in proofs:
        root = roots[proof["space_id"]]
        if "creator_user_id" in proof:
            actual = creator_retention(
                resource=root, creator=creators[proof["creator_user_id"]], managed_file_count=counts[proof["space_id"]]
            )
        else:
            actual = stranded_retention(
                resource=root,
                file=files[proof["file_id"]],
                ancestor=ancestors[proof["missing_parent_id"]],
                sql_permission_count=auth[proof["file_id"]],
                fga_tuple_count=0,
            )
        if actual.data != proof:
            blocked("live_proof_changed")
