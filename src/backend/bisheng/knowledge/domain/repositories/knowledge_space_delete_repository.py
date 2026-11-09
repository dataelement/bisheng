"""Atomic business cutover and leased, tenant-scoped cleanup jobs."""

from dataclasses import fields
from datetime import timedelta
from uuid import uuid4

from sqlmodel import col, delete, or_, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    get_current_tenant_id,
    is_tenant_filter_bypassed,
    strict_tenant_filter,
)
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_delete_job import (
    DELETE_STEPS,
    KnowledgeSpaceDeleteJob,
    deletion_now,
)
from bisheng.knowledge.domain.repositories.knowledge_version_mutation_repository import (
    VersionDocumentFact,
    VersionRowFact,
)
from bisheng.knowledge.domain.repositories.knowledge_version_read_repository import KnowledgeVersionReadRepository
from bisheng.knowledge.domain.schemas.direct_delete_scope import (
    DeleteResourceFact,
    DeleteScope,
    DeleteSelection,
    DeleteSelectionIssue,
    DeleteUnit,
)
from bisheng.knowledge.domain.schemas.move_processing import move_path_ids

LEASE_SECONDS = 900


class KnowledgeSpaceDeleteRepository:
    def __init__(self, session_factory=get_async_db_session):
        self.session_factory = session_factory

    @staticmethod
    def tenant_id() -> int:
        value = get_current_tenant_id()
        if value is None or int(value) <= 0:
            raise RuntimeError("knowledge deletion requires an explicit tenant")
        return int(value)

    @staticmethod
    def _delete_path(value):
        try:
            return move_path_ids(value)
        except ValueError as error:
            raise KnowledgeOperationPlanConflictError(reason="delete_scope_path_invalid") from error

    async def _delete_rows(self, session, space_id, model, names, condition, *, via="document_id"):
        root, table = Knowledge.__table__, model.__table__
        checks = [Knowledge.tenant_id]
        if model is KnowledgeDocumentVersion:
            parent = KnowledgeFile.__table__ if via == "knowledge_file_id" else KnowledgeDocument.__table__
            joined = root.join(parent, parent.c.knowledge_id == root.c.id).join(table, table.c[via] == parent.c.id)
            if via == "knowledge_file_id":
                checks.append(parent.c.tenant_id)
        else:
            joined = root.join(table, table.c.knowledge_id == root.c.id)
        if model is KnowledgeFile:
            checks.append(table.c.tenant_id)
        query = (
            select(*checks, *(table.c[name] for name in names))
            .select_from(joined)
            .where(Knowledge.id == space_id, condition)
        )
        result, after = {}, None
        with session.no_autoflush, strict_tenant_filter():
            while True:
                page = query if after is None else query.where(table.c.id > after)
                rows = (await session.execute(page.order_by(table.c.id).limit(201))).all()
                for row in rows:
                    if any(value != get_current_tenant_id() for value in row[: len(checks)]):
                        raise KnowledgeOperationPlanConflictError(reason="delete_scope_child_tenant")
                for row in rows[:200]:
                    values = dict(zip(names, row[len(checks) :], strict=True))
                    if type(values["id"]) is not int or values["id"] <= 0:
                        raise KnowledgeOperationPlanConflictError(reason="delete_scope_identifier")
                    result[values["id"]] = values
                if len(rows) <= 200:
                    return result
                after = rows[199][len(checks) + names.index("id")]

    async def _delete_ids(self, session, space_id, model, names, ids, *, key="id"):
        result, ordered = {}, sorted(set(ids))
        for start in range(0, len(ordered), 200):
            result.update(
                await self._delete_rows(
                    session, space_id, model, names, model.__table__.c[key].in_(ordered[start : start + 200]), via=key
                )
            )
        return result

    @staticmethod
    def _delete_units(groups, by_file, by_document, resources):
        units = []
        version_index = {row["id"]: row for row in by_file.values()}
        primary = {key: next(row["id"] for row in chain if row["is_primary"]) for key, chain in by_document.items()}
        for positions, ids in groups:
            selected = {}
            for ident in ids:
                if ident in by_file:
                    version = by_file[ident]
                    selected.setdefault(version["document_id"], set()).add(version["id"])
            version_ids, deleted_docs, expanded = set(), set(), set(ids)
            for doc_id, chosen in selected.items():
                chain = by_document[doc_id]
                remove = primary[doc_id] in chosen or len(chosen) == len(chain)
                removed = chain if remove else [version_index[key] for key in chosen]
                version_ids.update(row["id"] for row in removed)
                expanded.update(row["knowledge_file_id"] for row in removed)
                if remove:
                    deleted_docs.add(doc_id)
            units.append((set(positions), expanded, version_ids, deleted_docs))
        parent, owners = list(range(len(units))), {}

        def find(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        for index, (_, ids, versions, documents) in enumerate(units):
            for kind, values in (("resource", ids), ("version", versions), ("document", documents)):
                for ident in values:
                    key = kind, ident
                    if key in owners:
                        parent[find(index)] = find(owners[key])
                    owners[key] = index
        merged = {}
        for index, unit in enumerate(units):
            target = merged.setdefault(find(index), (set(), set(), set(), set()))
            for output, values in zip(target, unit, strict=True):
                output.update(values)
        result = []
        for positions, ids, versions, documents in merged.values():
            files = {key for key in ids if resources[key]["file_type"] == 1}
            busy = {key for key in files if resources[key]["status"] in (1, 4, 5)}
            values = (positions, ids, versions, documents, files - by_file.keys(), busy)
            result.append(DeleteUnit(*(tuple(sorted(value)) for value in values)))
        return tuple(sorted(result, key=lambda unit: unit.selection_positions[0]))

    async def aread_delete_scope(
        self, session: AsyncSession, *, space_id: int, selections: tuple[DeleteSelection, ...], for_update: bool = False
    ) -> DeleteScope:
        tenant = get_current_tenant_id()
        if (
            not isinstance(session, AsyncSession)
            or type(tenant) is not int
            or tenant <= 0
            or is_tenant_filter_bypassed()
            or type(space_id) is not int
            or space_id <= 0
            or type(for_update) is not bool
            or type(selections) is not tuple
            or any(type(value) is not DeleteSelection for value in selections)
        ):
            raise ValueError("delete scope requires a native session, concrete tenant and typed selections")
        if not selections:
            return DeleteScope(tenant, space_id, selections)
        if not session.in_transaction():
            raise ValueError("delete scope requires the caller transaction")
        root_fields = ("id", "name", "type", "tenant_id", "user_id", "model", "index_name", "collection_name")
        query = select(*(getattr(Knowledge, name) for name in root_fields)).where(Knowledge.id == space_id)
        with session.no_autoflush, strict_tenant_filter():
            root = (await session.execute(query.with_for_update() if for_update else query)).mappings().one_or_none()
        if root is None or root["tenant_id"] != tenant or root["type"] != 3:
            raise SpaceFileNotFoundError()
        names = (
            "id",
            "tenant_id",
            "knowledge_id",
            "file_type",
            "file_name",
            "file_level_path",
            "level",
            "status",
            "user_id",
            "update_time",
            "object_name",
            "preview_file_object_name",
            "bbox_object_name",
            "thumbnails",
        )
        rows = await self._delete_ids(
            session, space_id, KnowledgeFile, names, [value.resource_id for value in selections]
        )
        positions, issues, valid = {}, [], {}
        for position, selection in enumerate(selections):
            positions.setdefault(selection, []).append(position)
        for selection, aliases in positions.items():
            row = rows.get(selection.resource_id)
            if row is None:
                issues.append(DeleteSelectionIssue(tuple(aliases), "not_found"))
            elif row["file_type"] != (0 if selection.resource_type == "folder" else 1):
                issues.append(DeleteSelectionIssue(tuple(aliases), "type_mismatch"))
            else:
                valid[selection.resource_id] = row
        if any(key in self._delete_path(row["file_level_path"]) for key, row in valid.items()):
            raise KnowledgeOperationPlanConflictError(reason="delete_scope_cycle")
        folders = {key for key, row in valid.items() if row["file_type"] == 0}
        minimal = {
            key for key, row in valid.items() if not folders.intersection(self._delete_path(row["file_level_path"]))
        }
        groups = {key: ([], {key}) for key in minimal}
        for selection, aliases in positions.items():
            if selection.resource_id not in valid or selection.resource_type != (
                "folder" if valid[selection.resource_id]["file_type"] == 0 else "knowledge_file"
            ):
                continue
            key = next(
                (key for key in self._delete_path(valid[selection.resource_id]["file_level_path"]) if key in minimal),
                selection.resource_id,
            )
            groups[key][0].extend(aliases)
        physical = {key: valid[key] for key in minimal}
        prefixes = {key: (*self._delete_path(valid[key]["file_level_path"]), key) for key in minimal & folders}
        prefix_items = list(prefixes.items())
        for start in range(0, len(prefix_items), 200):
            batch = prefix_items[start : start + 200]
            paths = ["/" + "/".join(map(str, path)) for _, path in batch]
            condition = or_(
                *(
                    or_(
                        KnowledgeFile.file_level_path == path,
                        KnowledgeFile.file_level_path.startswith(path + "/", autoescape=True),
                    )
                    for path in paths
                )
            )
            descendants = await self._delete_rows(session, space_id, KnowledgeFile, names, condition)
            for key, row in descendants.items():
                owner = next((key for key in self._delete_path(row["file_level_path"]) if key in prefixes), None)
                if owner is None:
                    raise KnowledgeOperationPlanConflictError(reason="delete_scope_subtree")
                groups[owner][1].add(key)
            physical.update(descendants)
        version_names = tuple(item.name for item in fields(VersionRowFact))
        document_names = tuple(item.name for item in fields(VersionDocumentFact))
        attached = await self._delete_ids(
            session, space_id, KnowledgeDocumentVersion, version_names, physical, key="knowledge_file_id"
        )
        doc_ids = {row["document_id"] for row in attached.values()}
        documents = await self._delete_ids(session, space_id, KnowledgeDocument, document_names, doc_ids)
        if set(documents) != doc_ids:
            raise KnowledgeOperationPlanConflictError(reason="delete_scope_document_missing")
        versions = await self._delete_ids(
            session, space_id, KnowledgeDocumentVersion, version_names, doc_ids, key="document_id"
        )
        by_file, by_document = {}, {}
        for version in versions.values():
            if version["knowledge_file_id"] in by_file:
                raise KnowledgeOperationPlanConflictError(reason="delete_scope_duplicate_file")
            by_file[version["knowledge_file_id"]] = version
            by_document.setdefault(version["document_id"], []).append(version)
        for doc in documents.values():
            chain = by_document.get(doc["id"], [])
            primary = [row["id"] for row in chain if row["is_primary"]]
            stats = (
                len(chain),
                len({row["knowledge_file_id"] for row in chain}),
                len(primary),
                max(primary) if primary else None,
                min((row["version_no"] for row in chain), default=0),
            )
            KnowledgeVersionReadRepository._check_document(VersionDocumentFact(**doc), stats)
        ordered_docs = sorted(doc_ids)
        for start in range(0, len(ordered_docs), 200):
            with session.no_autoflush:
                await KnowledgeVersionReadRepository._check_links(
                    session, ordered_docs[start : start + 200], tenant, space_id
                )
        physical.update(await self._delete_ids(session, space_id, KnowledgeFile, names, set(by_file) - physical.keys()))
        if not set(by_file) <= physical.keys() or any(row["file_type"] not in (0, 1) for row in physical.values()):
            raise KnowledgeOperationPlanConflictError(reason="delete_scope_file_missing")
        ancestors = {key for row in physical.values() for key in self._delete_path(row["file_level_path"])}
        parents = await self._delete_ids(session, space_id, KnowledgeFile, names, ancestors)
        for row in physical.values():
            path = self._delete_path(row["file_level_path"])
            if row["id"] in path:
                raise KnowledgeOperationPlanConflictError(reason="delete_scope_cycle")
            for index, key in enumerate(path):
                parent = parents.get(key)
                if (
                    parent is None
                    or parent["file_type"] != 0
                    or self._delete_path(parent["file_level_path"]) != path[:index]
                ):
                    raise KnowledgeOperationPlanConflictError(reason="delete_scope_ancestor")
        units = self._delete_units(groups.values(), by_file, by_document, physical)
        deleting = {key for unit in units for key in unit.resource_ids}
        if for_update:
            # An ancestor reread must not replace the facts returned for deletion.
            for model, columns, expected in (
                (KnowledgeFile, names, {**parents, **physical}),
                (KnowledgeDocument, document_names, documents),
                (KnowledgeDocumentVersion, version_names, versions),
            ):
                ordered = sorted(expected)
                for start in range(0, len(ordered), 200):
                    table = model.__table__
                    query = (
                        select(*(table.c[name] for name in columns))
                        .where(table.c.id.in_(ordered[start : start + 200]))
                        .order_by(table.c.id)
                        .with_for_update()
                    )
                    with session.no_autoflush, strict_tenant_filter():
                        locked = (await session.execute(query)).mappings().all()
                    if {row["id"]: dict(row) for row in locked} != {
                        key: expected[key] for key in ordered[start : start + 200]
                    }:
                        raise KnowledgeOperationPlanConflictError(reason="delete_scope_changed")
        facts = []
        for key in sorted(deleting):
            row = physical[key]
            objects = {row[name] for name in names[-4:] if row[name]}
            if row["file_type"] == 1:
                objects.add(str(key))
            facts.append(
                DeleteResourceFact(**{name: row[name] for name in names[:-4]}, object_names=tuple(sorted(objects)))
            )
        if get_current_tenant_id() != tenant or is_tenant_filter_bypassed():
            raise KnowledgeOperationPlanConflictError(reason="delete_scope_context_changed")
        return DeleteScope(
            tenant,
            space_id,
            selections,
            tuple(facts),
            tuple(VersionDocumentFact(**documents[key]) for key in sorted(documents)),
            tuple(VersionRowFact(**versions[key]) for key in sorted(versions)),
            units,
            tuple(issues),
            dict(root),
            tuple(sorted({name for row in facts for name in row.object_names})),
        )

    async def prepare(self, session, resource: KnowledgeFile) -> dict:
        """Lock the subtree and resolve primary-version expansion without writes."""
        tenant_id = self.tenant_id()
        space = (
            await session.exec(select(Knowledge).where(Knowledge.id == resource.knowledge_id).with_for_update())
        ).first()
        if space is None or space.type != KnowledgeTypeEnum.SPACE.value or space.tenant_id != tenant_id:
            raise SpaceFileNotFoundError()
        root = (
            await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == resource.id).with_for_update())
        ).first()
        if root is None or root.tenant_id != tenant_id or root.knowledge_id != space.id:
            raise SpaceFileNotFoundError()
        if (root.file_name, root.file_level_path, root.file_type) != (
            resource.file_name,
            resource.file_level_path,
            resource.file_type,
        ):
            raise RuntimeError("delete resource changed before cutover")
        rows = [root]
        if root.file_type == FileType.DIR.value:
            prefix = f"{root.file_level_path or ''}/{root.id}"
            rows += list(
                (
                    await session.exec(
                        select(KnowledgeFile)
                        .where(
                            KnowledgeFile.knowledge_id == space.id,
                            or_(
                                KnowledgeFile.file_level_path == prefix,
                                col(KnowledgeFile.file_level_path).startswith(prefix + "/"),
                            ),
                        )
                        .order_by(KnowledgeFile.id)
                        .with_for_update()
                    )
                ).all()
            )
        file_ids = {int(row.id) for row in rows if row.file_type == FileType.FILE.value}
        versions = (
            list(
                (
                    await session.exec(
                        select(KnowledgeDocumentVersion)
                        .where(col(KnowledgeDocumentVersion.knowledge_file_id).in_(file_ids))
                        .order_by(KnowledgeDocumentVersion.document_id, KnowledgeDocumentVersion.id)
                        .with_for_update()
                    )
                ).all()
            )
            if file_ids
            else []
        )
        selected_by_document: dict[int, list] = {}
        for version in versions:
            selected_by_document.setdefault(version.document_id, []).append(version)
        version_ids, document_ids = set(), set()
        for document_id, selected in selected_by_document.items():
            document = (
                await session.exec(
                    select(KnowledgeDocument)
                    .where(KnowledgeDocument.id == document_id, KnowledgeDocument.knowledge_id == space.id)
                    .with_for_update()
                )
            ).first()
            if document is None:
                raise RuntimeError("delete version anchor is outside the space")
            chain = list(
                (
                    await session.exec(
                        select(KnowledgeDocumentVersion)
                        .where(KnowledgeDocumentVersion.document_id == document_id)
                        .order_by(KnowledgeDocumentVersion.id)
                        .with_for_update()
                    )
                ).all()
            )
            remove_chain = any(version.is_primary for version in selected) or len(selected) == len(chain)
            removed = chain if remove_chain else selected
            version_ids.update(version.id for version in removed)
            file_ids.update(version.knowledge_file_id for version in removed)
            if remove_chain:
                document_ids.add(document_id)
        sibling_ids = file_ids - {row.id for row in rows}
        if sibling_ids:
            siblings = list(
                (
                    await session.exec(
                        select(KnowledgeFile)
                        .where(KnowledgeFile.knowledge_id == space.id, col(KnowledgeFile.id).in_(sibling_ids))
                        .order_by(KnowledgeFile.id)
                        .with_for_update()
                    )
                ).all()
            )
            if {row.id for row in siblings} != sibling_ids:
                raise RuntimeError("delete version siblings are missing or outside the space")
            rows += siblings
        if any(row.tenant_id != tenant_id for row in rows):
            raise SpaceFileNotFoundError()
        return {
            "rows": sorted(row.id for row in rows),
            "file_ids": sorted(file_ids),
            "folder_ids": sorted(row.id for row in rows if row.file_type == FileType.DIR.value),
            "version_ids": sorted(version_ids),
            "document_ids": sorted(document_ids),
            "fga_resources": [
                {
                    "resource_type": "folder" if row.file_type == FileType.DIR.value else "knowledge_file",
                    "resource_id": row.id,
                }
                for row in sorted(rows, key=lambda row: row.id)
            ],
            "object_names": sorted(
                {
                    str(value)
                    for row in rows
                    for value in (
                        row.object_name,
                        row.preview_file_object_name,
                        row.bbox_object_name,
                        row.thumbnails,
                        str(row.id) if row.file_type == FileType.FILE.value else None,
                    )
                    if value
                }
            ),
            "knowledge": space.model_dump(
                include={"id", "name", "type", "tenant_id", "user_id", "model", "index_name", "collection_name"}
            ),
        }

    async def cutover(self, session, manifest: dict) -> None:
        """Delete the formal graph in the same transaction that inserts the job."""
        space_id = int(manifest["knowledge"]["id"])
        if manifest["document_ids"]:
            await session.exec(
                update(KnowledgeDocument)
                .where(
                    KnowledgeDocument.knowledge_id == space_id, col(KnowledgeDocument.id).in_(manifest["document_ids"])
                )
                .values(primary_version_id=None)
            )
        if manifest["version_ids"]:
            await session.exec(
                delete(KnowledgeDocumentVersion).where(col(KnowledgeDocumentVersion.id).in_(manifest["version_ids"]))
            )
        if manifest["document_ids"]:
            await session.exec(
                delete(KnowledgeDocument).where(
                    KnowledgeDocument.knowledge_id == space_id, col(KnowledgeDocument.id).in_(manifest["document_ids"])
                )
            )
        await session.exec(
            delete(KnowledgeFile).where(
                KnowledgeFile.knowledge_id == space_id, col(KnowledgeFile.id).in_(manifest["rows"])
            )
        )
        await session.flush()

    async def _locked_job(self, session, job_id):
        job = (
            await session.exec(
                select(KnowledgeSpaceDeleteJob).where(KnowledgeSpaceDeleteJob.id == job_id).with_for_update()
            )
        ).first()
        if job is None or job.tenant_id != self.tenant_id():
            raise LookupError("delete job not found in the current tenant")
        return job

    async def claim(self, job_id: str) -> KnowledgeSpaceDeleteJob | None:
        async with self.session_factory() as session, session.begin():
            job = await self._locked_job(session, job_id)
            now = deletion_now()
            if job.state == "SUCCEEDED" or job.next_attempt_at > now or (job.lease_until and job.lease_until > now):
                return None
            job.state = "RUNNING"
            job.attempts += 1
            job.lease_token = str(uuid4())
            job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
            job.update_time = now
            session.add(job)
            await session.flush()
            session.expunge(job)
            return job

    async def advance(self, job, *, step: str | None = None, error: str | None = None, complete=False) -> None:
        async with self.session_factory() as session, session.begin():
            row = await self._locked_job(session, job.id)
            if row.state != "RUNNING" or row.lease_token != job.lease_token:
                raise RuntimeError("delete job lease was replaced")
            if (
                step
                and step not in row.completed_steps
                and (step not in DELETE_STEPS or list(DELETE_STEPS[: DELETE_STEPS.index(step)]) != row.completed_steps)
            ):
                raise RuntimeError("delete job steps must finish in order")
            if complete and row.completed_steps != list(DELETE_STEPS):
                raise RuntimeError("delete job has unverified cleanup steps")
            row.update_time = deletion_now()
            row.lease_until = row.update_time + timedelta(seconds=LEASE_SECONDS)
            if step:
                row.completed_steps = list(dict.fromkeys([*row.completed_steps, step]))
            if error is not None or complete:
                row.state = "SUCCEEDED" if complete else "PENDING"
                row.last_error = error[:4000] if error is not None else None
                row.next_attempt_at = row.update_time + timedelta(seconds=60)
                row.lease_token = None
                row.lease_until = None
            session.add(row)

    async def due_jobs(self, *, limit=100) -> list[tuple[int, str]]:
        # Beat enumerates routing metadata only; execution restores each tenant.
        with bypass_tenant_filter():
            async with self.session_factory() as session:
                now = deletion_now()
                rows = (
                    await session.exec(
                        select(KnowledgeSpaceDeleteJob.tenant_id, KnowledgeSpaceDeleteJob.id)
                        .where(
                            KnowledgeSpaceDeleteJob.state != "SUCCEEDED",
                            KnowledgeSpaceDeleteJob.next_attempt_at <= now,
                            or_(
                                KnowledgeSpaceDeleteJob.lease_until.is_(None),
                                KnowledgeSpaceDeleteJob.lease_until <= now,
                            ),
                        )
                        .order_by(KnowledgeSpaceDeleteJob.next_attempt_at, KnowledgeSpaceDeleteJob.id)
                        .limit(limit)
                    )
                ).all()
                return [(int(tenant_id), str(job_id)) for tenant_id, job_id in rows]
