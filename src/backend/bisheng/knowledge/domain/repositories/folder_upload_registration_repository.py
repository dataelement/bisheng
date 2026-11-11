"""Only this instance's acknowledged, unchanged empty upload folders may unwind."""

from copy import deepcopy
from dataclasses import dataclass, field
from weakref import WeakKeyDictionary

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Document
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import KNOWLEDGE_FILE_NAME_MAX_LENGTH, KnowledgeFile
from bisheng.knowledge.domain.repositories.upload_commit_observer import UploadCommitObserver, root_transaction
from bisheng.knowledge.domain.repositories.upload_registration_repository import _path, _positive, _same, _scope
from bisheng.resource_reference.application.contracts import TransactionIdentity


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason="folder_upload_registration_" + reason)


@dataclass(frozen=True, slots=True)
class NewUploadFolder:
    name: str
    user_id: int
    user_name: str | None
    updater_id: int
    updater_name: str | None


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class StagedUploadFolder:
    file: KnowledgeFile = field(repr=False)


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class OwnedUploadFolder:
    file: KnowledgeFile = field(repr=False)


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class _LocalFolder:
    file: KnowledgeFile = field(repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class _Issued:
    transaction: TransactionIdentity
    tenant: int
    parent_id: int | None
    file: KnowledgeFile
    facts: dict


class FolderUploadRegistrationRepository:
    def __init__(self):
        self._staged, self._owned, self._locals = WeakKeyDictionary(), WeakKeyDictionary(), WeakKeyDictionary()
        self._commits = UploadCommitObserver()

    @staticmethod
    async def _read(session, statement):
        tenant = _scope(session)
        transaction = TransactionIdentity.capture(session)
        with session.no_autoflush, strict_tenant_filter():
            rows = tuple(dict(row) for row in (await session.execute(statement.with_for_update())).mappings())
        if _scope(session) != tenant:
            _blocked("scope_changed")
        transaction.assert_current(session)
        return rows

    async def _location(self, session, space_id, parent_id):
        tenant = _scope(session)
        roots = await self._read(
            session,
            sa.select(Knowledge.id, Knowledge.tenant_id, Knowledge.type).where(
                Knowledge.id == space_id, Knowledge.tenant_id == tenant
            ),
        )
        if len(roots) != 1 or roots[0]["type"] != 3:
            _blocked("invalid_space")
        if parent_id is None:
            return "", 0
        columns = tuple(
            getattr(KnowledgeFile, name)
            for name in ("id", "tenant_id", "knowledge_id", "file_type", "file_level_path", "level")
        )
        nodes = await self._read(session, sa.select(*columns).where(KnowledgeFile.id == parent_id))
        if len(nodes) != 1:
            _blocked("missing_parent")
        path = _path(nodes[0]["file_level_path"])
        if path:
            nodes += await self._read(
                session, sa.select(*columns).where(KnowledgeFile.id.in_(path)).order_by(KnowledgeFile.id)
            )
        by_id = {row["id"]: row for row in nodes}
        if set(by_id) != {*path, parent_id}:
            _blocked("missing_ancestor")
        for index, ident in enumerate((*path, parent_id)):
            node = by_id[ident]
            if (
                node["tenant_id"] != tenant
                or node["knowledge_id"] != space_id
                or node["file_type"] != 0
                or type(node["level"]) is not int
                or node["level"] != index
                or _path(node["file_level_path"]) != path[:index]
            ):
                _blocked("changed_parent_chain")
        return "/" + "/".join(map(str, (*path, parent_id))), len(path) + 1

    async def aregister_folder(
        self, session: AsyncSession, *, space_id: int, parent_id: int | None, folder: NewUploadFolder
    ) -> StagedUploadFolder:
        tenant = _scope(session, clean=True)
        if not _positive(space_id) or (parent_id is not None and not _positive(parent_id)):
            _blocked("invalid_location")
        if (
            type(folder) is not NewUploadFolder
            or type(folder.name) is not str
            or not folder.name
            or len(folder.name) > KNOWLEDGE_FILE_NAME_MAX_LENGTH
            or not _positive(folder.user_id)
            or not _positive(folder.updater_id)
            or any(value is not None and type(value) is not str for value in (folder.user_name, folder.updater_name))
        ):
            _blocked("invalid_folder")
        transaction = TransactionIdentity.capture(session)
        self._commits.observe(transaction)
        try:
            async with session.begin_nested():
                path, level = await self._location(session, space_id, parent_id)
                row = KnowledgeFile(
                    knowledge_id=space_id,
                    tenant_id=tenant,
                    file_type=0,
                    status=2,
                    file_name=folder.name,
                    file_level_path=path,
                    level=level,
                    user_id=folder.user_id,
                    user_name=folder.user_name,
                    updater_id=folder.updater_id,
                    updater_name=folder.updater_name,
                )
                expected = deepcopy(row.model_dump(mode="python"))
                session.add(row)
                await session.flush()
                rows = await self._read(
                    session,
                    sa.select(KnowledgeFile.__table__).where(
                        KnowledgeFile.id == row.id, KnowledgeFile.tenant_id == tenant
                    ),
                )
                if len(rows) != 1 or any(
                    not _same(rows[0][name], value)
                    for name, value in expected.items()
                    if name not in {"id", "create_time", "update_time"}
                ):
                    _blocked("inserted_folder_changed")
                facts = deepcopy(rows[0])
        except SQLAlchemyError as error:
            raise KnowledgeOperationPlanConflictError(reason="folder_upload_registration_write_failed") from error
        transaction.assert_current(session)
        receipt = StagedUploadFolder(KnowledgeFile(**deepcopy(facts)))
        self._staged[receipt] = _Issued(transaction, tenant, parent_id, receipt.file, facts)
        return receipt

    @staticmethod
    def _original(receipt, kind, registry):
        issued = registry.get(receipt) if type(receipt) is kind else None
        if (
            issued is None
            or receipt.file is not issued.file
            or not _same(receipt.file.model_dump(mode="python"), issued.facts)
        ):
            _blocked("unissued_or_changed_receipt")
        return issued

    def _acknowledge_committed_folder(self, *, registration: StagedUploadFolder) -> OwnedUploadFolder:
        issued = self._original(registration, StagedUploadFolder, self._staged)
        if (
            issued.tenant != get_current_tenant_id()
            or type(get_current_tenant_id()) is not int
            or is_tenant_filter_bypassed()
        ):
            _blocked("acknowledgement_scope")
        self._commits.acknowledge((issued.transaction,))
        owned = OwnedUploadFolder(KnowledgeFile(**deepcopy(issued.facts)))
        self._owned[owned] = _Issued(issued.transaction, issued.tenant, issued.parent_id, owned.file, issued.facts)
        del self._staged[registration]
        return owned

    @staticmethod
    def _descendant(column, prefix):
        escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return sa.or_(column == prefix, column.like(escaped + "/%", escape="\\"))

    async def _empty(self, session, issued):
        row = issued.facts
        prefix = f"{row['file_level_path'] or ''}/{row['id']}"
        # Boolean relationship probes for an already proven owned global folder
        # ID must not hide bad/foreign child links with a status filter or JOIN.
        for model, predicate in (
            (KnowledgeFile, self._descendant(KnowledgeFile.file_level_path, prefix)),
            (Document, self._descendant(Document.file_level_path, prefix)),
            (Version, Version.knowledge_file_id == row["id"]),
        ):
            table = model.__table__
            if await self._read(session, sa.select(table.c.id).where(predicate).limit(1)):
                _blocked("folder_not_empty_or_linked")

    async def _current(self, session, issued):
        path, level = await self._location(session, issued.facts["knowledge_id"], issued.parent_id)
        rows = await self._read(
            session,
            sa.select(KnowledgeFile.__table__).where(
                KnowledgeFile.id == issued.facts["id"], KnowledgeFile.tenant_id == issued.tenant
            ),
        )
        if (
            len(rows) != 1
            or not _same(rows[0], issued.facts)
            or (rows[0]["file_level_path"], rows[0]["level"]) != (path, level)
        ):
            _blocked("current_folder_changed")
        await self._empty(session, issued)

    async def _arebind_owned_empty_folder(
        self, session: AsyncSession, *, registration: OwnedUploadFolder
    ) -> _LocalFolder:
        tenant = _scope(session, clean=True)
        issued = self._original(registration, OwnedUploadFolder, self._owned)
        if (
            issued.tenant != tenant
            or issued.transaction.session is session
            or root_transaction(issued.transaction.transaction).is_active
        ):
            _blocked("fresh_owned_transaction_required")
        await self._current(session, issued)
        receipt = _LocalFolder(KnowledgeFile(**deepcopy(issued.facts)))
        self._locals[receipt] = _Issued(
            TransactionIdentity.capture(session), tenant, issued.parent_id, receipt.file, issued.facts
        )
        return receipt

    async def arollback_created_empty(self, session: AsyncSession, *, receipt: _LocalFolder) -> None:
        tenant = _scope(session, clean=True)
        issued = self._original(receipt, _LocalFolder, self._locals)
        if issued.tenant != tenant:
            _blocked("local_scope_changed")
        try:
            issued.transaction.assert_current(session)
        except (TypeError, ValueError) as error:
            raise KnowledgeOperationPlanConflictError(
                reason="folder_upload_registration_local_transaction_changed"
            ) from error
        try:
            async with session.begin_nested():
                await self._current(session, issued)
                await session.execute(
                    sa.delete(KnowledgeFile.__table__).where(
                        KnowledgeFile.id == issued.facts["id"],
                        KnowledgeFile.tenant_id == tenant,
                        KnowledgeFile.knowledge_id == issued.facts["knowledge_id"],
                        KnowledgeFile.file_type == 0,
                    )
                )
                if await self._read(session, sa.select(KnowledgeFile.id).where(KnowledgeFile.id == issued.facts["id"])):
                    _blocked("cleanup_incomplete")
        except SQLAlchemyError as error:
            raise KnowledgeOperationPlanConflictError(reason="folder_upload_registration_cleanup_failed") from error
        del self._locals[receipt]
