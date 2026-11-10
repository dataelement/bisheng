"""SQL-only version mutations under privately issued, same-transaction locks.

No authorization is granted here. Callers own business admission and the only
commit. Core projections/writes leave their ORM identity map and pending intact.
"""

from dataclasses import dataclass, fields
from weakref import WeakKeyDictionary

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Document
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.resource_reference.application.contracts import TransactionIdentity


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"version_mutation_{reason}")


def _scope(session):
    tenant = get_current_tenant_id()
    if not isinstance(session, AsyncSession) or type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
        _blocked("native_scope_required")
    try:
        return tenant, TransactionIdentity.capture(session)
    except (ValueError, TypeError) as error:
        raise KnowledgeOperationPlanConflictError(reason="version_mutation_transaction_required") from error


def _id(value):
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        _blocked("invalid_identifier")
    return value


@dataclass(frozen=True, slots=True)
class VersionSpaceFact:
    id: int
    tenant_id: int
    type: int
    state: int
    model_transition: bool | None


@dataclass(frozen=True, slots=True)
class VersionDocumentFact:
    id: int
    knowledge_id: int
    primary_version_id: int | None
    file_level_path: str | None
    level: int | None


@dataclass(frozen=True, slots=True)
class VersionRowFact:
    id: int
    document_id: int
    knowledge_file_id: int
    version_no: int
    is_primary: bool


@dataclass(frozen=True, slots=True)
class VersionFileFact:
    id: int
    knowledge_id: int
    tenant_id: int
    file_type: int
    status: int
    md5: str | None
    file_name: str
    similar_status: int


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class LockedVersionState:
    operation: str
    space: VersionSpaceFact | None = None
    spaces: tuple[VersionSpaceFact, ...] = ()
    anchor_file: VersionFileFact | None = None
    incoming_file: VersionFileFact | None = None
    source_document: VersionDocumentFact | None = None
    target_document: VersionDocumentFact | None = None
    source_versions: tuple[VersionRowFact, ...] = ()
    target_versions: tuple[VersionRowFact, ...] = ()
    files: tuple[VersionFileFact, ...] = ()
    reference_counts: tuple[tuple[int, int], ...] = ()
    selected_version_id: int | None = None


@dataclass(frozen=True, slots=True)
class VersionRelinkResult:
    document_id: int
    new_version_no: int
    knowledge_id: int
    file_name: str


@dataclass(frozen=True, slots=True)
class VersionPrimaryResult:
    document_id: int
    new_primary_version_no: int
    knowledge_id: int
    file_name: str


def _projection(model, fact):
    return tuple(model.__table__.c[item.name] for item in fields(fact))


def _batches(ids):
    ordered = sorted(set(ids))
    return (ordered[start : start + 200] for start in range(0, len(ordered), 200))


class KnowledgeVersionMutationRepository:
    def __init__(self):
        self._issued = WeakKeyDictionary()

    @staticmethod
    async def _rows(session, statement):
        tenant, transaction = _scope(session)
        with session.no_autoflush, strict_tenant_filter():
            rows = tuple((await session.execute(statement)).mappings())
        if _scope(session)[0] != tenant:
            _blocked("tenant_changed")
        transaction.assert_current(session)
        return rows

    def _issue(self, session, state):
        tenant, transaction = _scope(session)
        self._issued[state] = (tenant, transaction)
        return state

    async def _one(self, session, model, fact, ident, *, owned=False):
        table = model.__table__
        query = sa.select(*_projection(model, fact)).where(table.c.id == ident)
        if model is File:
            query = query.where(table.c.tenant_id == _scope(session)[0])
        if owned:
            root = Knowledge.__table__
            query = query.join(root, root.c.id == table.c.knowledge_id).where(
                root.c.tenant_id == _scope(session)[0], root.c.type == 3
            )
        rows = await self._rows(session, query)
        return fact(**rows[0]) if rows else None

    async def _file_version(self, session, ident):
        table = Version.__table__
        rows = await self._rows(
            session, sa.select(*_projection(Version, VersionRowFact)).where(table.c.knowledge_file_id == ident).limit(2)
        )
        if len(rows) > 1:
            _blocked("multiple_file_references")
        return VersionRowFact(**rows[0]) if rows else None

    @staticmethod
    def _pending(session, *, space_ids, document_ids, version_ids, file_ids):
        for item in (*session.new, *session.dirty, *session.deleted):
            state = sa.inspect(item)

            def values(name, state=state):
                attribute = state.attrs[name]
                return (*attribute.history.added, *attribute.history.deleted, state.dict.get(name))

            overlaps = (
                (isinstance(item, Knowledge) and any(value in space_ids for value in values("id")))
                or (isinstance(item, Document) and any(value in document_ids for value in values("id")))
                or (isinstance(item, File) and any(value in file_ids for value in values("id")))
                or (
                    isinstance(item, Version)
                    and (
                        any(value in version_ids for value in values("id"))
                        or any(value in document_ids for value in values("document_id"))
                        or any(value in file_ids for value in values("knowledge_file_id"))
                    )
                )
            )
            if overlaps:
                _blocked("pending_caller_graph")

    async def _collect(self, session, template):
        tenant = _scope(session)[0]
        documents = tuple(row for row in (template.source_document, template.target_document) if row is not None)
        doc_ids = {row.id for row in documents}
        space_ids = {row.knowledge_id for row in documents}
        input_files = tuple(row for row in (template.incoming_file, template.anchor_file) if row is not None)
        space_ids.update(row.knowledge_id for row in input_files)
        self._pending(
            session,
            space_ids=space_ids,
            document_ids=doc_ids,
            version_ids=set(),
            file_ids={row.id for row in input_files},
        )
        root = Knowledge.__table__
        roots = await self._rows(
            session,
            sa.select(
                root.c.id,
                root.c.tenant_id,
                root.c.type,
                root.c.state,
                root.c.model_transition,
            )
            .where(root.c.id.in_(sorted(space_ids)), root.c.tenant_id == tenant)
            .order_by(root.c.id)
            .with_for_update(),
        )
        # Native JSON null is not SQL NULL. Decode the typed column first;
        # every other value, including an empty object, still means busy.
        spaces = tuple(
            VersionSpaceFact(
                **(dict(row) | {"model_transition": True if row["model_transition"] is not None else None})
            )
            for row in roots
        )
        if {row.id for row in spaces} != space_ids or any(row.type != 3 for row in spaces):
            _blocked("space_graph")
        # Global numeric order within each lock phase, including the two docs.
        table = Document.__table__
        docs = await self._rows(
            session,
            sa.select(*_projection(Document, VersionDocumentFact))
            .where(table.c.id.in_(sorted(doc_ids)))
            .order_by(table.c.id)
            .with_for_update(),
        )
        by_doc = {row["id"]: VersionDocumentFact(**row) for row in docs}
        if any(by_doc.get(row.id) is None or by_doc[row.id].knowledge_id != row.knowledge_id for row in documents):
            _blocked("document_changed")
        versions, after = [], 0
        table = Version.__table__
        while doc_ids:
            page = await self._rows(
                session,
                sa.select(*_projection(Version, VersionRowFact))
                .where(table.c.document_id.in_(sorted(doc_ids)), table.c.id > after)
                .order_by(table.c.id)
                .limit(200)
                .with_for_update(),
            )
            versions.extend(VersionRowFact(**row) for row in page)
            if len(page) < 200:
                break
            after = page[-1]["id"]
        file_ids = {row.knowledge_file_id for row in versions} | {row.id for row in input_files}
        self._pending(
            session,
            space_ids=space_ids,
            document_ids=doc_ids,
            version_ids={row.id for row in versions},
            file_ids=file_ids,
        )
        files, counts = [], []
        for batch in _batches(file_ids):
            table = File.__table__
            rows = await self._rows(
                session,
                sa.select(*_projection(File, VersionFileFact))
                .where(table.c.id.in_(batch), table.c.tenant_id == tenant)
                .order_by(table.c.id)
                .with_for_update(),
            )
            files.extend(VersionFileFact(**row) for row in rows)
            table = Version.__table__
            rows = await self._rows(
                session,
                sa.select(table.c.knowledge_file_id, sa.func.count().label("count"))
                .where(table.c.knowledge_file_id.in_(batch))
                .group_by(table.c.knowledge_file_id),
            )
            counts.extend((row["knowledge_file_id"], row["count"]) for row in rows)
        by_file = {row.id: row for row in files}
        source = by_doc.get(template.source_document.id) if template.source_document else None
        target = by_doc.get(template.target_document.id) if template.target_document else None
        source_versions = tuple(row for row in versions if source and row.document_id == source.id)
        incoming = by_file.get(template.incoming_file.id) if template.incoming_file else None
        if template.operation == "merge" and source_versions:
            incoming = by_file.get(source_versions[0].knowledge_file_id)
        anchor = by_file.get(template.anchor_file.id) if template.anchor_file else None
        space_id = (
            (anchor or incoming).knowledge_id if anchor or incoming else template.space.id if template.space else None
        )
        return LockedVersionState(
            template.operation,
            next((row for row in spaces if row.id == space_id), None),
            spaces,
            anchor,
            incoming,
            source,
            target,
            source_versions,
            tuple(row for row in versions if target and row.document_id == target.id),
            tuple(files),
            tuple(sorted(counts)),
            template.selected_version_id,
        )

    async def alock_link_state(self, session, *, knowledge_file_id, target_document_id):
        _scope(session)
        _id(knowledge_file_id), _id(target_document_id)
        incoming = await self._one(session, File, VersionFileFact, knowledge_file_id)
        template = LockedVersionState("link", incoming_file=incoming)
        if incoming is None or incoming.status != 2:
            return self._issue(session, template)
        version = await self._file_version(session, incoming.id)
        source = (
            await self._one(session, Document, VersionDocumentFact, version.document_id, owned=True)
            if version
            else None
        )
        if version and source is None:
            _blocked("source_document_missing")
        target = await self._one(session, Document, VersionDocumentFact, target_document_id, owned=True)
        template = LockedVersionState("link", incoming_file=incoming, source_document=source, target_document=target)
        return self._issue(session, await self._collect(session, template))

    async def alock_merge_state(self, session, *, current_file_id, source_document_id):
        _scope(session)
        _id(current_file_id), _id(source_document_id)
        anchor = await self._one(session, File, VersionFileFact, current_file_id)
        template = LockedVersionState("merge", anchor_file=anchor)
        if anchor is None or anchor.status != 2:
            return self._issue(session, template)
        version = await self._file_version(session, anchor.id)
        target = (
            await self._one(session, Document, VersionDocumentFact, version.document_id, owned=True)
            if version
            else None
        )
        if version and target is None:
            _blocked("current_document_missing")
        if target is None:
            return self._issue(session, template)
        source = await self._one(session, Document, VersionDocumentFact, source_document_id, owned=True)
        return self._issue(
            session,
            await self._collect(
                session, LockedVersionState("merge", anchor_file=anchor, source_document=source, target_document=target)
            ),
        )

    async def alock_primary_state(self, session, *, version_id):
        _scope(session)
        _id(version_id)
        version = await self._one(session, Version, VersionRowFact, version_id)
        target = (
            await self._one(session, Document, VersionDocumentFact, version.document_id, owned=True)
            if version
            else None
        )
        if target is None:
            return self._issue(session, LockedVersionState("primary"))
        file = await self._one(session, File, VersionFileFact, version.knowledge_file_id)
        return self._issue(
            session,
            await self._collect(
                session,
                LockedVersionState(
                    "primary", incoming_file=file, target_document=target, selected_version_id=version_id
                ),
            ),
        )

    async def _verify(self, session, state):
        tenant, _ = _scope(session)
        issued = self._issued.get(state) if type(state) is LockedVersionState else None
        if issued is None or issued[0] != tenant:
            _blocked("unissued_state")
        try:
            issued[1].assert_current(session)
        except (ValueError, TypeError) as error:
            raise KnowledgeOperationPlanConflictError(reason="version_mutation_transaction_changed") from error
        fresh = await self._collect(session, state)
        if any(getattr(fresh, item.name) != getattr(state, item.name) for item in fields(state)):
            _blocked("locked_graph_changed")
        by_file = {row.id: row for row in state.files}
        counts = dict(state.reference_counts)
        for document, rows in (
            (state.source_document, state.source_versions),
            (state.target_document, state.target_versions),
        ):
            if document is None:
                continue
            primary = [row for row in rows if row.is_primary]
            if (
                not rows
                or len(primary) != 1
                or primary[0].id != document.primary_version_id
                or len({row.version_no for row in rows}) != len(rows)
            ):
                _blocked("invalid_document_chain")
            for row in rows:
                file = by_file.get(row.knowledge_file_id)
                if (
                    file is None
                    or file.file_type != 1
                    or file.knowledge_id != document.knowledge_id
                    or counts.get(file.id) != 1
                    or row.version_no < 1
                ):
                    _blocked("invalid_file_chain")
        if state.target_document is None or state.incoming_file is None or state.incoming_file.file_type != 1:
            _blocked("incomplete_state")
        if state.space is None or state.incoming_file.knowledge_id != state.target_document.knowledge_id:
            _blocked("different_space")
        return state

    async def _write(self, session, statement):
        with session.no_autoflush, strict_tenant_filter():
            return await session.execute(statement)

    async def arelink(self, session, *, state, new_version_no):
        state = await self._verify(session, state)
        if (
            state.operation not in {"link", "merge"}
            or len(state.source_versions) > 1
            or state.source_document == state.target_document
        ):
            _blocked("invalid_relink_state")
        if (
            type(new_version_no) is not int
            or new_version_no != max(row.version_no for row in state.target_versions) + 1
        ):
            _blocked("invalid_next_version")
        if state.source_document is not None and (
            len(state.source_versions) != 1 or state.source_versions[0].knowledge_file_id != state.incoming_file.id
        ):
            _blocked("incoming_source_changed")
        if not state.source_versions and dict(state.reference_counts).get(state.incoming_file.id, 0):
            _blocked("incoming_file_already_linked")
        del self._issued[state]
        version, document, file = Version.__table__, Document.__table__, File.__table__
        saved = await self._write(
            session,
            version.insert().values(
                document_id=state.target_document.id,
                knowledge_file_id=state.incoming_file.id,
                version_no=new_version_no,
                is_primary=True,
            ),
        )
        ident = saved.inserted_primary_key[0]
        await self._write(
            session,
            document.update()
            .where(document.c.id == state.target_document.id, document.c.knowledge_id == state.space.id)
            .values(primary_version_id=ident),
        )
        await self._write(
            session,
            version.update()
            .where(
                version.c.document_id == state.target_document.id, version.c.id != ident, version.c.is_primary.is_(True)
            )
            .values(is_primary=False),
        )
        if state.source_document is not None:
            await self._write(
                session,
                version.delete().where(
                    version.c.id == state.source_versions[0].id, version.c.document_id == state.source_document.id
                ),
            )
            await self._write(
                session,
                document.delete().where(
                    document.c.id == state.source_document.id, document.c.knowledge_id == state.space.id
                ),
            )
        if state.incoming_file.similar_status != 2:
            await self._write(
                session,
                file.update()
                .where(
                    file.c.id == state.incoming_file.id,
                    file.c.tenant_id == state.space.tenant_id,
                    file.c.knowledge_id == state.space.id,
                )
                .values(similar_status=2),
            )
        return VersionRelinkResult(
            state.target_document.id, new_version_no, state.space.id, state.incoming_file.file_name
        )

    async def aset_primary(self, session, *, state):
        state = await self._verify(session, state)
        selected = next((row for row in state.target_versions if row.id == state.selected_version_id), None)
        if state.operation != "primary" or selected is None:
            _blocked("invalid_primary_state")
        del self._issued[state]
        if not selected.is_primary:
            table = Version.__table__
            await self._write(
                session,
                table.update()
                .where(table.c.id == selected.id, table.c.document_id == state.target_document.id)
                .values(is_primary=True),
            )
            table = Document.__table__
            await self._write(
                session,
                table.update()
                .where(table.c.id == state.target_document.id, table.c.knowledge_id == state.space.id)
                .values(primary_version_id=selected.id),
            )
            table = Version.__table__
            await self._write(
                session,
                table.update()
                .where(
                    table.c.document_id == state.target_document.id,
                    table.c.id != selected.id,
                    table.c.is_primary.is_(True),
                )
                .values(is_primary=False),
            )
        return VersionPrimaryResult(
            state.target_document.id, selected.version_no, state.space.id, state.incoming_file.file_name
        )
