"""Bounded move reads anchored to the actual owned Root, preserving broken child facts."""

from copy import deepcopy

from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.core.database.dialect_helpers import StrJoinKey
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.schemas.move_processing import DOC_FIELDS, FILE_FIELDS, VERSION_FIELDS, move_path_ids
from bisheng.resource_reference.application.contracts import TransactionIdentity

PAGE = 200
STRING_KEYS = (KnowledgeProcessingJob, KnowledgeProcessingItem, KnowledgeOperationPlan)


def _conflict():
    raise KnowledgeOperationPlanConflictError(reason="move_owned_row_chain_invalid")


class MoveRowRepository:
    @staticmethod
    def _owned_query(model, fields, *, via):
        root, file = Knowledge.__table__, KnowledgeFile.__table__
        doc, job = KnowledgeDocument.__table__, KnowledgeProcessingJob.__table__
        table = model.__table__
        checks = [Knowledge.tenant_id]
        condition = None
        if model in (KnowledgeFile, KnowledgeDocument):
            joined = root.join(table, table.c.knowledge_id == root.c.id)
        elif model is KnowledgeDocumentVersion:
            if via == "document_id":
                joined = root.join(doc, doc.c.knowledge_id == root.c.id).join(table, table.c.document_id == doc.c.id)
            else:
                joined = root.join(file, file.c.knowledge_id == root.c.id).join(
                    table, table.c.knowledge_file_id == file.c.id
                )
                checks.append(file.c.tenant_id)
        elif model is TagLink:
            joined = root.join(file, file.c.knowledge_id == root.c.id).join(
                table, table.c.resource_id == StrJoinKey(file.c.id)
            )
            checks.append(file.c.tenant_id)
            condition = table.c.resource_type == ResourceTypeEnum.SPACE_FILE.value
        elif model in (KnowledgeProcessingJob, KnowledgeOperationPlan):
            joined = root.join(table, table.c.space_id == root.c.id)
        elif model is KnowledgeProcessingItem:
            joined = root.join(job, job.c.space_id == root.c.id).join(table, table.c.job_id == job.c.id)
            checks.append(job.c.tenant_id)
        else:
            raise TypeError("unsupported move row model")
        if "tenant_id" in table.c:
            checks.append(table.c.tenant_id)
        # ORM Root is the C3 owner. Raw children must not be independently
        # filtered, or a malformed descendant could disappear from the manifest.
        query = select(Knowledge.id, *checks, *(table.c[name] for name in fields)).select_from(joined)
        return query.where(condition) if condition is not None else query, len(checks) + 1

    @classmethod
    async def _rows(cls, session, model, fields, condition, *, lock=False, via="id"):
        if not isinstance(session, (Session, AsyncSession)):
            raise TypeError("move requires the caller native session")
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
            raise ResourceReferenceInvalidError(reason="move_concrete_tenant_required")
        table, result = model.__table__, []
        if "id" not in fields:
            raise ValueError("move row projection requires its real primary key")
        query, prefix = cls._owned_query(model, fields, via=via)
        cursor = "" if model in STRING_KEYS else 0
        with session.no_autoflush, strict_tenant_filter():
            while True:
                page = query.where(condition, table.c.id > cursor).order_by(table.c.id).limit(PAGE)
                rows = (await session.execute(page)).all()
                if any(any(value != tenant for value in row[1:prefix]) for row in rows):
                    _conflict()
                values = [deepcopy(dict(zip(fields, row[prefix:], strict=True))) for row in rows]
                if lock and values:
                    # Roots are locked by the caller in ascending order. Lock
                    # only these child PKs so a join cannot acquire new Roots
                    # out of order; compare both reads before returning facts.
                    locked = (
                        (
                            await session.execute(
                                select(*(table.c[name] for name in fields))
                                .where(table.c.id.in_([row["id"] for row in values]))
                                .order_by(table.c.id)
                                .limit(PAGE)
                                .with_for_update()
                            )
                        )
                        .mappings()
                        .all()
                    )
                    if [dict(row) for row in locked] != values:
                        _conflict()
                result.extend(values)
                if len(rows) < PAGE:
                    return result
                cursor = values[-1]["id"]

    async def _by_ids(self, session, model, fields, ids, *, lock=False, key="id"):
        result, keys = [], sorted(set(ids))
        for offset in range(0, len(keys), PAGE):
            condition = model.__table__.c[key].in_(keys[offset : offset + PAGE])
            result += await self._rows(session, model, fields, condition, lock=lock, via=key)
        return result

    async def aread_move_target(self, session, *, target, expected_path):
        """Point-read one target and its primary/ancestors, never its sibling chain."""
        tenant, transaction = get_current_tenant_id(), TransactionIdentity.capture(session)

        def check():
            if (
                type(tenant) is not int
                or tenant <= 0
                or get_current_tenant_id() != tenant
                or is_tenant_filter_bypassed()
            ):
                _conflict()
            transaction.assert_current(session)

        check()
        doc, version = KnowledgeDocument.__table__, KnowledgeDocumentVersion.__table__
        with session.no_autoflush, strict_tenant_filter():
            header = (
                await session.execute(
                    select(doc.c.primary_version_id, version.c.knowledge_file_id)
                    .select_from(doc.outerjoin(version, version.c.id == doc.c.primary_version_id))
                    .where(doc.c.id == target.document_id)
                )
            ).one_or_none()
        check()
        if header is None or type(header.knowledge_file_id) is not int:
            _conflict()
        ancestors = move_path_ids(expected_path)
        files = {
            row["id"]: row
            for row in await self._by_ids(
                session,
                KnowledgeFile,
                FILE_FIELDS,
                (*ancestors, target.file_id, header.knowledge_file_id),
                lock=True,
            )
        }
        check()
        documents = await self._by_ids(session, KnowledgeDocument, DOC_FIELDS, (target.document_id,), lock=True)
        check()
        versions = {
            row["id"]: row
            for row in await self._by_ids(
                session,
                KnowledgeDocumentVersion,
                VERSION_FIELDS,
                (target.version_id, header.primary_version_id),
                lock=True,
            )
        }
        check()
        with session.no_autoflush, strict_tenant_filter():
            linked = (
                (
                    await session.execute(
                        select(version.c.id)
                        .where(version.c.knowledge_file_id == target.file_id)
                        .order_by(version.c.id)
                        .limit(2)
                    )
                )
                .scalars()
                .all()
            )
        check()
        if (
            len(documents) != 1
            or target.file_id not in files
            or header.knowledge_file_id not in files
            or target.version_id not in versions
            or header.primary_version_id not in versions
            or documents[0]["primary_version_id"] != header.primary_version_id
            or linked != [target.version_id]
            or any(key not in files for key in ancestors)
        ):
            _conflict()
        primary = versions[header.primary_version_id]
        if (
            primary["document_id"] != target.document_id
            or not primary["is_primary"]
            or primary["knowledge_file_id"] != header.knowledge_file_id
        ):
            _conflict()
        return (
            files[target.file_id],
            documents[0],
            versions[target.version_id],
            primary,
            files[header.knowledge_file_id],
            tuple(files[key] for key in ancestors),
        )
