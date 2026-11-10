"""Initial upload SQL chains; the caller owns authorization, objects and commit.

Local receipts cover only this instance's initial upload chains. Explicit root
commit ACK permits fresh local rechecks of their original facts. This is neither
general file deletion authority nor recovery after losing the private registry.
"""

import math
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from weakref import WeakKeyDictionary, WeakSet

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Document
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import (
    KNOWLEDGE_FILE_NAME_MAX_LENGTH,
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.repositories.upload_commit_observer import UploadCommitObserver, root_transaction
from bisheng.resource_reference.application.contracts import TransactionIdentity


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"upload_registration_{reason}")


def _positive(value):
    return type(value) is int and value > 0


def _scope(session, *, clean=False):
    tenant = get_current_tenant_id()
    if not isinstance(session, AsyncSession) or not _positive(tenant) or is_tenant_filter_bypassed():
        _blocked("native_transaction_scope_required")
    try:
        TransactionIdentity.capture(session)
    except (TypeError, ValueError):
        _blocked("native_transaction_scope_required")
    # begin_nested flushes even with autoflush disabled. Reject before entering it.
    if clean and (session.new or session.dirty or session.deleted):
        _blocked("pending_caller_state")
    return tenant


def _same(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_same(value, right[key]) for key, value in left.items())
    if type(left) is list:
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def _json(value):
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _json(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _json(item)
        return
    _blocked("invalid_metadata")


@dataclass(frozen=True, slots=True)
class NewUploadFile:
    file_name: str
    file_size: int
    md5: str | None
    split_rule: str | None = field(repr=False)
    file_source: str | None
    user_metadata: dict | None = field(repr=False)
    user_id: int
    user_name: str | None
    updater_id: int
    updater_name: str | None


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class RegisteredUpload:
    file: KnowledgeFile = field(repr=False)
    document_id: int
    version_id: int


@dataclass(frozen=True, slots=True, repr=False)
class _Issued:
    transaction: TransactionIdentity
    tenant: int
    parent_id: int | None
    file: KnowledgeFile
    facts: tuple[dict, dict, dict]
    initial: bool = True


def _input(value):
    if type(value) is not NewUploadFile:
        _blocked("invalid_file_input")
    if (
        type(value.file_name) is not str
        or not value.file_name
        or len(value.file_name) > KNOWLEDGE_FILE_NAME_MAX_LENGTH
        or type(value.file_size) is not int
        or value.file_size < 0
        or not _positive(value.user_id)
        or not _positive(value.updater_id)
        or any(
            item is not None and type(item) is not str
            for item in (value.md5, value.split_rule, value.file_source, value.user_name, value.updater_name)
        )
        or (value.user_metadata is not None and type(value.user_metadata) is not dict)
    ):
        _blocked("invalid_file_input")
    _json(value.user_metadata)
    return {item.name: deepcopy(getattr(value, item.name)) for item in value.__dataclass_fields__.values()}


def _path(value):
    if value in (None, ""):
        return ()
    if type(value) is not str or not re.fullmatch(r"(?:/[1-9][0-9]*)+", value):
        _blocked("invalid_folder_path")
    result = tuple(int(part) for part in value[1:].split("/"))
    if len(set(result)) != len(result):
        _blocked("cyclic_folder_path")
    return result


class UploadRegistrationRepository:
    def __init__(self):
        self._issued = WeakKeyDictionary()
        self._commits, self._acknowledged = UploadCommitObserver(), WeakSet()

    async def alock_space_for_upload(self, session: AsyncSession, *, space_id: int) -> Knowledge:
        tenant = _scope(session, clean=True)
        if not _positive(space_id):
            _blocked("invalid_location")
        rows = await self._read(
            session, sa.select(Knowledge.__table__).where(Knowledge.id == space_id, Knowledge.tenant_id == tenant)
        )
        if len(rows) != 1 or rows[0]["type"] != 3:
            _blocked("space_missing_or_changed")
        return Knowledge(**deepcopy(rows[0]))

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

    async def _locations(self, session, keys):
        tenant = _scope(session)
        spaces = tuple(dict.fromkeys(space for space, _ in keys))
        roots = await self._read(
            session, sa.select(Knowledge.id, Knowledge.type, Knowledge.tenant_id).where(Knowledge.id.in_(spaces))
        )
        if len(roots) != len(spaces) or any(row["tenant_id"] != tenant or row["type"] != 3 for row in roots):
            _blocked("space_missing_or_changed")
        parents = tuple(dict.fromkeys(parent for _, parent in keys if parent is not None))
        columns = tuple(
            getattr(KnowledgeFile, name)
            for name in ("id", "knowledge_id", "tenant_id", "file_type", "file_level_path", "level")
        )

        async def folders(ids):
            result = {}
            for offset in range(0, len(ids), 200):
                rows = await self._read(
                    session, sa.select(*columns).where(KnowledgeFile.id.in_(ids[offset : offset + 200]))
                )
                result.update((row["id"], row) for row in rows)
            return result

        nodes = await folders(parents)
        if len(nodes) != len(parents):
            _blocked("parent_missing")
        paths = {key: _path(row["file_level_path"]) for key, row in nodes.items()}
        ancestor_ids = tuple(dict.fromkeys(key for path in paths.values() for key in path if key not in nodes))
        nodes.update(await folders(ancestor_ids))
        if any(key not in nodes for key in ancestor_ids):
            _blocked("ancestor_missing")
        # Validate unique ancestors once. Historical deep but consistent paths are legal.
        paths = {key: _path(row["file_level_path"]) for key, row in nodes.items()}
        for key, row in nodes.items():
            path = paths[key]
            if (
                row["tenant_id"] != tenant
                or row["file_type"] != FileType.DIR.value
                or type(row["level"]) is not int
                or row["level"] != len(path)
                or key in path
            ):
                _blocked("invalid_parent")
            if path:
                item = nodes.get(path[-1])
                if item is None or item["knowledge_id"] != row["knowledge_id"] or paths[item["id"]] != path[:-1]:
                    _blocked("broken_ancestor_chain")
        result = {}
        for space, parent in keys:
            if parent is None:
                result[(space, parent)] = ("", 0)
            else:
                row = nodes[parent]
                if row["knowledge_id"] != space:
                    _blocked("parent_space_mismatch")
                path = paths[parent] + (parent,)
                result[(space, parent)] = ("/" + "/".join(map(str, path)), len(path))
        return result

    async def _facts(self, session, ids):
        """Read whole current chains, including extra versions/primary aliases."""
        files, documents, versions = zip(*ids, strict=True)
        native_files = await self._read(
            session,
            sa.select(KnowledgeFile.__table__).where(
                KnowledgeFile.id.in_(files), KnowledgeFile.tenant_id == _scope(session)
            ),
        )
        native_docs = await self._read(
            session,
            sa.select(Document.__table__).where(
                sa.or_(Document.id.in_(documents), Document.primary_version_id.in_(versions))
            ),
        )
        native_versions = await self._read(
            session,
            sa.select(Version.__table__).where(
                sa.or_(Version.document_id.in_(documents), Version.knowledge_file_id.in_(files))
            ),
        )
        maps = tuple({row["id"]: row for row in rows} for rows in (native_files, native_docs, native_versions))
        if any(len(rows) != len(ids) for rows in (native_files, native_docs, native_versions)):
            _blocked("chain_not_independent")
        result = []
        for file_id, doc_id, version_id in ids:
            file, doc, version = (
                mapping.get(key) for mapping, key in zip(maps, (file_id, doc_id, version_id), strict=True)
            )
            if (
                file is None
                or doc is None
                or version is None
                or file["file_type"] != FileType.FILE.value
                or file["status"] != KnowledgeFileStatus.WAITING.value
                or doc["knowledge_id"] != file["knowledge_id"]
                or (doc["file_level_path"], doc["level"]) != (file["file_level_path"], file["level"])
                or doc["primary_version_id"] != version_id
                or version["document_id"] != doc_id
                or version["knowledge_file_id"] != file_id
                or version["version_no"] != 1
                or version["is_primary"] is not True
                or any(
                    type(row[name]) is not datetime
                    for row in (file, doc, version)
                    for name in ("create_time", "update_time")
                )
            ):
                _blocked("initial_chain_changed")
            result.append(deepcopy((file, doc, version)))
        return tuple(result)

    @staticmethod
    def _receipt(facts):
        file, doc, version = facts
        return RegisteredUpload(KnowledgeFile(**deepcopy(file)), doc["id"], version["id"])

    def _original(self, receipt):
        issued = self._issued.get(receipt) if type(receipt) is RegisteredUpload else None
        if issued is None or receipt.file is not issued.file:
            _blocked("unissued_receipt")
        if (
            not _positive(receipt.document_id)
            or not _positive(receipt.version_id)
            or not _same(receipt.file.model_dump(mode="python"), issued.facts[0])
            or receipt.document_id != issued.facts[1]["id"]
            or receipt.version_id != issued.facts[2]["id"]
        ):
            _blocked("receipt_changed")
        return issued

    def _claim(self, session, receipt):
        tenant = _scope(session, clean=True)
        issued = self._original(receipt)
        if issued.tenant != tenant:
            _blocked("receipt_scope_changed")
        try:
            issued.transaction.assert_current(session)
        except (TypeError, ValueError):
            _blocked("receipt_transaction_changed")
        return issued

    def _acknowledge_committed_initial(self, *, registrations: tuple[RegisteredUpload, ...]) -> None:
        tenant = get_current_tenant_id()
        if (
            not _positive(tenant)
            or is_tenant_filter_bypassed()
            or type(registrations) is not tuple
            or len(registrations) > 200
        ):
            _blocked("invalid_acknowledgement")
        transactions = []
        for receipt in registrations:
            issued = self._original(receipt)
            if not issued.initial or issued.tenant != tenant:
                _blocked("original_root_commit_required")
            transactions.append(issued.transaction)
        self._commits.acknowledge(tuple(transactions))
        self._acknowledged.update(registrations)

    async def _arebind_committed_initial(
        self, session: AsyncSession, *, registration: RegisteredUpload
    ) -> RegisteredUpload:
        tenant = _scope(session, clean=True)
        issued = self._original(registration)
        if (
            registration not in self._acknowledged
            or issued.tenant != tenant
            or issued.transaction.session is session
            or root_transaction(issued.transaction.transaction).is_active
        ):
            _blocked("acknowledged_original_required")
        (facts,) = await self._current(session, (registration,), (issued,))
        receipt = self._receipt(facts)
        self._issued[receipt] = _Issued(
            TransactionIdentity.capture(session), tenant, issued.parent_id, receipt.file, facts, False
        )
        return receipt

    async def _current(self, session, receipts, issued):
        keys = tuple(dict.fromkeys((item.facts[0]["knowledge_id"], item.parent_id) for item in issued))
        locations = await self._locations(session, keys)
        ids = tuple((item.file.id, item.document_id, item.version_id) for item in receipts)
        facts = await self._facts(session, ids)
        for current, original in zip(facts, issued, strict=True):
            file = current[0]
            if (
                not all(_same(a, b) for a, b in zip(current, original.facts, strict=True))
                or (file["file_level_path"], file["level"]) != locations[(file["knowledge_id"], original.parent_id)]
            ):
                _blocked("current_chain_changed")
        return facts

    async def aregister_initial(
        self, session: AsyncSession, *, space_id: int, parent_id: int | None, files: tuple[NewUploadFile, ...]
    ) -> tuple[RegisteredUpload, ...]:
        tenant = _scope(session, clean=True)
        if not _positive(space_id) or (parent_id is not None and not _positive(parent_id)):
            _blocked("invalid_location")
        if type(files) is not tuple or len(files) > 200:
            _blocked("invalid_batch")
        values = tuple(_input(value) for value in files)
        if not values:
            return ()
        transaction = TransactionIdentity.capture(session)
        self._commits.observe(transaction)
        try:
            async with session.begin_nested():
                (path, level) = (await self._locations(session, ((space_id, parent_id),)))[(space_id, parent_id)]
                rows = [
                    KnowledgeFile(**value, knowledge_id=space_id, tenant_id=tenant, file_level_path=path, level=level)
                    for value in values
                ]
                expected_files = [deepcopy(row.model_dump(mode="python")) for row in rows]
                session.add_all(rows)
                await session.flush()
                docs = [Document(knowledge_id=space_id, file_level_path=path, level=level) for _ in rows]
                session.add_all(docs)
                await session.flush()
                versions = [
                    Version(document_id=doc.id, knowledge_file_id=row.id, version_no=1, is_primary=True)
                    for row, doc in zip(rows, docs, strict=True)
                ]
                session.add_all(versions)
                await session.flush()
                doc_times = await self._read(
                    session,
                    sa.select(Document.id, Document.update_time).where(Document.id.in_(tuple(doc.id for doc in docs))),
                )
                times = {row["id"]: row["update_time"] for row in doc_times}
                await session.execute(
                    sa.update(Document.__table__)
                    .where(Document.id == sa.bindparam("original_id"))
                    .values(primary_version_id=sa.bindparam("primary_id"), update_time=sa.bindparam("original_time")),
                    [
                        {"original_id": doc.id, "primary_id": version.id, "original_time": times[doc.id]}
                        for doc, version in zip(docs, versions, strict=True)
                    ],
                )
                facts = await self._facts(
                    session,
                    tuple((row.id, doc.id, version.id) for row, doc, version in zip(rows, docs, versions, strict=True)),
                )
                for actual, expected in zip(facts, expected_files, strict=True):
                    if any(
                        not _same(actual[0][key], value)
                        for key, value in expected.items()
                        if key not in {"id", "create_time", "update_time"}
                    ):
                        _blocked("registered_file_changed")
                receipts = tuple(self._receipt(item) for item in facts)
        except SQLAlchemyError as error:
            raise KnowledgeOperationPlanConflictError(reason="upload_registration_write_failed") from error
        transaction.assert_current(session)
        for receipt, fact in zip(receipts, facts, strict=True):
            self._issued[receipt] = _Issued(transaction, tenant, parent_id, receipt.file, fact)
        return receipts

    async def areserve_object_key(
        self, session: AsyncSession, *, registration: RegisteredUpload, object_name: str
    ) -> RegisteredUpload:
        issued = self._claim(session, registration)
        if issued.facts[0]["object_name"] not in (None, ""):
            _blocked("object_key_already_reserved")
        return await self.aset_materialized(session, registration=registration, object_name=object_name)

    async def aset_materialized(
        self,
        session: AsyncSession,
        *,
        registration: RegisteredUpload,
        object_name: str,
        user_metadata: dict | None = None,
    ) -> RegisteredUpload:
        issued = self._claim(session, registration)
        if (
            type(object_name) is not str
            or not object_name
            or (user_metadata is not None and type(user_metadata) is not dict)
        ):
            _blocked("invalid_materialization")
        _json(user_metadata)
        metadata = deepcopy(user_metadata)
        try:
            async with session.begin_nested():
                (facts,) = await self._current(session, (registration,), (issued,))
                changes = {"object_name": object_name, "update_time": facts[0]["update_time"]}
                if metadata is not None:
                    changes["user_metadata"] = metadata
                await session.execute(
                    sa.update(KnowledgeFile.__table__)
                    .where(KnowledgeFile.id == registration.file.id, KnowledgeFile.tenant_id == issued.tenant)
                    .values(**changes)
                )
                (current,) = await self._facts(
                    session, ((registration.file.id, registration.document_id, registration.version_id),)
                )
                expected = deepcopy(facts)
                expected[0].update(changes)
                # Initial File registration accepts its real DB updater time;
                # every other File/Doc/V1 fact remains exact, including create_time.
                expected[0]["update_time"] = current[0]["update_time"]
                if not all(_same(a, b) for a, b in zip(current, expected, strict=True)):
                    _blocked("materialized_chain_changed")
                receipt = self._receipt(current)
        except SQLAlchemyError as error:
            raise KnowledgeOperationPlanConflictError(reason="upload_registration_materialization_failed") from error
        self._issued[receipt] = _Issued(
            issued.transaction, issued.tenant, issued.parent_id, receipt.file, current, issued.initial
        )
        del self._issued[registration]
        return receipt

    async def arollback_created(self, session: AsyncSession, *, registrations: tuple[RegisteredUpload, ...]) -> None:
        _scope(session, clean=True)
        if type(registrations) is not tuple or len(registrations) > 200:
            _blocked("invalid_batch")
        if not registrations:
            return
        issued = tuple(self._claim(session, item) for item in registrations)
        if len(set(registrations)) != len(registrations):
            _blocked("duplicate_receipt")
        try:
            async with session.begin_nested():
                await self._current(session, registrations, issued)
                for model, ids in (
                    (Version, tuple(item.version_id for item in registrations)),
                    (Document, tuple(item.document_id for item in registrations)),
                    (KnowledgeFile, tuple(item.file.id for item in registrations)),
                ):
                    statement = sa.delete(model.__table__).where(model.id.in_(ids))
                    if model is KnowledgeFile:
                        statement = statement.where(KnowledgeFile.tenant_id == _scope(session))
                    await session.execute(statement)
                    if await self._read(session, sa.select(model.id).where(model.id.in_(ids))):
                        _blocked("cleanup_incomplete")
        except SQLAlchemyError as error:
            raise KnowledgeOperationPlanConflictError(reason="upload_registration_cleanup_failed") from error
        for receipt in registrations:
            del self._issued[receipt]
