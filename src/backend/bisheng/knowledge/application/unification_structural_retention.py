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
ROOTLESS_FILE_RETENTION = "rootless_file_retention"
HISTORICAL_CREATOR_RETENTION = "historical_resource_creator_retention"
DELETE_RETENTION = "retained_permission_delete"
RETENTIONS = frozenset(
    {CREATOR_RETENTION, FILE_RETENTION, ROOTLESS_FILE_RETENTION, HISTORICAL_CREATOR_RETENTION, DELETE_RETENTION}
)


def historical_creator_retention(*, resource, creator, managed_file_count):
    if (
        resource["type"] not in {0, 1, 2, 3}
        or type(resource["user_id"]) is not int
        or resource["user_id"] <= 0
        or type(managed_file_count) is not int
        or managed_file_count < 0
        or creator != {"user_id": resource["user_id"], "exists": False, "delete": None}
    ):
        blocked("historical_creator_identity_invalid")
    return record_from_values(
        HISTORICAL_CREATOR_RETENTION,
        tenant_id=resource["tenant_id"],
        space_id=resource["id"],
        creator_user_id=resource["user_id"],
        original_type=resource["type"],
        managed_file_count=managed_file_count,
        resource_digest=digest(resource),
        reason="preserve_original_missing_creator_without_new_membership",
    )


def rootless_file_retention(file):
    if file["file_type"] != 1 or file["file_level_path"] not in (None, ""):
        blocked("unknown_rootless_file_shape")
    return record_from_values(
        ROOTLESS_FILE_RETENTION,
        tenant_id=file["tenant_id"],
        space_id=file["knowledge_id"],
        file_id=file["id"],
        file_digest=file["row_digest"],
        reason="preserve_original_file_with_absent_knowledge_parent",
    )


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
        self.rootless_files = {}
        self.proofs = {tag: {} for tag in RETENTIONS - {DELETE_RETENTION}}
        self.delete_proofs, self.mode_identities, self.marker_policy = {}, {}, {}
        self.enabled_objects, self.store_id = set(), None
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
        if tag == DELETE_RETENTION:
            if (kind, section) != ("plan", "control") or value["tenant_id"] != tenant_id:
                blocked("delete_proof_scope")
            key = tenant_id, value["resource_type"], value["resource_id"]
            if key in self.delete_proofs:
                blocked("duplicate_delete_proof")
            self.delete_proofs[key] = value
        elif tag == "permission_plan":
            if (kind, section) != ("plan", "conversion") or value["tenant_id"] != tenant_id:
                blocked("delete_marker_plan_scope")
            self.marker_policy[tenant_id, value["resource_type"], value["resource_id"]] = value.get(
                "restore_missing_markers"
            )
        elif tag in RETENTIONS:
            if (kind, section) != ("plan", "control") or value["tenant_id"] != tenant_id:
                blocked("proof_scope")
            ident = value["space_id"] if tag in {CREATOR_RETENTION, HISTORICAL_CREATOR_RETENTION} else value["file_id"]
            key = tenant_id, ident
            if key in self.proofs[tag]:
                blocked("duplicate_proof")
            self.proofs[tag][key] = value
        elif kind == "baseline":
            if tag == "rootless_file":
                if section != "control" or value["tenant_id"] != tenant_id:
                    blocked("rootless_file_scope")
                key = tenant_id, value["id"]
                if key in self.rootless_files:
                    blocked("duplicate_rootless_file")
                self.rootless_files[key] = value
            elif tag in {"resource", "file"}:
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
                if tag == "resource_mode":
                    self.mode_identities[row["tenant_id"], row["resource_type"], row["resource_id"]] = (
                        row["operation_id"],
                        row["version"],
                        row["projection_state"],
                    )
            elif tag == "authorization":
                self.store_id = value["store_id"]
            elif tag == "fga_tuple":
                if section != "fga" or tenant_id is not None:
                    blocked("fga_scope")
                self.fga.add(value["object"])
                self.fga.add(value["user"].split("#", 1)[0])
                if value["relation"] == "permission_enabled":
                    self.enabled_objects.add(value["object"])

    def finish(self):
        from bisheng.knowledge.domain.repositories.unification_delete_retention_repository import KINDS, REASON

        for key, proof in self.delete_proofs.items():
            tenant, resource_type, ident = key
            if resource_type not in KINDS or not ident.isdecimal() or str(int(ident)) != ident:
                blocked("delete_identity")
            physical_key = tenant, int(ident)
            row = (
                self.resources.get(physical_key)
                if resource_type in {"knowledge_library", "knowledge_space"}
                else self.files.get(physical_key)
            )
            if (
                row is None
                or (
                    resource_type in {"folder", "knowledge_file"}
                    and row["file_type"] != int(resource_type == "knowledge_file")
                )
                or proof["reason"] != REASON
                or proof["store_id"] != self.store_id
                or self.mode_identities.get(key) != (proof["operation_id"], proof["target_version"], "CURRENT")
                or self.marker_policy.get(key) is not False
                or f"{resource_type}:{ident}" in self.enabled_objects
            ):
                blocked("delete_not_closed")
        rootless_proofs = self.proofs[ROOTLESS_FILE_RETENTION]
        if set(rootless_proofs) != set(self.rootless_files):
            blocked("rootless_file_proof_set")
        existing_roots = {row["id"] for row in self.resources.values()}
        authorized_file_ids = {
            ident
            for (_, kind, ident), count in self.permissions.items()
            if count and kind in {"folder", "knowledge_file"}
        }
        for key, file in self.rootless_files.items():
            if (
                key in self.files
                or file["knowledge_id"] in existing_roots
                or rootless_file_retention(file).data != rootless_proofs[key]
                or self.permissions[key[0], "knowledge_file", str(key[1])]
                or str(key[1]) in authorized_file_ids
                or f"knowledge_file:{key[1]}" in self.fga
                or f"folder:{key[1]}" in self.fga
                or key[1] in self.file_reference_targets
            ):
                blocked("rootless_file_not_isolated")
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
        for key, proof in self.proofs[HISTORICAL_CREATOR_RETENTION].items():
            resource = self.resources.get(key)
            creator = self.creators.get((key[0], proof["creator_user_id"]))
            if (
                resource is None
                or historical_creator_retention(resource=resource, creator=creator, managed_file_count=counts[key]).data
                != proof
            ):
                blocked("historical_creator_proof_changed")
            explained_creators.add((key[0], proof["creator_user_id"]))
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
        if self.proofs[CREATOR_RETENTION].keys() & self.proofs[HISTORICAL_CREATOR_RETENTION].keys():
            blocked("duplicate_creator_explanation")
        creator_proofs = self.proofs[CREATOR_RETENTION] | self.proofs[HISTORICAL_CREATOR_RETENTION]
        for source, creator in self.sources:
            if (
                (source.tenant_id, creator) in missing_creators
                and source not in invalid_assistants
                and (
                    source.source_type.value != "knowledge"
                    or not source.source_id.isdecimal()
                    or (source.tenant_id, int(source.source_id)) not in creator_proofs
                    or creator_proofs[source.tenant_id, int(source.source_id)]["creator_user_id"] != creator
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
    from bisheng.knowledge.domain.repositories.unification_delete_retention_repository import REASON, validate_facts

    deleted = tuple(p for p in proofs if p.get("reason") == REASON)
    if deleted:
        await validate_facts(session, deleted)
    proofs = tuple(p for p in proofs if p.get("reason") != REASON)
    historical = tuple(
        p for p in proofs if p.get("reason") == "preserve_original_missing_creator_without_new_membership"
    )
    for offset in range(0, len(historical), 199):
        batch = historical[offset : offset + 199]
        rows, _ = await resources.aload_retention_rows(session, resource_ids=tuple(p["space_id"] for p in batch))
        roots = {r.id: r for r in rows}
        counts = await resources.acount_resource_files(session, resource_ids=tuple(roots))
        creators = {
            r.user_id: r
            for r in await controls.ainspect_users(
                session, user_ids=tuple(sorted({p["creator_user_id"] for p in batch}))
            )
        }
        for proof in batch:
            root, creator = roots.get(proof["space_id"]), creators.get(proof["creator_user_id"])
            if (
                root is None
                or root.user_id != proof["creator_user_id"]
                or root.type not in ({0, 3} if proof["original_type"] == 0 else {proof["original_type"]})
                or creator is None
                or creator.exists is not False
                or counts.get(proof["space_id"]) != proof["managed_file_count"]
            ):
                blocked("historical_creator_live_identity_changed")
    proofs = tuple(p for p in proofs if p.get("reason") != "preserve_original_missing_creator_without_new_membership")
    rootless = tuple(p for p in proofs if p.get("reason") == "preserve_original_file_with_absent_knowledge_parent")
    for offset in range(0, len(rootless), 199):
        batch = rootless[offset : offset + 199]
        file_ids = tuple(sorted(p["file_id"] for p in batch))
        _, rows = await resources.aload_retention_rows(session, file_ids=file_ids)
        by_id = {r.id: record_from_row(r).data for r in rows}
        parents = tuple(sorted({p["space_id"] for p in batch}))
        if await resources.ainspect_existing_knowledge_ids(session, knowledge_ids=parents):
            blocked("rootless_parent_reappeared")
        occupied = await permissions.ainspect_rootless_file_authorization(session, file_ids=file_ids)
        for proof in batch:
            if (
                proof["file_id"] not in by_id
                or proof["file_id"] in occupied
                or rootless_file_retention(by_id[proof["file_id"]]).data != proof
            ):
                blocked("rootless_live_proof_changed")
    proofs = tuple(p for p in proofs if p.get("reason") != "preserve_original_file_with_absent_knowledge_parent")
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
