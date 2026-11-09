"""Owned whole-space copy facts and independent native resource mappings."""

from copy import deepcopy
from dataclasses import dataclass

from sqlalchemy import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError, KnowledgeProcessingConflictError
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Document
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibrary as Library
from bisheng.knowledge.domain.repositories.move_batch_repository import MoveBatchRepository
from bisheng.knowledge.domain.repositories.move_row_repository import MoveRowRepository
from bisheng.knowledge.domain.repositories.operation_plan_repository import _digest
from bisheng.knowledge.domain.schemas.move_processing import DOC_FIELDS, MoveRoot, move_path_ids
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils


@dataclass(frozen=True, slots=True)
class SpaceCopyScope:
    source: dict
    files: tuple[dict, ...]
    documents: tuple[dict, ...]
    versions: tuple[dict, ...]
    tags: tuple[dict, ...]
    links: tuple[dict, ...]
    library: dict | None

    def payload(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def digest(self):
        return _digest(self.payload())


class SpaceCopyRepository(MoveRowRepository):
    async def aroot(self, session, space_id, *, lock=False):
        with session.no_autoflush, strict_tenant_filter():
            query = select(Knowledge).where(Knowledge.id == space_id)
            row = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
        if row is None or row.tenant_id != get_current_tenant_id() or row.type != 3:
            raise KnowledgeOperationPlanChangedError()
        return row

    async def aload_scope(self, session, space_id, *, lock=False):
        source = await self.aroot(session, space_id, lock=lock)
        if source.state != 1 or source.model_transition is not None:
            raise KnowledgeProcessingConflictError(reason="copy_source_processing")
        files = await self._rows(
            session, File, tuple(File.__table__.c.keys()), File.knowledge_id == space_id, lock=lock
        )
        docs = await self._rows(session, Document, DOC_FIELDS, Document.knowledge_id == space_id, lock=lock)
        if files:
            batch = await MoveBatchRepository(max_folder_level=9).aread(
                session,
                source_space_id=space_id,
                destination_space_id=space_id,
                roots=tuple(MoveRoot("folder" if row["file_type"] == 0 else "file", row["id"]) for row in files),
                destination_folder_id=None,
                lock=lock,
            )
            if (
                {row["id"] for row in batch.files} != {row["id"] for row in files}
                or {row["id"] for row in batch.documents} != {row["id"] for row in docs}
                or any(value in {"not_found", "unsupported", "processing"} for value in batch.issues.values())
            ):
                raise KnowledgeProcessingConflictError(reason="copy_complete_scope_required")
            versions = batch.versions
        else:
            if docs:
                raise KnowledgeOperationPlanChangedError()
            versions = ()
        if any(row["file_type"] == 1 and row["status"] in {1, 4, 5} for row in files):
            raise KnowledgeProcessingConflictError(reason="copy_source_file_processing")
        with session.no_autoflush, strict_tenant_filter():
            tags = (
                (
                    await session.execute(
                        select(Tag)
                        .where(
                            Tag.business_id == str(space_id), Tag.business_type.in_(("knowledge_space", "knowledge"))
                        )
                        .order_by(Tag.id)
                    )
                )
                .scalars()
                .all()
            )
            library = await session.get(Library, source.auto_tag_library_id) if source.auto_tag_library_id else None
        if source.auto_tag_library_id and (library is None or library.tenant_id != source.tenant_id):
            raise KnowledgeOperationPlanChangedError()
        links = await self._by_ids(
            session, TagLink, tuple(TagLink.__table__.c.keys()), [str(row["id"]) for row in files], key="resource_id"
        )
        tag_ids = {row.id for row in tags}
        if any(
            row["tag_id"] not in tag_ids or row["resource_type"] != ResourceTypeEnum.SPACE_FILE.value for row in links
        ):
            raise KnowledgeOperationPlanChangedError()
        return SpaceCopyScope(
            source.model_dump(mode="json"),
            tuple(File(**row).model_dump(mode="json") for row in files),
            tuple(docs),
            tuple(versions),
            tuple(row.model_dump(mode="json") for row in tags),
            tuple(TagLink(**row).model_dump(mode="json") for row in links),
            library.model_dump(mode="json") if library is not None else None,
        )

    async def aallocate(self, session, *, scope, target, creator_id):
        files, docs, versions, tags = {}, {}, {}, {}
        for row in scope.files:
            values = {
                key: deepcopy(value) for key, value in row.items() if key not in {"id", "create_time", "update_time"}
            }
            values.update(
                knowledge_id=target.id,
                user_id=creator_id,
                updater_id=creator_id,
                status=5 if row["file_type"] == 1 else row["status"],
            )
            file = File.model_validate(values)
            session.add(file)
            await session.flush()
            files[row["id"]] = file
        for row in scope.files:
            file = files[row["id"]]
            path = tuple(files[key].id for key in move_path_ids(row["file_level_path"]))
            file.file_level_path, file.level = ("/" + "/".join(map(str, path)) if path else ""), len(path)
            if file.file_type == 1:
                file.object_name = (
                    KnowledgeUtils.get_knowledge_file_object_name(file.id, file.file_name)
                    if row["object_name"]
                    else None
                )
                file.preview_file_object_name = (
                    KnowledgeUtils.get_knowledge_preview_file_object_name(file.id, file.file_name)
                    if row["preview_file_object_name"]
                    else None
                )
                file.bbox_object_name = (
                    KnowledgeUtils.get_knowledge_bbox_file_object_name(file.id) if row["bbox_object_name"] else None
                )
                file.thumbnails = f"knowledge/images/{target.id}/{file.id}/thumbnail" if row["thumbnails"] else None
        for row in scope.documents:
            path = tuple(files[key].id for key in move_path_ids(row["file_level_path"]))
            doc = Document(
                knowledge_id=target.id, file_level_path="/" + "/".join(map(str, path)) if path else "", level=len(path)
            )
            session.add(doc)
            await session.flush()
            docs[row["id"]] = doc
        for row in scope.versions:
            version = Version(
                document_id=docs[row["document_id"]].id,
                knowledge_file_id=files[row["knowledge_file_id"]].id,
                version_no=row["version_no"],
                is_primary=row["is_primary"],
            )
            session.add(version)
            await session.flush()
            versions[row["id"]] = version
        for row in scope.documents:
            docs[row["id"]].primary_version_id = versions[row["primary_version_id"]].id
        for row in scope.tags:
            tag = Tag(
                name=row["name"],
                business_type="knowledge_space",
                business_id=str(target.id),
                user_id=creator_id,
                tenant_id=target.tenant_id,
            )
            session.add(tag)
            await session.flush()
            tags[row["id"]] = tag.id
        for row in scope.links:
            session.add(
                TagLink(
                    tag_id=tags[row["tag_id"]],
                    resource_id=str(files[int(row["resource_id"])].id),
                    resource_type=ResourceTypeEnum.SPACE_FILE.value,
                    user_id=creator_id,
                    tenant_id=target.tenant_id,
                )
            )
        if scope.library is not None:
            values = {
                key: deepcopy(value)
                for key, value in scope.library.items()
                if key not in {"id", "create_time", "update_time"}
            }
            values.update(
                owner_knowledge_id=target.id, tenant_id=target.tenant_id, user_id=creator_id, is_builtin=False
            )
            library = Library.model_validate(values)
            session.add(library)
            await session.flush()
            target.auto_tag_library_id = library.id
        await session.flush()
        return {
            "files": {str(key): value.model_dump(mode="json") for key, value in files.items()},
            "documents": {str(key): value.model_dump(mode="json") for key, value in docs.items()},
            "versions": {str(key): value.model_dump(mode="json") for key, value in versions.items()},
        }

    async def aitem_facts(self, session, *, source_id, target_id, source_file_id, target_file_id):
        source = await self.aroot(session, source_id)
        target = await self.aroot(session, target_id)
        files = await self._by_ids(session, File, tuple(File.__table__.c.keys()), (source_file_id, target_file_id))
        found = {row["id"]: File(**row).model_dump(mode="json") for row in files}
        if (
            set(found) != {source_file_id, target_file_id}
            or found[source_file_id]["knowledge_id"] != source_id
            or found[target_file_id]["knowledge_id"] != target_id
        ):
            raise KnowledgeOperationPlanChangedError()
        return source, target, found[source_file_id], found[target_file_id]
