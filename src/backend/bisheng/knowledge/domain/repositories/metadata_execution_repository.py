"""Exact metadata execution reads and leased value writes in one caller TX."""

from copy import deepcopy
from dataclasses import dataclass, field

from sqlalchemy import inspect, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.repositories.metadata_processing_repository import (
    MetadataProcessingRepository,
    metadata_digest,
)
from bisheng.knowledge.domain.repositories.processing_job_repository import ProcessingJobRepository
from bisheng.knowledge.domain.schemas.processing_job import ResourceVersionTarget


@dataclass(frozen=True, slots=True)
class MetadataExecutionConfiguration:
    model_config_revision: int
    index_generation: str | None
    metadata_schema_revision: int
    metadata_schema_digest: str


@dataclass(frozen=True, slots=True)
class MetadataExecutionItem:
    target: ResourceVersionTarget
    parent_id: int | None
    original_status: int
    source_revision: str
    affected_fields: tuple[str, ...]
    after_values: dict | None = field(repr=False)


def _conflict(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"metadata_execution_{reason}")


class MetadataExecutionRepository:
    def __init__(self, *, jobs=None):
        self.jobs = jobs if jobs is not None else ProcessingJobRepository()

    @staticmethod
    def _context(session, space_id):
        if not isinstance(session, AsyncSession):
            raise TypeError("metadata execution requires the caller's native AsyncSession")
        tenant = get_current_tenant_id()
        if not session.in_transaction() or type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
            raise ResourceReferenceInvalidError(reason="metadata_execution_native_tenant_transaction_required")
        if type(space_id) is not int or space_id <= 0:
            raise SpaceNotFoundError()
        return tenant

    async def _configuration(self, session, space_id, *, lock=False):
        tenant = self._context(session, space_id)
        query = select(
            Knowledge.tenant_id,
            Knowledge.model_config_revision,
            Knowledge.index_generation,
            Knowledge.metadata_schema_revision,
            Knowledge.metadata_fields,
        ).where(Knowledge.id == space_id, Knowledge.type == KnowledgeTypeEnum.SPACE.value)
        if lock:
            query = query.with_for_update()
        with session.no_autoflush, strict_tenant_filter():
            row = (await session.execute(query)).one_or_none()
        if row is None or row.tenant_id != tenant:
            raise SpaceNotFoundError()
        schema = row.metadata_fields
        if schema is not None and (
            not isinstance(schema, list) or any(not isinstance(value, dict) for value in schema)
        ):
            _conflict("schema_invalid")
        if type(row.metadata_schema_revision) is not int or row.metadata_schema_revision < 0:
            _conflict("schema_revision_invalid")
        return MetadataExecutionConfiguration(
            row.model_config_revision, row.index_generation, row.metadata_schema_revision, metadata_digest(schema or [])
        )

    async def aread_configuration(self, session, space_id) -> MetadataExecutionConfiguration:
        return await self._configuration(session, space_id)

    async def aread_item(self, session, job, item) -> MetadataExecutionItem:
        tenant = self._context(session, job.space_id)
        configuration = await self.aread_configuration(session, job.space_id)
        job_table, item_table = KnowledgeProcessingJob.__table__, KnowledgeProcessingItem.__table__
        job_fields = (
            "id",
            "tenant_id",
            "space_id",
            "kind",
            "parameters",
            "expected_model_config_revision",
            "expected_index_generation",
        )
        query = (
            select(KnowledgeProcessingJob.id, *(job_table.c[name] for name in job_fields), *item_table.c)
            .select_from(KnowledgeProcessingJob)
            .join(item_table, item_table.c.job_id == job_table.c.id)
            .where(KnowledgeProcessingJob.id == job.id, item_table.c.id == item.id)
        )
        with session.no_autoflush, strict_tenant_filter():
            row = (await session.execute(query)).one_or_none()
        if row is None:
            _conflict("item_missing")
        saved_job = {name: row._mapping[job_table.c[name]] for name in job_fields}
        saved_item = {column.name: row._mapping[column] for column in item_table.c}
        if (
            saved_job["tenant_id"] != tenant
            or saved_item["tenant_id"] != tenant
            or saved_job["space_id"] != job.space_id
            or saved_item["expected_space_id"] != job.space_id
            or saved_job["kind"] != "metadata_schema_change"
        ):
            _conflict("item_scope_changed")
        parameters, snapshot = saved_job["parameters"], saved_item["processing_snapshot"]
        expected_keys = {
            "schema_version",
            "mode",
            "target",
            "parent_id",
            "source_revision",
            "before_values",
            "after_values",
            "before_values_digest",
            "after_values_digest",
            "original_status",
            "affected_fields",
        }
        try:
            if (
                not isinstance(parameters, dict)
                or not isinstance(snapshot, dict)
                or set(snapshot) != expected_keys
                or type(snapshot["schema_version"]) is not int
                or snapshot["schema_version"] != 1
                or snapshot["mode"] != "metadata_schema_change"
                or snapshot["original_status"] not in {2, 3, 6, 7}
                or not isinstance(parameters["after_schema"], list)
                or parameters["metadata_schema_revision"] != configuration.metadata_schema_revision
                or parameters["metadata_schema_digest"] != configuration.metadata_schema_digest
                or metadata_digest(parameters["after_schema"]) != configuration.metadata_schema_digest
                or saved_job["expected_model_config_revision"] != configuration.model_config_revision
                or saved_job["expected_index_generation"] != configuration.index_generation
            ):
                _conflict("configuration_or_snapshot_changed")
            target = ResourceVersionTarget(**{key: saved_item[key] for key in ("file_id", "document_id", "version_id")})
            if (
                snapshot["target"] != target.model_dump(mode="json")
                or snapshot["parent_id"] != saved_item["expected_parent_id"]
            ):
                _conflict("snapshot_target_changed")
            for key in ("before", "after"):
                values = snapshot[f"{key}_values"]
                if (values is not None and not isinstance(values, dict)) or metadata_digest(values) != snapshot[
                    f"{key}_values_digest"
                ]:
                    _conflict("snapshot_values_changed")
            affected = snapshot["affected_fields"]
            if (
                not isinstance(affected, list)
                or not affected
                or any(not isinstance(name, str) or not name for name in affected)
                or len(set(affected)) != len(affected)
            ):
                _conflict("affected_fields_invalid")
        except (KeyError, TypeError, ValueError) as error:
            raise KnowledgeOperationPlanConflictError(reason="metadata_execution_snapshot_invalid") from error
        physical, document, version = (
            KnowledgeFile.__table__,
            KnowledgeDocument.__table__,
            KnowledgeDocumentVersion.__table__,
        )
        primary = version.alias("metadata_primary_version")
        primary_file = physical.alias("metadata_primary_file")
        valid_primary = (
            select(primary.c.id)
            .select_from(primary)
            .join(primary_file, primary_file.c.id == primary.c.knowledge_file_id)
            .where(
                primary.c.id == document.c.primary_version_id,
                primary.c.document_id == document.c.id,
                primary.c.is_primary.is_(True),
                primary_file.c.knowledge_id == Knowledge.id,
                primary_file.c.tenant_id == Knowledge.tenant_id,
                primary_file.c.file_type == FileType.FILE.value,
            )
            .exists()
        )
        duplicate = version.alias("metadata_other_version")
        duplicate_file = (
            select(duplicate.c.id)
            .where(duplicate.c.knowledge_file_id == physical.c.id, duplicate.c.id != version.c.id)
            .exists()
        )
        query = (
            select(
                Knowledge.id,
                *physical.c,
                document.c.id,
                document.c.knowledge_id,
                document.c.primary_version_id,
                *version.c,
            )
            .select_from(Knowledge)
            .join(physical, physical.c.knowledge_id == Knowledge.id)
            .join(version, version.c.knowledge_file_id == physical.c.id)
            .join(document, document.c.id == version.c.document_id)
            .where(
                Knowledge.id == job.space_id,
                physical.c.id == target.file_id,
                document.c.id == target.document_id,
                version.c.id == target.version_id,
                valid_primary,
                ~duplicate_file,
            )
            .with_for_update()
        )
        with session.no_autoflush, strict_tenant_filter():
            row = (await session.execute(query)).one_or_none()
        if row is None:
            _conflict("physical_chain_changed")
        raw = {column.name: row._mapping[column] for column in physical.c}
        if (
            raw["tenant_id"] != tenant
            or raw["file_type"] != FileType.FILE.value
            or raw["status"] not in {2, 3, 6, 7}
            or row._mapping[document.c.knowledge_id] != job.space_id
            or row._mapping[version.c.version_no] <= 0
            or bool(row._mapping[version.c.is_primary])
            != (row._mapping[document.c.primary_version_id] == target.version_id)
            or MetadataProcessingRepository._parent(raw["file_level_path"]) != saved_item["expected_parent_id"]
        ):
            _conflict("physical_scope_changed")
        source = {
            key: raw[key]
            for key in (
                "id",
                "tenant_id",
                "knowledge_id",
                "file_type",
                "file_source",
                "object_name",
                "md5",
                "file_size",
                "file_name",
                "file_level_path",
            )
        }
        source.update(
            document_id=target.document_id, version_id=target.version_id, version_no=row._mapping[version.c.version_no]
        )
        if metadata_digest(source) != snapshot["source_revision"] or metadata_digest(raw["user_metadata"]) not in {
            snapshot["before_values_digest"],
            snapshot["after_values_digest"],
        }:
            _conflict("source_or_values_changed")
        return MetadataExecutionItem(
            target,
            saved_item["expected_parent_id"],
            snapshot["original_status"],
            snapshot["source_revision"],
            tuple(affected),
            deepcopy(snapshot["after_values"]),
        )

    @staticmethod
    async def _assert_no_pending_target_changes(session, job, item):
        pending = {id(row): row for collection in (session.new, session.dirty, session.deleted) for row in collection}
        if not pending:
            return
        primary_version, primary_file = None, None
        if any(
            isinstance(row, (KnowledgeFile, KnowledgeDocument, KnowledgeDocumentVersion)) for row in pending.values()
        ):
            # This exact document/primary PK read covers the shared chain of a
            # historical item without scanning its sibling versions or files.
            version = KnowledgeDocumentVersion.__table__
            query = (
                select(Knowledge.id, KnowledgeDocument.primary_version_id, version.c.knowledge_file_id)
                .select_from(Knowledge)
                .join(KnowledgeDocument, KnowledgeDocument.knowledge_id == Knowledge.id)
                .outerjoin(version, version.c.id == KnowledgeDocument.primary_version_id)
                .where(Knowledge.id == job.space_id, KnowledgeDocument.id == item.document_id)
            )
            with session.no_autoflush, strict_tenant_filter():
                row = (await session.execute(query)).one_or_none()
            if row is None:
                _conflict("physical_chain_changed")
            primary_version, primary_file = row.primary_version_id, row.knowledge_file_id
        ids = {
            Knowledge: {job.space_id},
            KnowledgeFile: {item.file_id, primary_file},
            KnowledgeDocument: {item.document_id},
            KnowledgeDocumentVersion: {item.version_id, primary_version},
            KnowledgeProcessingJob: {job.id},
            KnowledgeProcessingItem: {item.id},
        }
        critical = {
            Knowledge: {
                "id",
                "tenant_id",
                "type",
                "metadata_fields",
                "metadata_schema_revision",
                "model",
                "model_config_revision",
                "index_generation",
                "state",
                "model_transition",
                "index_name",
                "collection_name",
            },
            KnowledgeFile: {
                "id",
                "tenant_id",
                "knowledge_id",
                "file_type",
                "file_source",
                "object_name",
                "md5",
                "file_size",
                "file_name",
                "file_level_path",
                "status",
                "user_metadata",
            },
            KnowledgeDocument: {"id", "knowledge_id", "primary_version_id", "file_level_path", "level"},
            KnowledgeDocumentVersion: {"id", "document_id", "knowledge_file_id", "version_no", "is_primary"},
        }
        for row in pending.values():
            state = inspect(row)
            related = type(row) in ids and ids[type(row)].intersection((state.dict.get("id"), *(state.identity or ())))
            if isinstance(row, KnowledgeDocumentVersion):
                related = related or item.file_id in (
                    state.dict.get("knowledge_file_id"),
                    *state.attrs.knowledge_file_id.history.added,
                    *state.attrs.knowledge_file_id.history.deleted,
                )
            if related:
                fields = critical.get(type(row), state.attrs.keys())
                # A historical item relies on the primary's ownership chain,
                # while that primary's unrelated payload/remark stays caller-owned.
                if isinstance(row, KnowledgeFile) and item.file_id not in (
                    state.dict.get("id"),
                    *(state.identity or ()),
                ):
                    fields = {"id", "tenant_id", "knowledge_id", "file_type"}
                if (
                    row in session.new
                    or row in session.deleted
                    or any(state.attrs[name].history.has_changes() for name in fields)
                ):
                    _conflict("pending_target_change")

    async def awrite_values(self, session, job, item, *, lease) -> bool:
        self._context(session, job.space_id)
        await self._assert_no_pending_target_changes(session, job, item)
        configuration = await self._configuration(session, job.space_id, lock=True)
        with session.no_autoflush:
            guarded = await self.jobs._guard_item(session, lease, configuration)
        if guarded is None:
            return False
        actual_job, actual_item = guarded
        if actual_job.id != job.id or actual_item.id != item.id:
            _conflict("lease_target_changed")
        current = await self.aread_item(session, actual_job, actual_item)
        if not await self.jobs.acomplete_item(session, lease, configuration=configuration, succeeded=True):
            return False
        # Both SQL mutations belong to the original transaction. Completing
        # first ensures a rejected lease can never leave an uncompleted value
        # write; neither mutation is visible before the caller commits.
        result = await session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.id == current.target.file_id,
                KnowledgeFile.knowledge_id == actual_job.space_id,
                KnowledgeFile.tenant_id == actual_job.tenant_id,
            )
            .values(user_metadata=deepcopy(current.after_values))
        )
        if result.rowcount != 1:
            _conflict("file_write_lost")
        return True
