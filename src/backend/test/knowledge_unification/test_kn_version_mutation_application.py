"""Real atomic version application, preserving original business admission."""

import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, KnowledgeProcessingConflictError
from bisheng.common.errcode.knowledge_space import (
    VersionLinkFileNotReadyError,
    VersionLinkSourceFileMissingError,
    VersionLinkSourceMultiVersionError,
    VersionLinkTargetUnavailableError,
    VersionManagementDisabledError,
)
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Document
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from test.knowledge_unification import test_kn_version_mutation_repository as native_tests

native = native_tests.native
database = native_tests.database


def api():
    return importlib.import_module("bisheng.knowledge.application.knowledge_version_mutation")


def user(home=101):
    return UserPayload(user_id=7, user_name="original", tenant_id=home, user_role=[])


def build(database, *, enabled=None, session_factory=None):
    sessions, commits, admissions = [], [], []

    @asynccontextmanager
    async def fresh():
        async with AsyncSession(database.engine) as session:
            sessions.append(session)
            sa.event.listen(session.sync_session, "after_commit", lambda *args: commits.append(1))
            yield session

    async def feature():
        assert not sessions
        admissions.append(1)
        if enabled is not None:
            await enabled()

    app = api().KnowledgeVersionMutationApplication(
        session_factory=session_factory or fresh, require_version_management_enabled=feature
    )
    return SimpleNamespace(app=app, sessions=sessions, commits=commits, admissions=admissions)


async def invoke(app, operation, login_user=None, *, source=10, target=20, selected=2001):
    login_user = login_user or user()
    if operation == "link":
        return await app.alink_file(login_user=login_user, knowledge_file_id=101, target_document_id=target)
    if operation == "merge":
        return await app.amerge_document(
            login_user=login_user, current_knowledge_file_id=201, source_document_id=source
        )
    return await app.aset_primary(login_user=login_user, version_id=selected)


@pytest.mark.parametrize("operation", ["link", "merge", "primary"])
async def test_actual_factory_one_commit_and_original_identity_is_not_rewritten(database, operation):
    built, original_user = build(database), user(home=1)
    before = original_user.model_dump()
    result = await invoke(built.app, operation, original_user)
    assert result.document_id == 20
    assert result.knowledge_id == 9700 and result.file_name == "private-name"
    assert built.admissions == [1] and built.commits == [1] and len(built.sessions) == 1
    assert not built.sessions[0].in_transaction() and original_user.model_dump() == before
    after = await native_tests.snapshot(database)
    rows = [row for row in after["knowledge_document_version"] if row["document_id"] == 20]
    assert len([row for row in rows if row["is_primary"]]) == 1
    assert (
        getattr(result, "new_primary_version_no", None) == 1 if operation == "primary" else result.new_version_no == 4
    )


@pytest.mark.parametrize("operation", ["link", "merge", "primary"])
async def test_switch_rejection_is_before_session_creation_and_any_sql(database, operation):
    async def disabled():
        raise VersionManagementDisabledError()

    built = build(database, enabled=disabled)
    database.queries.clear()
    with pytest.raises(VersionManagementDisabledError):
        await invoke(built.app, operation)
    assert not built.sessions and not database.queries and not built.commits


async def corrupt(database, case):
    async with database.engine.begin() as connection:
        if case == "source_missing":
            await connection.execute(sa.delete(File).where(File.id == 101))
        elif case in {"source_failed", "source_failed_and_rebuilding"}:
            await connection.execute(sa.update(File).where(File.id == 101).values(status=3))
        elif case == "source_multi":
            await connection.execute(sa.insert(File), native_tests.original.file(103, knowledge_id=9700))
            await connection.execute(sa.insert(Version), native_tests.version(1002, 10, 103, no=2, primary=False))
            # The original source guard precedes even an unavailable target.
            await connection.execute(sa.delete(Document).where(Document.id == 20))
        elif case == "target_missing":
            await connection.execute(sa.delete(Document).where(Document.id == 20))
        elif case == "target_pointer":
            await connection.execute(sa.update(Document).where(Document.id == 20).values(primary_version_id=99999))
        elif case == "target_failed":
            await connection.execute(sa.update(File).where(File.id == 202).values(status=3))
        elif case == "duplicate":
            await connection.execute(sa.update(File).where(File.id == 101).values(md5="202"))
        elif case == "merge_source_missing":
            await connection.execute(sa.delete(Document).where(Document.id == 10))
        elif case == "merge_source_no_version":
            await connection.execute(sa.delete(Version).where(Version.id == 1001))
        elif case == "merge_source_multi":
            await connection.execute(sa.insert(File), native_tests.original.file(103, knowledge_id=9700))
            await connection.execute(sa.insert(Version), native_tests.version(1002, 10, 103, no=2, primary=False))
        elif case == "current_missing":
            await connection.execute(sa.delete(File).where(File.id == 201))
        elif case == "current_failed":
            await connection.execute(sa.update(File).where(File.id == 201).values(status=3))
        elif case == "current_no_version":
            await connection.execute(sa.delete(Version).where(Version.id == 2001))
        elif case == "primary_failed":
            await connection.execute(sa.update(File).where(File.id == 201).values(status=3))
        if case in {"rebuilding", "source_failed_and_rebuilding"}:
            await connection.execute(
                sa.update(Knowledge).where(Knowledge.id == 9700).values(state=KnowledgeState.REBUILDING.value)
            )
        elif case == "transition":
            await connection.execute(sa.update(Knowledge).where(Knowledge.id == 9700).values(model_transition={}))


@pytest.mark.parametrize(
    "operation,case,error",
    [
        ("link", "source_missing", VersionLinkSourceFileMissingError),
        ("link", "source_failed", VersionLinkFileNotReadyError),
        ("link", "source_failed_and_rebuilding", VersionLinkFileNotReadyError),
        ("link", "source_multi", VersionLinkSourceMultiVersionError),
        ("link", "target_missing", VersionLinkTargetUnavailableError),
        ("link", "target_pointer", VersionLinkTargetUnavailableError),
        ("link", "target_failed", VersionLinkTargetUnavailableError),
        ("link", "rebuilding", KnowledgeProcessingConflictError),
        ("link", "transition", KnowledgeProcessingConflictError),
        ("merge", "current_missing", VersionLinkSourceFileMissingError),
        ("merge", "current_failed", VersionLinkFileNotReadyError),
        ("merge", "current_no_version", VersionLinkFileNotReadyError),
        ("merge", "merge_source_missing", VersionLinkSourceFileMissingError),
        ("merge", "merge_source_no_version", VersionLinkSourceFileMissingError),
        ("merge", "source_missing", VersionLinkSourceFileMissingError),
        ("merge", "source_failed", VersionLinkFileNotReadyError),
        ("merge", "merge_source_multi", VersionLinkSourceMultiVersionError),
        ("merge", "rebuilding", KnowledgeProcessingConflictError),
        ("primary", "rebuilding", KnowledgeProcessingConflictError),
        ("primary", "transition", KnowledgeProcessingConflictError),
    ],
)
async def test_original_business_errors_and_order_have_no_durable_writes(database, operation, case, error):
    await corrupt(database, case)
    before = await native_tests.snapshot(database)
    built = build(database)
    with pytest.raises(error):
        await invoke(built.app, operation)
    assert not built.commits and await native_tests.snapshot(database) == before


@pytest.mark.parametrize(
    "operation,case,code",
    [
        ("link", "duplicate", 409),
        ("merge", "duplicate", 409),
        ("link", "different_space", 409),
        ("merge", "different_space", 409),
        ("primary", "primary_failed", 412),
        ("primary", "version_missing", 404),
    ],
)
async def test_legacy_http_error_semantics_are_not_replaced_by_a_new_permission_gate(database, operation, case, code):
    await corrupt(database, case)
    before = await native_tests.snapshot(database)
    built = build(database)
    with pytest.raises(HTTPException) as caught:
        await invoke(
            built.app,
            operation,
            source=30 if case == "different_space" else 10,
            target=30 if case == "different_space" else 20,
            selected=99999 if case == "version_missing" else 2001,
        )
    assert caught.value.status_code == code
    assert not built.commits and await native_tests.snapshot(database) == before


async def test_merge_preserves_old_qualification_when_current_is_historical_and_primary_failed(database):
    await corrupt(database, "target_failed")
    result = await invoke(build(database).app, "merge")
    assert result.new_version_no == 4


async def test_existing_primary_is_an_atomic_noop_without_version_creation(database):
    before = await native_tests.snapshot(database)
    result = await invoke(build(database).app, "primary", selected=2002)
    assert result.new_primary_version_no == 3
    assert await native_tests.snapshot(database) == before


async def test_actual_write_failure_is_rolled_back_by_application_transaction(database):
    before, statements = await native_tests.snapshot(database), []

    def fault(_conn, _cursor, sql, _parameters, _context, _many):
        if sql.startswith(("INSERT", "UPDATE", "DELETE")):
            statements.append(sql)
            if len(statements) == 3:
                raise RuntimeError("original SQL failure")

    sa.event.listen(database.engine.sync_engine, "after_cursor_execute", fault)
    try:
        built = build(database)
        with pytest.raises(RuntimeError, match="original SQL failure"):
            await invoke(built.app, "link")
    finally:
        sa.event.remove(database.engine.sync_engine, "after_cursor_execute", fault)
    assert not built.commits and await native_tests.snapshot(database) == before


async def test_durable_commit_with_lost_ack_propagates_and_never_retries_or_compensates(database):
    calls = []

    @asynccontextmanager
    async def sessions():
        calls.append(1)
        async with AsyncSession(database.engine) as session:

            def lost_ack(_session):
                raise RuntimeError("commit reply unavailable")

            sa.event.listen(session.sync_session, "after_commit", lost_ack)
            yield session

    built = build(database, session_factory=sessions)
    with pytest.raises(RuntimeError, match="commit reply unavailable"):
        await invoke(built.app, "link")
    after = await native_tests.snapshot(database)
    assert calls == [1]
    assert len([row for row in after["knowledge_document_version"] if row["document_id"] == 20]) == 3
    assert len([row for row in after["knowledge_document_version"] if row["knowledge_file_id"] == 101]) == 1


async def test_scope_changed_during_feature_io_is_rejected_before_session_creation(database):
    async def changed():
        set_current_tenant_id(202)

    token = set_current_tenant_id(101)
    try:
        built = build(database, enabled=changed)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await invoke(built.app, "link")
        assert not built.sessions
    finally:
        current_tenant_id.reset(token)


async def test_caller_active_session_cannot_be_borrowed_as_a_fresh_application_session(database):
    async with AsyncSession(database.engine) as caller, caller.begin():

        @asynccontextmanager
        async def borrowed():
            yield caller

        built = build(database, session_factory=borrowed)
        database.queries.clear()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await invoke(built.app, "link")
        assert caller.in_transaction() and not database.queries


async def test_unknown_commit_is_preserved_when_factory_close_also_fails(database):
    original = RuntimeError("original commit ACK unavailable")
    calls = []

    @asynccontextmanager
    async def sessions():
        calls.append(1)
        session = AsyncSession(database.engine)

        def lost_ack(_session):
            raise original

        sa.event.listen(session.sync_session, "after_commit", lost_ack)
        try:
            yield session
        finally:
            await session.close()
            raise OSError("secondary factory close unavailable")

    with pytest.raises(RuntimeError, match="original commit ACK") as caught:
        await invoke(build(database, session_factory=sessions).app, "link")
    assert caught.value is original and calls == [1]
    after = await native_tests.snapshot(database)
    assert len([row for row in after["knowledge_document_version"] if row["document_id"] == 20]) == 3


async def test_original_business_error_is_preserved_when_native_transaction_rollback_fails(database, monkeypatch):
    await corrupt(database, "source_failed")
    before, rolled_back = await native_tests.snapshot(database), []

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(database.engine) as session:

            def root_created(_session, transaction):
                if transaction.parent is not None:
                    return
                original_rollback = transaction.rollback

                def failed_reply(*args, **kwargs):
                    original_rollback(*args, **kwargs)  # Actual native rollback runs first.
                    rolled_back.append(1)
                    raise OSError("secondary transaction rollback unavailable")

                monkeypatch.setattr(transaction, "rollback", failed_reply)

            sa.event.listen(session.sync_session, "after_transaction_create", root_created)
            yield session

    with pytest.raises(VersionLinkFileNotReadyError):
        await invoke(build(database, session_factory=sessions).app, "link")
    assert rolled_back == [1] and await native_tests.snapshot(database) == before
