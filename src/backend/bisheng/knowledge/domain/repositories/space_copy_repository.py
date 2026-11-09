"""Owned whole-space copy facts and independent native resource mappings."""

import json
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
from bisheng.knowledge.domain.schemas.move_processing import DOC_FIELDS, ROOT_FIELDS, MoveRoot, move_path_ids
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils


def object_names(row, target_space_id, target_file_id):
    return {
        "object_name": KnowledgeUtils.get_knowledge_file_object_name(target_file_id, row["file_name"])
        if row["object_name"]
        else None,
        "preview_file_object_name": (
            KnowledgeUtils.get_knowledge_preview_file_object_name(target_file_id, row["file_name"])
            or f"preview/{target_file_id}/{row['file_name']}"
        )
        if row["preview_file_object_name"]
        else None,
        "bbox_object_name": KnowledgeUtils.get_knowledge_bbox_file_object_name(target_file_id)
        if row["bbox_object_name"]
        else None,
        "thumbnails": f"knowledge/images/{target_space_id}/{target_file_id}/thumbnail" if row["thumbnails"] else None,
    }


def root_facts(row):
    value = row.model_dump(mode="json", exclude={"create_time", "update_time"})
    value.update(
        {
            key: deepcopy(getattr(row, key))
            for key in (*ROOT_FIELDS, "processing_defaults", "processing_config_version")
            if key not in value
        }
    )
    return value


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

    @property
    def execution_digest(self):
        # Names/defaults, tags and library were already cloned at acceptance.
        # Only the original indexed physical versions and serving tuple remain
        # copy inputs; a future-upload setting must not expire an accepted job.
        return _digest(
            {
                "source": {key: self.source[key] for key in (*ROOT_FIELDS, "user_id")},
                "files": self.files,
                "documents": self.documents,
                "versions": self.versions,
            }
        )


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
            root_facts(source),
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
                user_name=None,
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
                if file.split_rule:
                    rules = json.loads(file.split_rule)
                    if "knowledge_id" in rules:
                        rules["knowledge_id"] = target.id
                    file.split_rule = json.dumps(rules, ensure_ascii=False)
                for name, value in object_names(row, target.id, file.id).items():
                    setattr(file, name, value)
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
            "files": {
                str(key): value.model_dump(mode="json", exclude={"create_time", "update_time"})
                for key, value in files.items()
            },
            "documents": {
                str(key): value.model_dump(mode="json", exclude={"create_time", "update_time"})
                for key, value in docs.items()
            },
            "versions": {
                str(key): value.model_dump(mode="json", exclude={"create_time", "update_time"})
                for key, value in versions.items()
            },
        }

    async def aread_empty_plan(self, session, *, target_id):
        from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan as Plan

        with session.no_autoflush, strict_tenant_filter():
            rows = (
                (
                    await session.execute(
                        select(Plan)
                        .where(
                            Plan.tenant_id == get_current_tenant_id(),
                            Plan.operation == "space_copy_empty",
                            Plan.operation_id == str(target_id),
                        )
                        .limit(2)
                    )
                )
                .scalars()
                .all()
            )
        if len(rows) != 1:
            raise KnowledgeOperationPlanChangedError()
        return rows[0]

    async def aread_directory_mapping(self, session, *, scope, target_id):
        current = await self._rows(session, File, tuple(File.__table__.c.keys()), File.knowledge_id == target_id)
        original = scope["files"]
        if len(current) != len(original) or any(row["file_type"] != 0 for row in (*current, *original)):
            raise KnowledgeOperationPlanChangedError()
        mapping = {str(old["id"]): new["id"] for old, new in zip(original, current, strict=True)}
        for old, new in zip(original, current, strict=True):
            path = tuple(mapping[str(key)] for key in move_path_ids(old["file_level_path"]))
            if (
                new["file_name"] != old["file_name"]
                or new["file_level_path"] != ("/" + "/".join(map(str, path)) if path else "")
                or new["level"] != len(path)
            ):
                raise KnowledgeOperationPlanChangedError()
        return mapping

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

    async def aassert_item(self, session, snapshot):
        source, destination, before, copied = await self.aitem_facts(
            session,
            source_id=snapshot["source"]["id"],
            target_id=snapshot["destination"]["id"],
            source_file_id=snapshot["source_file"]["id"],
            target_file_id=snapshot["target_file"]["id"],
        )
        root_fields = (
            "id",
            "tenant_id",
            "user_id",
            "type",
            "model",
            "model_config_revision",
            "index_generation",
            "metadata_fields",
            "metadata_schema_revision",
            "index_name",
            "collection_name",
            "model_transition",
        )
        for current, expected in ((source, snapshot["source"]), (destination, snapshot["destination"])):
            actual = root_facts(current)
            if any(actual[key] != expected[key] for key in root_fields):
                raise KnowledgeOperationPlanChangedError()
        if source.state != 1 or destination.state != 2 or before != snapshot["source_file"]:
            raise KnowledgeOperationPlanChangedError()
        ignored = {"status", "update_time", "create_time", "updater_id"}
        if any(copied[key] != value for key, value in snapshot["target_file"].items() if key not in ignored):
            raise KnowledgeOperationPlanChangedError()
        for name in ("source_version", "target_version"):
            expected = snapshot[name]
            rows = await self._by_ids(session, Version, tuple(Version.__table__.c.keys()), (expected["id"],))
            if len(rows) != 1 or any(rows[0][key] != value for key, value in expected.items()):
                raise KnowledgeOperationPlanChangedError()
            docs = await self._by_ids(session, Document, DOC_FIELDS, (expected["document_id"],))
            root = source if name == "source_version" else destination
            if len(docs) != 1 or docs[0]["knowledge_id"] != root.id:
                raise KnowledgeOperationPlanChangedError()
        return source, destination

    async def acomplete_file(self, session, *, file_id, target_id, succeeded, user_metadata=None):
        from sqlalchemy import update

        values = {"status": 2 if succeeded else 3}
        if user_metadata is not None:
            values["user_metadata"] = user_metadata
        with session.no_autoflush, strict_tenant_filter():
            result = await session.execute(
                update(File)
                .where(
                    File.id == file_id,
                    File.tenant_id == get_current_tenant_id(),
                    File.knowledge_id == target_id,
                    File.file_type == 1,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )
        if result.rowcount != 1:
            raise KnowledgeOperationPlanChangedError()
        await session.flush()
