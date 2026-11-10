"""T963: exact inbound streams retain native Owner authority and bounded work.

覆盖 AC: AC-28, AC-29, AC-72, AC-89, AC-90, AC-91, AC-94
SQLite validates SQL/results and transaction identity, not physical lock timing.
"""

import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from math import ceil

import pytest
from sqlalchemy import event, insert, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.application.reference_target_owner import KnowledgeReferenceTargetOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob
from bisheng.resource_reference.application.contracts import TargetKey, TargetType
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet as SourceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference as Binding
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_knowledge_reference_owner as owner
from test.knowledge_unification.test_ref_repo import tenant

owner_tenant = owner.owner_tenant


@asynccontextmanager
async def native(count=1, *, slots=1, sparse=False):
    engine = create_async_engine("sqlite+aiosqlite://")
    keys = tuple(TargetKey("knowledge_file", i) for i in range(1, count + 1))
    selected = (keys[0], keys[count // 2], keys[-1]) if sparse else tuple(reversed(keys))
    references = [
        {
            "tenant_id": 101,
            "source_type": "assistant",
            "source_id": "a",
            "source_version": "current",
            "source_revision": 3,
            "target_type": "knowledge_file",
            "target_id": key.target_id,
            "target_tenant_id": 101,
            "target_space_id": "1",
            "slot_key": f"slot-{key.target_id}-{slot}",
        }
        for key in selected
        for slot in range(slots)
    ]
    tables = [
        KnowledgeSpaceDeleteJob.__table__,
        Knowledge.__table__,
        KnowledgeFile.__table__,
        SourceSet.__table__,
        Binding.__table__,
        ResourceReferenceTombstone.__table__,
    ]
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: SQLModel.metadata.create_all(conn, tables=tables))
            await connection.execute(
                insert(Knowledge.__table__), {"id": 1, "tenant_id": 101, "user_id": 7, "name": "root", "type": 3}
            )
            await connection.execute(
                insert(KnowledgeFile.__table__),
                [
                    {"id": i, "tenant_id": 101, "knowledge_id": 1, "user_id": 7, "file_name": str(i)}
                    for i in range(1, count + 1)
                ],
            )
            await connection.execute(
                insert(SourceSet.__table__),
                {
                    "tenant_id": 101,
                    "source_type": "assistant",
                    "source_id": "a",
                    "source_version": "current",
                    "source_revision": 3,
                    "extractor_version": "native",
                    "digest": "a" * 64,
                    "ready": True,
                    "effective": True,
                },
            )
            if references:
                await connection.execute(insert(Binding.__table__), references)
        async with AsyncSession(engine) as session:
            await session.begin()
            verifier = ReferenceTargetVerifier({TargetType.KNOWLEDGE_FILE: KnowledgeReferenceTargetOwner()})
            repository = ReferenceRepository(verifier=verifier)
            receipts = await verifier.averify_owner_targets(session, keys)
            scope = repository.target_owner_scope(session, receipts)
            yield session, repository, scope, references
    finally:
        await engine.dispose()


@contextmanager
def observe(session, repository, monkeypatch):
    sql, validation, checks = [], [], []
    original, check = repository.verifier.validate_owner_receipts, repository._check_scope

    def validated(active, receipts):
        validation.append(len(receipts))
        return original(active, receipts)

    def checked(active, scope):
        checks.append(scope)
        return check(active, scope)

    def record(_conn, _cursor, statement, params, _context, _many):
        sql.append((statement, params))

    monkeypatch.setattr(repository.verifier, "validate_owner_receipts", validated)
    monkeypatch.setattr(repository, "_check_scope", checked)
    event.listen(session.bind.sync_engine, "before_cursor_execute", record)
    try:
        yield sql, validation, checks
    finally:
        event.remove(session.bind.sync_engine, "before_cursor_execute", record)


async def consume(repository, session, scope, *, limit=200):
    pages = [page async for page in repository.aiter_inbound_for_owner_pages(session, scope, limit=limit)]
    assert all(type(page) is tuple and 0 < len(page) <= limit for page in pages)
    return tuple(row for page in pages for row in page)


@pytest.mark.parametrize(
    "count,slots,sparse",
    [
        (200, 1, False),
        (401, 0, False),
        (401, 3, False),
        (1001, 0, False),
        (1001, 3, False),
        (10001, 1, True),
        (10001, 3, False),
    ],
)
async def test_native_401_1001_10001_exact_stream_bounds_sql_rows_and_full_scope_cpu(monkeypatch, count, slots, sparse):
    async with native(count, slots=slots, sparse=sparse) as (session, repository, scope, seeded):
        with observe(session, repository, monkeypatch) as (sql, validation, checks):
            rows = await consume(repository, session, scope)
        assert len(rows) == len(seeded)
        assert len({row.id for row in rows}) == len(seeded)
        assert all(row.target_type == "knowledge_file" and 1 <= int(row.target_id) <= count for row in rows)
        assert validation == [count, count] and len(checks) == 2
        assert len(sql) <= ceil(count / 200) + len(seeded) // 200
        assert len(sql) >= ceil(count / 200)
        assert all(query.lstrip().upper().startswith("SELECT") and "LEFT OUTER JOIN" in query for query, _ in sql)
        assert max(len(params) for _, params in sql) <= 250
        assert all("ORDER BY business_resource_reference.id" in query and "LIMIT" in query for query, _ in sql)
        groups = [((int(row.target_id) - 1) // 200, row.id) for row in rows]
        assert groups == sorted(groups)
        if count > 200 and not sparse and slots:
            assert [row.id for row in rows] != sorted(row.id for row in rows)
        assert not session.new and not session.dirty and not session.deleted
        print({"targets": count, "references": len(seeded), "sql": len(sql), "full_validation_candidates": validation})


async def test_native_limit_exact_tail_and_unselected_space_and_file_never_expand_scope(monkeypatch):
    async with native(201, slots=2) as (session, repository, scope, _):
        await session.execute(
            insert(Binding.__table__),
            [
                {
                    "tenant_id": 101,
                    "source_type": "assistant",
                    "source_id": "a",
                    "source_version": "current",
                    "source_revision": 3,
                    "slot_key": kind,
                    "target_type": kind,
                    "target_id": ident,
                    "target_tenant_id": 101,
                    "target_space_id": "1",
                }
                for kind, ident in (("knowledge_space", "1"), ("knowledge_file", "999999"))
            ],
        )
        await session.flush()
        with observe(session, repository, monkeypatch) as (sql, validations, _):
            rows = await consume(repository, session, scope, limit=37)
        assert len(rows) == 402 and all(
            row.target_type == "knowledge_file" and row.target_id != "999999" for row in rows
        )
        assert len(sql) == 12 and validations == [201, 201]


@pytest.mark.parametrize("limit", [0, 201, True, "1", None, 1.0])
async def test_invalid_limits_fail_before_query(monkeypatch, limit):
    async with native() as (session, repository, scope, _):
        with observe(session, repository, monkeypatch) as (sql, _, _), pytest.raises(ValueError):
            await consume(repository, session, scope, limit=limit)
        assert not sql


@pytest.mark.parametrize(
    "failure", ["missing", "not_ready", "inactive", "revision", "record_kind", "tenant", "type", "source_id", "version"]
)
async def test_native_complete_left_source_identity_never_erases_blocking_binding(failure):
    async with native() as (session, repository, scope, _):
        if failure == "missing":
            await session.execute(SourceSet.__table__.delete())
        elif failure == "revision":
            await session.execute(update(Binding).values(source_revision=2))
        else:
            change = {
                "not_ready": {"ready": False},
                "inactive": {"effective": False},
                "record_kind": {
                    "record_kind": "root_guard",
                    "source_version": "__root__",
                    "ready": False,
                    "effective": False,
                },
                "tenant": {"tenant_id": 202},
                "type": {"source_type": "channel_sync"},
                "source_id": {"source_id": "other"},
                "version": {"source_version": "other"},
            }[failure]
            await session.execute(update(SourceSet).values(**change))
        await session.flush()
        with pytest.raises(ReferenceCoverageNotReadyError) as failure_result:
            await consume(repository, session, scope)
        assert failure_result.value.kwargs["reason"] == "reference_inbound_source_incomplete"


async def test_native_foreign_sources_versions_and_registered_legacy_are_preserved():
    async with native() as (session, repository, scope, _):
        with bypass_tenant_filter():
            for tid, kind, version in (
                (202, "assistant", "current"),
                (202, "workflow_version", "v1"),
                (202, "workflow_version", "v2"),
            ):
                session.add(
                    SourceSet(
                        tenant_id=tid,
                        source_type=kind,
                        source_id="same",
                        source_version=version,
                        source_revision=3,
                        extractor_version="native",
                        digest="a" * 64,
                        ready=True,
                        effective=True,
                    )
                )
                session.add(
                    Binding(
                        tenant_id=tid,
                        source_type=kind,
                        source_id="same",
                        source_version=version,
                        source_revision=3,
                        slot_key="paused-or-history",
                        target_type="knowledge_file",
                        target_id="1",
                        target_tenant_id=101,
                        target_space_id="1",
                    )
                )
            await session.flush()
            await session.execute(
                update(Binding)
                .where(Binding.tenant_id == 101)
                .values(
                    target_tenant_id=None,
                    legacy_invalid_reason="target_missing",
                    legacy_run_id="frozen",
                    legacy_evidence_key="proof",
                )
            )
        rows = await consume(repository, session, scope, limit=2)
        assert (
            len(rows) == 4
            and len({(row.tenant_id, row.source_type, row.source_id, row.source_version) for row in rows}) == 4
        )
        assert rows[0].legacy_run_id == "frozen" and rows[0].target_tenant_id is None


@pytest.mark.parametrize("failure", ["copy", "foreign_repo", "transaction", "session", "tenant", "bypass"])
async def test_original_scope_session_tenant_and_issuer_guards_fail_before_sql(monkeypatch, failure):
    async with native() as (session, repository, scope, _):
        if failure == "copy":
            scope = replace(scope)
        elif failure == "foreign_repo":
            repository = ReferenceRepository(verifier=repository.verifier)
        elif failure == "transaction":
            await session.commit()
            await session.begin()
        with observe(session, repository, monkeypatch) as (sql, _, _), pytest.raises(ResourceReferenceInvalidError):
            if failure == "session":
                async with AsyncSession(session.bind) as other:
                    await other.begin()
                    await consume(repository, other, scope)
            elif failure == "tenant":
                with tenant(202):
                    await consume(repository, session, scope)
            elif failure == "bypass":
                with bypass_tenant_filter():
                    await consume(repository, session, scope)
            else:
                await consume(repository, session, scope)
        assert not sql


@pytest.mark.parametrize(
    "failure", ["scope_targets", "key_alias", "transaction", "tenant", "bypass", "registration", "authority", "owner"]
)
async def test_yield_changes_cannot_expand_later_sql_or_prove_completion(monkeypatch, failure):
    async with native(201) as (session, repository, scope, _):
        stream = repository.aiter_inbound_for_owner_pages(session, scope, limit=1)
        with observe(session, repository, monkeypatch) as (sql, validation, _):
            first = await anext(stream)
            assert len(first) == 1
            if failure == "scope_targets":
                object.__setattr__(scope, "targets", (TargetKey("knowledge_file", 999999),))
            elif failure == "key_alias":
                object.__setattr__(scope.targets[-1], "target_id", "999999")
            elif failure == "transaction":
                await session.commit()
                await session.begin()
                # The stream must guard its captured TX, not this mutable field.
                from bisheng.resource_reference.application.contracts import TransactionIdentity

                object.__setattr__(scope, "transaction", TransactionIdentity.capture(session))
            elif failure == "registration":
                del repository._issued_scopes[scope]
            elif failure == "authority":
                object.__setattr__(scope, "_authority", object())
            elif failure == "owner":
                object.__setattr__(scope, "owner_tenant_id", 202)
            with pytest.raises(ResourceReferenceInvalidError):
                if failure == "tenant":
                    with tenant(202):
                        _ = [page async for page in stream]
                elif failure == "bypass":
                    with bypass_tenant_filter():
                        _ = [page async for page in stream]
                else:
                    _ = [page async for page in stream]
            assert all("999999" not in tuple(map(str, params)) for _, params in sql)
            if failure in {"scope_targets", "key_alias"}:
                assert len(sql) >= 2
            else:
                assert len(sql) == 1 and len(validation) == 1
        await stream.aclose()


@pytest.mark.parametrize("ending", ["close", "cancel"])
async def test_partial_or_cancelled_native_stream_never_runs_completion_validation(monkeypatch, ending):
    async with native(201) as (session, repository, scope, _):
        stream = repository.aiter_inbound_for_owner_pages(session, scope, limit=1)
        with observe(session, repository, monkeypatch) as (sql, validation, _):
            if ending == "close":
                assert len(await anext(stream)) == 1
                await stream.aclose()
            else:
                entered, hold = asyncio.Event(), asyncio.Event()

                async def read():
                    try:
                        async for _page in stream:
                            entered.set()
                            await hold.wait()
                    finally:
                        await stream.aclose()

                task = asyncio.create_task(read())
                await entered.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert len(sql) == 1 and validation == [201]


async def test_stream_does_not_autoflush_pending_rows(monkeypatch):
    async with native() as (session, repository, scope, _):
        pending = SourceSet(
            tenant_id=101,
            source_type="assistant",
            source_id="pending",
            source_version="current",
            source_revision=1,
            extractor_version="native",
            digest="a" * 64,
            ready=True,
            effective=True,
        )
        session.add(pending)
        with observe(session, repository, monkeypatch) as (sql, _, _):
            assert len(await consume(repository, session, scope)) == 1
        assert pending in session.new and pending.id is None
        assert all(query.lstrip().upper().startswith("SELECT") for query, _ in sql)
