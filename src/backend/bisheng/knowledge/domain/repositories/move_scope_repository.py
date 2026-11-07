"""Native move manifests. The caller owns authorization, session and commit."""

from copy import deepcopy
from dataclasses import asdict

from sqlalchemy import and_, func, inspect, or_
from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    KnowledgeProcessingConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.repositories.move_row_repository import PAGE, MoveRowRepository
from bisheng.knowledge.domain.repositories.operation_plan_repository import _digest
from bisheng.knowledge.domain.schemas.move_processing import (
    DOC_FIELDS,
    FILE_FIELDS,
    ROOT_FIELDS,
    VERSION_FIELDS,
    MoveLeaf,
    MoveParentChange,
    MoveRoot,
    MoveRow,
    MoveScope,
    metadata_schema_fields,
    move_path_ids,
    move_scope_parameters,
)
from bisheng.knowledge.domain.schemas.processing_job import ResourceVersionTarget
from bisheng.knowledge.domain.services.move_metadata_policy import effective_move_removed_fields


def conflict(reason):
    raise KnowledgeOperationPlanConflictError(reason=reason)


def checked(parser, value):
    try:
        return parser(value)
    except ValueError as error:
        raise KnowledgeOperationPlanConflictError(reason="move_snapshot_invalid") from error


def path_ids(path):
    return checked(move_path_ids, path)


def revision(row):
    return _digest({key: value for key, value in row.items() if key != "status"})


class MoveScopeRepository(MoveRowRepository):
    def __init__(self, *, parent_states=None):
        self.parent_states = parent_states

    @staticmethod
    def _context(session, *space_ids):
        if not isinstance(session, (Session, AsyncSession)):
            raise TypeError("move requires the caller native session")
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
            raise ResourceReferenceInvalidError(reason="move_concrete_tenant_required")
        if any(type(key) is not int or key <= 0 for key in space_ids):
            raise SpaceNotFoundError()
        return tenant

    async def _roots(self, session, source, destination, *, lock=False):
        tenant = self._context(session, source, destination)
        if source == destination:
            conflict("move_cross_space_required")
        with session.no_autoflush, strict_tenant_filter():
            query = (
                select(*(getattr(Knowledge, name) for name in ROOT_FIELDS))
                .where(Knowledge.id.in_(sorted((source, destination))))
                .order_by(Knowledge.id)
            )
            rows = (await session.execute(query.with_for_update() if lock else query)).mappings().all()
        roots = {row["id"]: deepcopy(dict(row)) for row in rows}
        if len(roots) != 2 or any(row["tenant_id"] != tenant or row["type"] != 3 for row in rows):
            raise SpaceNotFoundError()
        if any(row["state"] in (2, 3) or row["model_transition"] for row in rows):
            raise KnowledgeProcessingConflictError(reason="move_space_processing")
        return roots[source], roots[destination]

    async def aload_scope(
        self, session, *, source_space_id, destination_space_id, roots, destination_folder_id, for_update=False
    ):
        if type(for_update) is not bool or not roots or not all(isinstance(root, MoveRoot) for root in roots):
            raise ValueError("explicit move roots and lock mode required")
        source, destination = await self._roots(session, source_space_id, destination_space_id, lock=for_update)
        tenant = source["tenant_id"]
        await self._pending_jobs(session, (source_space_id, destination_space_id))
        with session.no_autoflush, strict_tenant_filter():
            active = (
                select(KnowledgeProcessingJob.id)
                .where(
                    KnowledgeProcessingJob.space_id.in_((source_space_id, destination_space_id)),
                    KnowledgeProcessingJob.state.in_(("accepted", "running")),
                    KnowledgeProcessingJob.kind.in_(("embedding_rebuild", "metadata_schema_change", "space_copy")),
                )
                .limit(1)
            )
            if (await session.execute(active.with_for_update() if for_update else active)).first():
                raise KnowledgeProcessingConflictError(reason="move_processing_conflict")
        selected = await self._by_ids(session, KnowledgeFile, FILE_FIELDS, [root.id for root in roots])
        selected_map = {row["id"]: row for row in selected}
        if len(selected_map) != len({root.id for root in roots}):
            conflict("move_root_missing")
        for root in roots:
            row = selected_map[root.id]
            if (
                row["knowledge_id"] != source_space_id
                or row["tenant_id"] != tenant
                or row["file_type"] != (0 if root.type == "folder" else 1)
            ):
                conflict("move_root_invalid")
        folder_ids = {root.id for root in roots if root.type == "folder"}
        roots = tuple(
            sorted(
                {
                    root
                    for root in roots
                    if not folder_ids.intersection(path_ids(selected_map[root.id]["file_level_path"]))
                },
                key=lambda root: (root.type, root.id),
            )
        )
        folders = {root.id: root for root in roots if root.type == "folder"}
        physical = {root.id: selected_map[root.id] for root in roots}
        prefixes = ["/" + "/".join(map(str, (*path_ids(selected_map[key]["file_level_path"]), key))) for key in folders]
        docs = {}
        for offset in range(0, len(prefixes), PAGE):

            def conditions(column, page=prefixes[offset : offset + PAGE]):
                return or_(
                    *(or_(column == prefix, column.startswith(prefix + "/", autoescape=True)) for prefix in page)
                )

            for row in await self._rows(
                session,
                KnowledgeFile,
                FILE_FIELDS,
                and_(
                    KnowledgeFile.__table__.c.knowledge_id == source_space_id,
                    conditions(KnowledgeFile.__table__.c.file_level_path),
                ),
            ):
                physical[row["id"]] = row
            for row in await self._rows(
                session,
                KnowledgeDocument,
                DOC_FIELDS,
                and_(
                    KnowledgeDocument.__table__.c.knowledge_id == source_space_id,
                    conditions(KnowledgeDocument.__table__.c.file_level_path),
                ),
            ):
                docs[row["id"]] = row
        versions = {
            row["id"]: row
            for row in await self._by_ids(
                session, KnowledgeDocumentVersion, VERSION_FIELDS, physical, key="knowledge_file_id"
            )
        }
        docs.update(
            {
                row["id"]: row
                for row in await self._by_ids(
                    session, KnowledgeDocument, DOC_FIELDS, {row["document_id"] for row in versions.values()}
                )
            }
        )
        versions.update(
            {
                row["id"]: row
                for row in await self._by_ids(
                    session, KnowledgeDocumentVersion, VERSION_FIELDS, docs, key="document_id"
                )
            }
        )
        physical.update(
            {
                row["id"]: row
                for row in await self._by_ids(
                    session,
                    KnowledgeFile,
                    FILE_FIELDS,
                    {row["knowledge_file_id"] for row in versions.values()} - physical.keys(),
                )
            }
        )
        by_file, primaries = {}, {}
        for version in versions.values():
            file_id, doc_id = version["knowledge_file_id"], version["document_id"]
            if (
                file_id in by_file
                or file_id not in physical
                or physical[file_id]["file_type"] != 1
                or doc_id not in docs
            ):
                conflict("move_version_chain_invalid")
            by_file[file_id] = version
            if version["is_primary"]:
                primaries.setdefault(doc_id, []).append(version["id"])
        for doc in docs.values():
            if doc["knowledge_id"] != source_space_id or primaries.get(doc["id"]) != [doc["primary_version_id"]]:
                conflict("move_primary_invalid")
            primary = physical[versions[doc["primary_version_id"]]["knowledge_file_id"]]
            if path_ids(primary["file_level_path"]) != path_ids(doc["file_level_path"]):
                conflict("move_primary_location_invalid")
        parents = set()
        for row in physical.values():
            if row["tenant_id"] != tenant or row["knowledge_id"] != source_space_id or row["file_type"] not in (0, 1):
                conflict("move_file_chain_invalid")
            if row["file_type"] == 1 and row["id"] not in by_file:
                conflict("move_unversioned_file")
            if row["status"] in (1, 4, 5) and row["file_type"] == 1:
                raise KnowledgeProcessingConflictError(reason="move_file_processing")
            parents.update(path_ids(row["file_level_path"]))
        target_rows = await self._by_ids(
            session, KnowledgeFile, FILE_FIELDS, [destination_folder_id] if destination_folder_id else []
        )
        if destination_folder_id and (
            not target_rows
            or target_rows[0]["file_type"] != 0
            or target_rows[0]["knowledge_id"] != destination_space_id
            or target_rows[0]["tenant_id"] != tenant
        ):
            conflict("move_destination_invalid")
        destination_path = (*path_ids(target_rows[0]["file_level_path"]), destination_folder_id) if target_rows else ()
        ancestors = await self._by_ids(session, KnowledgeFile, FILE_FIELDS, parents | set(destination_path))
        ancestor_map = {row["id"]: row for row in ancestors}
        for path, space in ((parents, source_space_id), (destination_path, destination_space_id)):
            for key in path:
                row = ancestor_map.get(key)
                if row is None or row["file_type"] != 0 or row["knowledge_id"] != space or row["tenant_id"] != tenant:
                    conflict("move_parent_chain_invalid")
                ancestor_path = path_ids(row["file_level_path"])
                if any(
                    parent not in ancestor_map
                    or path_ids(ancestor_map[parent]["file_level_path"]) != ancestor_path[:index]
                    for index, parent in enumerate(ancestor_path)
                ):
                    conflict("move_parent_path_invalid")
        if for_update:
            for model, fields, expected in (
                (KnowledgeFile, FILE_FIELDS, {**physical, **ancestor_map}),
                (KnowledgeDocument, DOC_FIELDS, docs),
                (KnowledgeDocumentVersion, VERSION_FIELDS, versions),
            ):
                locked = await self._by_ids(session, model, fields, expected, lock=True)
                if {row["id"]: row for row in locked} != expected:
                    conflict("move_locked_scope_changed")
        file_roots = {by_file[root.id]["document_id"]: root for root in roots if root.type == "file"}

        def moved_path(path, doc_id=None):
            old = path_ids(path)
            match = next((index for index, key in enumerate(old) if key in folders), None)
            if match is not None:
                return (*destination_path, *old[match:]), folders[old[match]]
            if doc_id in file_roots:
                return destination_path, file_roots[doc_id]
            conflict("move_document_outside_selection")

        doc_after, owners = {}, {}
        for key, doc in docs.items():
            new_path, owners[key] = moved_path(doc["file_level_path"], key)
            doc_after[key] = {
                **doc,
                "knowledge_id": destination_space_id,
                "file_level_path": "/" + "/".join(map(str, new_path)) if new_path else "",
                "level": len(new_path),
            }
        source_schema = checked(metadata_schema_fields, source["metadata_fields"])
        target_schema = checked(metadata_schema_fields, destination["metadata_fields"])
        retained = tuple(sorted(name for name, kind in source_schema.items() if target_schema.get(name) == kind))
        removed = tuple(sorted(set(source_schema) - set(retained)))
        rows, proposed, selected_for = [], [], {}
        for key, row in sorted(physical.items()):
            if row["file_type"] == 1:
                doc_id = by_file[key]["document_id"]
                new = doc_after[doc_id]
                new_path, selected_for[key] = path_ids(new["file_level_path"]), owners[doc_id]
            elif key in folders:
                new_path, selected_for[key] = destination_path, folders[key]
            else:
                new_path, selected_for[key] = moved_path(row["file_level_path"])
            values = deepcopy(row["user_metadata"])
            if values is not None and not isinstance(values, dict):
                conflict("move_metadata_values_invalid")
            for name in effective_move_removed_fields(file_source=row["file_source"], removed_fields=removed):
                if values is not None:
                    values.pop(name, None)
            after = {
                **deepcopy(row),
                "knowledge_id": destination_space_id,
                "file_level_path": "/" + "/".join(map(str, new_path)) if new_path else "",
                "level": len(new_path),
                "user_metadata": values,
            }
            if row["file_type"] == 1 and row["status"] == 2:
                after["status"] = 4
            rows.append(MoveRow(key, deepcopy(row), after))
            old_parent = path_ids(row["file_level_path"])
            before_ref = ("folder", old_parent[-1]) if old_parent else ("knowledge_space", source_space_id)
            after_ref = ("folder", new_path[-1]) if new_path else ("knowledge_space", destination_space_id)
            if before_ref != after_ref:
                proposed.append(("folder" if row["file_type"] == 0 else "knowledge_file", key, *before_ref, *after_ref))
        if self.parent_states is None:
            conflict("move_parent_state_port_required")
        changes = []
        for offset in range(0, len(proposed), PAGE):
            page = proposed[offset : offset + PAGE]
            facts = await self.parent_states.aread_parent_states(
                session, targets=tuple((item[0], str(item[1])) for item in page)
            )
            facts = {(fact.resource_type, str(fact.resource_id)): fact for fact in facts}
            for kind, key, old_type, old_id, new_type, new_id in page:
                fact = facts.get((kind, str(key)))
                if (
                    fact is None
                    or fact.projection_state != "CURRENT"
                    or (fact.parent_type, str(fact.parent_id)) != (old_type, str(old_id))
                    or fact.mode not in ("INHERIT", "CUSTOM")
                    or type(fact.version) is not int
                    or fact.version < 0
                ):
                    conflict("move_permission_parent_not_current")
                changes.append(MoveParentChange(kind, key, old_type, old_id, new_type, new_id, fact.mode, fact.version))
        change_map = {(change.resource_type, change.resource_id): change for change in changes}
        leaves = []
        row_map = {row.file_id: row for row in rows}
        for version in sorted(versions.values(), key=lambda value: value["id"]):
            key = version["knowledge_file_id"]
            row = row_map[key]
            anchor = change_map.get(("knowledge_file", key)) or next(
                (
                    change_map[("folder", parent)]
                    for parent in path_ids(row.before["file_level_path"])
                    if ("folder", parent) in change_map
                ),
                None,
            )
            if anchor is None:
                conflict("move_projection_anchor_missing")
            path = path_ids(row.after["file_level_path"])
            leaves.append(
                MoveLeaf(
                    ResourceVersionTarget(file_id=key, document_id=version["document_id"], version_id=version["id"]),
                    selected_for[key],
                    path[-1] if path else None,
                    version["version_no"],
                    version["is_primary"],
                    row.before["status"],
                    row.before["status"] == 2,
                    revision(row.before),
                    revision(row.after),
                    anchor,
                )
            )
        links = []
        keys = sorted(str(key) for key in physical)
        for offset in range(0, len(keys), PAGE):
            links.extend(
                await self._rows(
                    session,
                    TagLink,
                    ("id", "tenant_id", "resource_id"),
                    and_(
                        TagLink.__table__.c.resource_id.in_(keys[offset : offset + PAGE]),
                        TagLink.__table__.c.resource_type == ResourceTypeEnum.SPACE_FILE.value,
                    ),
                )
            )
        if any(row["tenant_id"] != tenant for row in links):
            conflict("move_tag_tenant_invalid")
        data = {
            "tenant_id": tenant,
            "source_space_id": source_space_id,
            "destination_space_id": destination_space_id,
            "destination_folder_id": destination_folder_id,
            "roots": roots,
            "source": source,
            "destination": destination,
            "files": tuple(rows),
            "documents": tuple(MoveRow(key, docs[key], doc_after[key]) for key in sorted(docs)),
            "versions": tuple(versions[key] for key in sorted(versions)),
            "leaves": tuple(leaves),
            "parent_changes": tuple(changes),
            "retained_fields": retained,
            "removed_fields": removed,
            "tag_link_ids": tuple(sorted(row["id"] for row in links)),
        }
        scope = MoveScope(
            **data,
            scope_digest=_digest(move_scope_parameters(data)),
            changes_digest=_digest([asdict(row) for row in changes]),
        )
        self._pending(session, scope, set(ancestor_map))
        return scope

    async def _pending_jobs(self, session, spaces):
        pending = [row for row in (*session.new, *session.dirty) if isinstance(row, KnowledgeProcessingJob)]
        keys = [inspect(row).identity[0] for row in pending if inspect(row).identity]
        actual = {
            row["id"]: row
            for row in await self._by_ids(session, KnowledgeProcessingJob, ("id", "space_id", "state", "kind"), keys)
        }
        for row in pending:
            state = inspect(row)
            values = {**actual.get((state.identity or (None,))[0], {}), **state.dict}
            if values.get("space_id") in spaces and values.get("state") in ("accepted", "running"):
                raise KnowledgeProcessingConflictError(reason="move_pending_processing_conflict")

    @staticmethod
    def _pending(session, scope, parent_ids=()):
        native = session.sync_session
        ids = {row.file_id for row in scope.files} | set(parent_ids)
        docs = {row.file_id for row in scope.documents}
        versions = {row["id"] for row in scope.versions}
        for row in (*native.new, *native.dirty, *native.deleted):
            state = inspect(row)

            def values(name, state=state):
                history = state.attrs[name].history
                return (state.dict.get(name), *history.added, *history.deleted)

            keys = (*values("id"), *(state.identity or ())) if "id" in state.attrs else ()
            fields = ()
            if isinstance(row, Knowledge) and {scope.source_space_id, scope.destination_space_id}.intersection(keys):
                fields = ROOT_FIELDS
            elif isinstance(row, KnowledgeFile) and (
                ids.intersection(keys)
                or any(
                    set(path_ids(path)).intersection({root.id for root in scope.roots if root.type == "folder"})
                    for path in values("file_level_path")
                    if path is not None
                )
            ):
                fields = FILE_FIELDS
            elif isinstance(row, KnowledgeDocument) and (
                docs.intersection(keys) or scope.source_space_id in values("knowledge_id")
            ):
                fields = DOC_FIELDS
            elif isinstance(row, KnowledgeDocumentVersion) and (
                versions.intersection(keys)
                or docs.intersection(values("document_id"))
                or ids.intersection(values("knowledge_file_id"))
            ):
                fields = VERSION_FIELDS
            elif isinstance(row, TagLink) and (
                set(scope.tag_link_ids).intersection(keys)
                or {str(key) for key in ids}.intersection(values("resource_id"))
            ):
                fields = ("id", "tenant_id", "tag_id", "resource_id", "resource_type")
            if fields and (
                row in native.new
                or row in native.deleted
                or any(state.attrs[name].history.has_changes() for name in fields)
            ):
                conflict("move_pending_scope_change")

    @staticmethod
    def _input_query(space_id, tenant):
        plan, job, item = (
            KnowledgeOperationPlan.__table__,
            KnowledgeProcessingJob.__table__,
            KnowledgeProcessingItem.__table__,
        )
        count = select(func.count(item.c.id)).where(item.c.job_id == job.c.id).scalar_subquery()
        invalid = or_(item.c.tenant_id != tenant, item.c.state != "succeeded")
        unfinished = select(item.c.id).where(item.c.job_id == job.c.id, invalid).exists()
        protected = or_(
            job.c.id.is_(None),
            job.c.tenant_id != tenant,
            job.c.kind != "move_index",
            and_(job.c.total_count == 0, job.c.state != "succeeded"),
            or_(count != job.c.total_count, unfinished),
        )
        linked = (
            select(plan.c.id)
            .select_from(plan.outerjoin(job, job.c.id == plan.c.operation_id))
            .where(
                plan.c.tenant_id == tenant,
                plan.c.space_id == Knowledge.id,
                plan.c.operation == "move",
                plan.c.operation_id.is_not(None),
                protected,
            )
        )
        return select(Knowledge.id, linked.exists().label("blocked")).where(Knowledge.id == space_id)

    @staticmethod
    def _pending_input_queries(session, space_id, tenant):
        native = session.sync_session if isinstance(session, AsyncSession) else session
        candidates = []
        for row in (*native.new, *native.dirty, *native.deleted):
            state = inspect(row)
            if isinstance(row, KnowledgeOperationPlan) and row in native.new:
                if (
                    state.dict.get("operation") == "move"
                    and state.dict.get("space_id") == space_id
                    and state.dict.get("operation_id")
                ):
                    raise KnowledgeProcessingConflictError(reason="move_pending_source_input")
            if isinstance(row, (KnowledgeOperationPlan, KnowledgeProcessingJob, KnowledgeProcessingItem)):
                keys = (
                    *state.attrs.id.history.added,
                    *state.attrs.id.history.deleted,
                    state.dict.get("id"),
                    *(state.identity or ()),
                )
                candidates.extend((type(row), key) for key in keys if type(key) is str and key)
        plan, item = KnowledgeOperationPlan.__table__, KnowledgeProcessingItem.__table__
        for offset in range(0, len(candidates), PAGE):
            page = candidates[offset : offset + PAGE]

            def keys(model, page=page):
                return [key for kind, key in page if kind is model]

            affected = or_(
                plan.c.id.in_(keys(KnowledgeOperationPlan)),
                plan.c.operation_id.in_(keys(KnowledgeProcessingJob)),
                plan.c.operation_id.in_(select(item.c.job_id).where(item.c.id.in_(keys(KnowledgeProcessingItem)))),
            )
            linked = select(plan.c.id).where(
                plan.c.tenant_id == tenant,
                plan.c.space_id == Knowledge.id,
                plan.c.operation == "move",
                plan.c.operation_id.is_not(None),
                affected,
            )
            yield select(Knowledge.id).where(Knowledge.id == space_id, linked.exists())

    async def aassert_no_unsettled_move_inputs(self, session, space_id):
        tenant = self._context(session, space_id)
        with session.no_autoflush, strict_tenant_filter():
            row = (await session.execute(self._input_query(space_id, tenant))).first()
            if row is None:
                raise SpaceNotFoundError()
            if row.blocked:
                raise KnowledgeProcessingConflictError(reason="move_source_input_required")
            for query in self._pending_input_queries(session, space_id, tenant):
                if (await session.execute(query)).first():
                    raise KnowledgeProcessingConflictError(reason="move_pending_source_input")

    def assert_no_unsettled_move_inputs(self, session, space_id):
        tenant = self._context(session, space_id)
        with session.no_autoflush, strict_tenant_filter():
            row = session.execute(self._input_query(space_id, tenant)).first()
            if row is None:
                raise SpaceNotFoundError()
            if row.blocked:
                raise KnowledgeProcessingConflictError(reason="move_source_input_required")
            for query in self._pending_input_queries(session, space_id, tenant):
                if session.execute(query).first():
                    raise KnowledgeProcessingConflictError(reason="move_pending_source_input")
