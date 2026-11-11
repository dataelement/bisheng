"""Exact existing physical files and version anchors for the old retry writer."""

from copy import deepcopy

from sqlalchemy import update
from sqlmodel import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, KnowledgeProcessingConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Document
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.repositories.knowledge_version_read_repository import KnowledgeVersionReadRepository
from bisheng.knowledge.domain.repositories.source_move_input_repository import SourceMoveInputRepository
from bisheng.knowledge.domain.services.knowledge_processing_guard import require_space_processing_idle
from bisheng.resource_reference.application.contracts import TransactionIdentity

_ROOT_FIELDS = (
    "id",
    "tenant_id",
    "type",
    "model",
    "model_config_revision",
    "index_generation",
    "model_transition",
    "state",
    "collection_name",
    "index_name",
)


def blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason="legacy_retry_" + reason)


def _path(value):
    if not value:
        return ()
    if type(value) is not str or not value.startswith("/"):
        blocked("invalid_parent")
    parts = value[1:].split("/")
    if any(
        not part.isascii() or not part.isdecimal() or str(int(part)) != part or not 0 < int(part) <= 2**63 - 1
        for part in parts
    ):
        blocked("invalid_parent")
    result = tuple(map(int, parts))
    if len(set(result)) != len(result):
        blocked("invalid_parent")
    return result


class LegacyRetryRepository:
    async def aread(self, session, *, space_id, file_ids, lock=False, allow_processing=False):
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
            blocked("tenant_required")
        transaction = TransactionIdentity.capture(session)

        def current():
            transaction.assert_current(session)
            if (
                get_current_tenant_id() != tenant
                or is_tenant_filter_bypassed()
                or session.new
                or session.dirty
                or session.deleted
            ):
                blocked("context_changed")

        async def query(statement):
            current()
            if lock:
                statement = statement.with_for_update().execution_options(populate_existing=True)
            with session.no_autoflush, strict_tenant_filter():
                rows = (await session.exec(statement)).all()
            current()
            return rows

        roots = await query(select(Knowledge).where(Knowledge.id == space_id))
        if len(roots) != 1 or roots[0].tenant_id != tenant or roots[0].type != 3:
            blocked("space_missing")
        root = roots[0]
        require_space_processing_idle(root, operation="legacy_retry")
        await SourceMoveInputRepository().arequire_released(session, space_id=space_id)
        current()
        files = {}
        for start in range(0, len(file_ids), 200):
            rows = await query(
                select(KnowledgeFile)
                .where(KnowledgeFile.id.in_(file_ids[start : start + 200]))
                .order_by(KnowledgeFile.id)
            )
            for row in rows:
                if row.tenant_id != tenant or row.knowledge_id != space_id or row.file_type != FileType.FILE.value:
                    blocked("file_scope_changed")
                if row.status in {1, 4, 5} and not allow_processing:
                    raise KnowledgeProcessingConflictError(reason="legacy_retry_file_busy")
                if row.status not in ({1, 2, 3, 4, 5, 6, 7} if allow_processing else {2, 3, 6, 7}):
                    blocked("file_state_invalid")
                files[row.id] = row.model_dump(mode="json")
        if set(files) != set(file_ids):
            blocked("file_missing")
        parent_ids = sorted({ident for row in files.values() for ident in _path(row["file_level_path"])})
        parents = {}
        for start in range(0, len(parent_ids), 200):
            for row in await query(
                select(KnowledgeFile)
                .where(KnowledgeFile.id.in_(parent_ids[start : start + 200]))
                .order_by(KnowledgeFile.id)
            ):
                if row.tenant_id != tenant or row.knowledge_id != space_id or row.file_type != FileType.DIR.value:
                    blocked("parent_scope_changed")
                parents[row.id] = row.model_dump(mode="json")
        for row in (*files.values(), *parents.values()):
            path = _path(row["file_level_path"])
            if row["level"] != len(path):
                blocked("invalid_parent")
            for index, ident in enumerate(path):
                if ident not in parents or _path(parents[ident]["file_level_path"]) != path[:index]:
                    blocked("parent_missing")
        versions, documents, stats = {}, {}, {}
        for start in range(0, len(file_ids), 200):
            rows = await query(
                select(Version).where(Version.knowledge_file_id.in_(file_ids[start : start + 200])).order_by(Version.id)
            )
            for row in rows:
                if row.knowledge_file_id in versions:
                    blocked("version_alias")
                versions[row.knowledge_file_id] = row.model_dump(mode="json")
        if set(versions) != set(files):
            blocked("version_missing")
        document_ids = sorted({row["document_id"] for row in versions.values()})
        for start in range(0, len(document_ids), 200):
            batch = document_ids[start : start + 200]
            rows = await query(select(Document).where(Document.id.in_(batch)).order_by(Document.id))
            with session.no_autoflush, strict_tenant_filter():
                grouped = await KnowledgeVersionReadRepository._stats(session, batch)
                current()
                await KnowledgeVersionReadRepository._check_links(session, batch, tenant, space_id)
            current()
            for row in rows:
                KnowledgeVersionReadRepository._check_document(row, grouped.get(row.id))
                if row.knowledge_id != space_id:
                    blocked("document_scope_changed")
                documents[row.id] = row.model_dump(mode="json")
            stats.update(grouped)
        for row in files.values():
            doc = documents.get(versions[row["id"]]["document_id"])
            if (
                doc is None
                or _path(doc["file_level_path"]) != _path(row["file_level_path"])
                or doc["level"] != row["level"]
            ):
                blocked("document_parent_changed")
        return {
            "root": {column.name: deepcopy(getattr(root, column.name)) for column in Knowledge.__table__.columns},
            "files": files,
            "parents": parents,
            "versions": versions,
            "documents": documents,
            "stats": stats,
        }

    @staticmethod
    def same(before, after):
        if any(before["root"][key] != after["root"][key] for key in _ROOT_FIELDS) or any(
            before[key] != after[key] for key in ("files", "parents", "versions", "documents", "stats")
        ):
            blocked("scope_changed")

    async def awrite(self, session, *, scope, patches, identity):
        transaction, tenant = TransactionIdentity.capture(session), get_current_tenant_id()
        result = []
        for ident, patch in patches.items():
            transaction.assert_current(session)
            if get_current_tenant_id() != tenant or is_tenant_filter_bypassed():
                blocked("context_changed")
            update_result = await session.exec(
                update(KnowledgeFile)
                .where(
                    KnowledgeFile.id == ident,
                    KnowledgeFile.tenant_id == tenant,
                    KnowledgeFile.knowledge_id == scope["root"]["id"],
                    KnowledgeFile.file_type == FileType.FILE.value,
                    KnowledgeFile.status == scope["files"][ident]["status"],
                )
                .values(
                    **patch,
                    status=5,
                    remark="",
                    similar_status=0,
                    simhash=None,
                    updater_id=identity.user_id,
                    updater_name=identity.user_name,
                )
            )
            transaction.assert_current(session)
            if get_current_tenant_id() != tenant or is_tenant_filter_bypassed() or update_result.rowcount != 1:
                blocked("file_changed")
            result.append(
                KnowledgeFile(
                    **{
                        **scope["files"][ident],
                        **patch,
                        "status": 5,
                        "remark": "",
                        "similar_status": 0,
                        "simhash": None,
                        "updater_id": identity.user_id,
                        "updater_name": identity.user_name,
                    }
                )
            )
        return result
