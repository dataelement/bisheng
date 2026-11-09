"""Native outer move classification and synchronous same-space row finalization."""

from dataclasses import dataclass

from sqlalchemy import or_, select, update

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Document
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.knowledge.domain.repositories.move_row_repository import PAGE, MoveRowRepository
from bisheng.knowledge.domain.repositories.operation_plan_repository import _now
from bisheng.knowledge.domain.schemas.move_processing import (
    DOC_FIELDS,
    FILE_FIELDS,
    ROOT_FIELDS,
    VERSION_FIELDS,
    MoveRoot,
    move_path_ids,
)


def conflict(reason):
    raise KnowledgeOperationPlanConflictError(reason="move_batch_" + reason)


@dataclass(frozen=True, slots=True)
class MoveBatch:
    source: dict
    destination: dict
    destination_folder_id: int | None
    destination_path: tuple[int, ...]
    roots: tuple[MoveRoot, ...]
    files: tuple[dict, ...]
    documents: tuple[dict, ...]
    versions: tuple[dict, ...]
    owners: dict[int, tuple[MoveRoot, ...]]
    issues: dict[MoveRoot, str]


class MoveBatchRepository(MoveRowRepository):
    def __init__(self, *, max_folder_level, clock=_now):
        self.max_folder_level, self.clock = max_folder_level, clock

    async def aread(self, session, *, source_space_id, destination_space_id, roots, destination_folder_id, lock=False):
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or not roots:
            conflict("concrete_selection_required")
        with session.no_autoflush, strict_tenant_filter():
            query = (
                select(*(getattr(Knowledge, name) for name in ROOT_FIELDS))
                .where(Knowledge.id.in_(sorted({source_space_id, destination_space_id})))
                .order_by(Knowledge.id)
            )
            result = (await session.execute(query.with_for_update() if lock else query)).mappings().all()
        spaces = {row["id"]: dict(row) for row in result}
        if set(spaces) != {source_space_id, destination_space_id} or any(
            row["tenant_id"] != tenant or row["type"] != 3 for row in result
        ):
            conflict("space_missing")
        if any(row["state"] in (2, 3) or row["model_transition"] for row in result):
            conflict("space_processing")
        source, destination = spaces[source_space_id], spaces[destination_space_id]
        selected = {
            row["id"]: row for row in await self._by_ids(session, File, FILE_FIELDS, [root.id for root in roots])
        }
        issues = {}
        for root in roots:
            row = selected.get(root.id)
            if row is None or row["knowledge_id"] != source_space_id:
                issues[root] = "not_found"
            elif row["file_type"] != (0 if root.type == "folder" else 1):
                issues[root] = "unsupported"
        folders = {root.id for root in roots if root.type == "folder" and root not in issues}
        roots = tuple(
            dict.fromkeys(
                root
                for root in roots
                if root in issues or not folders.intersection(move_path_ids(selected[root.id]["file_level_path"]))
            )
        )
        folders = {root.id for root in roots if root.type == "folder" and root not in issues}
        physical = {root.id: selected[root.id] for root in roots if root not in issues}
        prefixes = [
            "/" + "/".join(map(str, (*move_path_ids(selected[key]["file_level_path"]), key))) for key in folders
        ]
        path_documents = {}
        for offset in range(0, len(prefixes), PAGE):
            conditions = or_(
                *(
                    or_(File.file_level_path == prefix, File.file_level_path.startswith(prefix + "/", autoescape=True))
                    for prefix in prefixes[offset : offset + PAGE]
                )
            )
            rows = await self._rows(session, File, FILE_FIELDS, (File.knowledge_id == source_space_id) & conditions)
            physical.update({row["id"]: row for row in rows})
            doc_conditions = or_(
                *(
                    or_(
                        Document.file_level_path == prefix,
                        Document.file_level_path.startswith(prefix + "/", autoescape=True),
                    )
                    for prefix in prefixes[offset : offset + PAGE]
                )
            )
            rows = await self._rows(
                session, Document, DOC_FIELDS, (Document.knowledge_id == source_space_id) & doc_conditions
            )
            path_documents.update({row["id"]: row for row in rows})
        versions = {
            row["id"]: row
            for row in await self._by_ids(session, Version, VERSION_FIELDS, physical, key="knowledge_file_id")
        }
        documents = {
            row["id"]: row
            for row in await self._by_ids(
                session, Document, DOC_FIELDS, {row["document_id"] for row in versions.values()}
            )
        }
        documents = {**path_documents, **documents}
        versions.update(
            {
                row["id"]: row
                for row in await self._by_ids(session, Version, VERSION_FIELDS, documents, key="document_id")
            }
        )
        physical.update(
            {
                row["id"]: row
                for row in await self._by_ids(
                    session,
                    File,
                    FILE_FIELDS,
                    {row["knowledge_file_id"] for row in versions.values()} - physical.keys(),
                )
            }
        )
        target = await self._by_ids(
            session, File, FILE_FIELDS, [destination_folder_id] if destination_folder_id else []
        )
        if destination_folder_id and (
            len(target) != 1 or target[0]["knowledge_id"] != destination_space_id or target[0]["file_type"] != 0
        ):
            conflict("destination_missing")
        path = (*move_path_ids(target[0]["file_level_path"]), destination_folder_id) if target else ()
        parents = {key for row in physical.values() for key in move_path_ids(row["file_level_path"])}
        ancestors = {row["id"]: row for row in await self._by_ids(session, File, FILE_FIELDS, parents | set(path))}
        for keys, space in ((parents, source_space_id), (path, destination_space_id)):
            for key in keys:
                row = ancestors.get(key)
                if row is None or row["file_type"] != 0 or row["knowledge_id"] != space or row["tenant_id"] != tenant:
                    conflict("parent_chain_invalid")
                ancestor_path = move_path_ids(row["file_level_path"])
                if any(
                    parent not in ancestors
                    or move_path_ids(ancestors[parent]["file_level_path"]) != ancestor_path[:index]
                    for index, parent in enumerate(ancestor_path)
                ):
                    conflict("parent_path_invalid")
        root_map = {root.id: root for root in roots if root not in issues}
        owners, docs_roots = {}, {}
        by_file = {row["knowledge_file_id"]: row for row in versions.values()}
        if len(by_file) != len(versions):
            conflict("version_alias")
        for key, row in physical.items():
            owner = root_map.get(key) or next(
                (root_map[parent] for parent in move_path_ids(row["file_level_path"]) if parent in folders), None
            )
            if owner:
                owners[key] = (owner,)
                if key in by_file:
                    docs_roots.setdefault(by_file[key]["document_id"], set()).add(owner)
        for doc in documents.values():
            owner = next((root_map[key] for key in move_path_ids(doc["file_level_path"]) if key in folders), None)
            if owner:
                docs_roots.setdefault(doc["id"], set()).add(owner)
        document_owners = {
            key: tuple(sorted(values, key=lambda root: (root.type, root.id))) for key, values in docs_roots.items()
        }
        for version in versions.values():
            if version["knowledge_file_id"] not in physical or version["document_id"] not in documents:
                conflict("version_chain_missing")
            owners[version["knowledge_file_id"]] = document_owners.get(version["document_id"], ())
        for root in roots:
            if root in issues:
                continue
            row = selected[root.id]
            old_path = move_path_ids(row["file_level_path"])
            if source_space_id == destination_space_id:
                if root.type == "folder" and root.id in path:
                    issues[root] = "into_self" if destination_folder_id == root.id else "into_subtree"
                elif old_path == path:
                    issues[root] = "into_current_parent"
        blocked_groups = set()
        for row in physical.values():
            if row["knowledge_id"] != source_space_id or row["tenant_id"] != tenant or row["file_type"] not in (0, 1):
                conflict("physical_chain_invalid")
            group = owners.get(row["id"], ())
            reason = None
            if row["file_type"] == 1 and row["id"] not in by_file:
                reason = "unsupported"
            elif row["file_type"] == 1 and row["status"] in (1, 4, 5):
                reason = "processing"
            elif (
                row["file_type"] == 0
                and group
                and len(path) + row["level"] - selected[group[0].id]["level"] > self.max_folder_level
            ):
                reason = "depth_exceeded"
            if reason and id(group) not in blocked_groups:
                blocked_groups.add(id(group))
                for root in group:
                    issues[root] = reason
        primary_versions = {}
        for version in versions.values():
            if version["is_primary"]:
                if version["document_id"] in primary_versions:
                    conflict("primary_duplicate")
                primary_versions[version["document_id"]] = version["id"]
        for doc in documents.values():
            primary = versions.get(doc["primary_version_id"])
            primary_file = physical.get(primary["knowledge_file_id"]) if primary else None
            if (
                not primary
                or primary_versions.get(doc["id"]) != primary["id"]
                or primary["document_id"] != doc["id"]
                or doc["knowledge_id"] != source_space_id
                or not primary_file
                or move_path_ids(primary_file["file_level_path"]) != move_path_ids(doc["file_level_path"])
                or primary_file["level"] != doc["level"]
            ):
                conflict("primary_invalid")
        destination_folders = await self._rows(
            session,
            File,
            FILE_FIELDS,
            (File.knowledge_id == destination_space_id)
            & (File.file_type == 0)
            & (
                File.file_level_path == "/".join(("", *map(str, path)))
                if path
                else or_(File.file_level_path.is_(None), File.file_level_path == "")
            ),
        )
        names = {row["file_name"] for row in destination_folders}
        incoming = {}
        for root in roots:
            if root not in issues and root.type == "folder":
                incoming.setdefault(selected[root.id]["file_name"], []).append(root)
        for name, group in incoming.items():
            if name in names or len(group) > 1:
                for root in group:
                    issues[root] = "name_conflict"
        return MoveBatch(
            source,
            destination,
            destination_folder_id,
            path,
            roots,
            tuple(physical.values()),
            tuple(documents.values()),
            tuple(versions.values()),
            owners,
            issues,
        )

    @staticmethod
    def classify(batch, denied):
        reasons = {**batch.issues, **dict.fromkeys(denied, "no_permission")}
        # Shared document chains are indivisible. Propagate a failure through
        # actual overlap edges, with no selected-root x physical-row scan.
        adjacent = {root: set() for root in batch.roots}
        seen = set()
        for roots in batch.owners.values():
            if id(roots) in seen:
                continue
            seen.add(id(roots))
            if roots:
                for root in roots[1:]:
                    adjacent[roots[0]].add(root)
                    adjacent[root].add(roots[0])
        pending = list(reasons)
        while pending:
            root = pending.pop()
            for other in adjacent[root]:
                if other not in reasons:
                    reasons[other] = "related_invalid"
                    pending.append(other)
        return tuple(root for root in batch.roots if root not in reasons), reasons

    async def same_parameters(self, session, batch, roots, projection):
        selected = set(roots)
        owners = {}
        for group in batch.owners.values():
            if id(group) not in owners:
                owners[id(group)] = next((root for root in group if root in selected), None)
        files = {row["id"]: row for row in batch.files if owners.get(id(batch.owners.get(row["id"], ()))) is not None}
        initial = {root.id: files[root.id] for root in roots}
        after, proposed = {}, []
        documents = {row["id"]: row for row in batch.documents}
        versions = {row["id"]: row for row in batch.versions}
        versions_by_document = {}
        for version in versions.values():
            versions_by_document.setdefault(version["document_id"], []).append(version)
        for key, row in files.items():
            root = owners[id(batch.owners[key])]
            own = initial[root.id]
            if root.type == "folder" and key != root.id:
                old = (*move_path_ids(own["file_level_path"]), root.id)
                suffix = move_path_ids(row["file_level_path"])[len(old) :]
                path = (*batch.destination_path, root.id, *suffix)
            else:
                path = batch.destination_path
            after[key] = {**row, "file_level_path": "/" + "/".join(map(str, path)) if path else "", "level": len(path)}
        # Historical versions follow the actual primary document location.
        for doc in documents.values():
            primary = versions[doc["primary_version_id"]]["knowledge_file_id"]
            if primary in after:
                for version in versions_by_document[doc["id"]]:
                    if version["knowledge_file_id"] in after:
                        current = after[version["knowledge_file_id"]]
                        current["file_level_path"], current["level"] = (
                            after[primary]["file_level_path"],
                            after[primary]["level"],
                        )
        for key, row in files.items():
            old = move_path_ids(row["file_level_path"])
            path = move_path_ids(after[key]["file_level_path"])
            before_ref = ("folder", old[-1]) if old else ("knowledge_space", batch.source["id"])
            after_ref = ("folder", path[-1]) if path else ("knowledge_space", batch.source["id"])
            if before_ref != after_ref:
                proposed.append(("folder" if row["file_type"] == 0 else "knowledge_file", key, before_ref, after_ref))
        changes = []
        for offset in range(0, len(proposed), PAGE):
            page = proposed[offset : offset + PAGE]
            states = await projection.aread_parent_states(
                session, targets=tuple((kind, str(key)) for kind, key, _, _ in page)
            )
            states = {(row.resource_type, row.resource_id): row for row in states}
            for kind, key, before_ref, after_ref in page:
                state = states.get((kind, str(key)))
                if (
                    state is None
                    or state.projection_state != "CURRENT"
                    or (state.parent_type, str(state.parent_id)) != (before_ref[0], str(before_ref[1]))
                ):
                    conflict("permission_changed")
                changes.append(
                    {
                        "resource_type": kind,
                        "resource_id": key,
                        "old_parent_type": before_ref[0],
                        "old_parent_id": before_ref[1],
                        "new_parent_type": after_ref[0],
                        "new_parent_id": after_ref[1],
                        "mode": state.mode,
                        "expected_permission_version": state.version,
                    }
                )
        docs = []
        for doc in documents.values():
            primary = versions[doc["primary_version_id"]]["knowledge_file_id"]
            if primary in after:
                docs.append(
                    {
                        "before": doc,
                        "after": {
                            **doc,
                            "file_level_path": after[primary]["file_level_path"],
                            "level": after[primary]["level"],
                        },
                    }
                )
        return {
            "same_space_move": 1,
            "source": batch.source,
            "destination_folder_id": batch.destination_folder_id,
            "destination_path": list(batch.destination_path),
            "roots": [{"id": root.id, "type": root.type} for root in roots],
            "files": [{"before": row, "after": after[key]} for key, row in sorted(files.items())],
            "documents": docs,
            "versions": [row for row in versions.values() if row["knowledge_file_id"] in files],
            "parent_changes": changes,
        }

    async def same_phase(self, session, parameters, *, lock=False):
        source = parameters["source"]
        with session.no_autoflush, strict_tenant_filter():
            query = select(*(getattr(Knowledge, name) for name in ROOT_FIELDS)).where(Knowledge.id == source["id"])
            row = (await session.execute(query.with_for_update() if lock else query)).mappings().one_or_none()
        if row is None or dict(row) != source or source["tenant_id"] != get_current_tenant_id():
            conflict("space_changed")
        batch = await self.aread(
            session,
            source_space_id=source["id"],
            destination_space_id=source["id"],
            roots=tuple(MoveRoot(row["type"], row["id"]) for row in parameters["roots"]),
            destination_folder_id=parameters["destination_folder_id"],
            lock=False,
        )
        if {row["id"] for row in batch.files} != {row["before"]["id"] for row in parameters["files"]} or list(
            batch.destination_path
        ) != parameters["destination_path"]:
            conflict("closure_changed")
        phases = set()
        for model, fields, key in ((File, FILE_FIELDS, "files"), (Document, DOC_FIELDS, "documents")):
            expected = parameters[key]
            actual = {
                row["id"]: row
                for row in await self._by_ids(
                    session, model, fields, [value["before"]["id"] for value in expected], lock=lock
                )
            }
            for value in expected:
                current = actual.get(value["before"]["id"])
                if current == value["before"] and current == value["after"]:
                    continue
                if current == value["before"]:
                    phases.add("before")
                elif current == value["after"]:
                    phases.add("after")
                else:
                    conflict("rows_changed")
        versions = await self._by_ids(
            session, Version, VERSION_FIELDS, [row["id"] for row in parameters["versions"]], lock=lock
        )
        if sorted(versions, key=lambda row: row["id"]) != sorted(parameters["versions"], key=lambda row: row["id"]):
            conflict("versions_changed")
        if len(phases) > 1:
            conflict("mixed_sql_phase")
        return next(iter(phases), "after")

    async def afinalize_same(self, session, parameters):
        tenant = get_current_tenant_id()
        for model, key in ((File, "files"), (Document, "documents")):
            for value in parameters[key]:
                table = model.__table__
                before, after = value["before"], value["after"]
                changes = {name: after[name] for name in ("file_level_path", "level")}
                where = [table.c.id == before["id"], table.c.knowledge_id == parameters["source"]["id"]]
                if model is File:
                    where.append(table.c.tenant_id == tenant)
                else:
                    where.append(
                        select(Knowledge.id)
                        .where(Knowledge.id == table.c.knowledge_id, Knowledge.tenant_id == tenant)
                        .exists()
                    )
                result = await session.execute(update(table).where(*where).values(**changes))
                if result.rowcount != 1:
                    conflict("row_disappeared")
        await touch_move_spaces(session, parameters["source"]["id"], parameters["source"]["id"], self.clock())
        await session.flush()


async def touch_move_spaces(session, source_id, destination_id, now):
    tenant = get_current_tenant_id()
    ids = sorted({source_id, destination_id})
    result = await session.execute(
        update(Knowledge.__table__)
        .where(
            Knowledge.id.in_(ids),
            Knowledge.tenant_id == tenant,
            Knowledge.type == 3,
        )
        .values(update_time=now)
    )
    if result.rowcount != len(ids):
        conflict("space_changed")
