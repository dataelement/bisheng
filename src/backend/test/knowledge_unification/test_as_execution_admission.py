"""T364: the assistant facade borrows active transactions and preserves identity.

The runtime substitute here tests the consumer Port only, never production
composition or scope authority. Real runtime integration is tested separately.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.assistant.application import execution_admission as admission_module
from bisheng.assistant.application.execution_admission import AssistantExecutionAdmission
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.resource_reference.application.contracts import SourceKey
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    SourceReferenceReadResult,
    canonical_payload_json,
    payload_digest,
)
from test.knowledge_unification import test_as_source_owner as owner_tests

source_db = owner_tests.source_db
source_tenant = owner_tests.source_tenant


@pytest.fixture
async def admission_db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admission.db'}")
    owned = []

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine) as session:
            owned.append(session)
            yield session

    payload = canonical_payload_json({"assistant": {"id": "as-a", "temperature": 0.7}, "links": []})
    snapshot = AuthorizedSourceSnapshot(
        SourceKey(101, "assistant", "as-a", "current"), (), "assistant-v1", payload_digest(payload), payload
    )
    result = SourceReferenceReadResult(snapshot, (), 3, 4)
    scope = object()
    issue = AsyncMock(return_value=scope)
    execute = AsyncMock(return_value=result)
    inspect = AsyncMock(return_value=result)
    from types import SimpleNamespace

    runtime = SimpleNamespace(
        verifier=SimpleNamespace(aissue_scope=issue), arequire_source_valid=execute, ainspect_source=inspect
    )
    getter = AsyncMock(return_value=runtime)
    monkeypatch.setattr(admission_module, "get_async_db_session", sessions)
    monkeypatch.setattr(admission_module, "get_reference_read_runtime", getter)
    user = UserPayload(user_id=9, user_name="actor", user_role=[], tenant_id=101)
    try:
        yield engine, owned, runtime, getter, user, result, scope
    finally:
        await engine.dispose()


async def test_borrowed_active_session_is_used_without_begin_commit_or_identity_conversion(admission_db):
    engine, owned, runtime, _getter, user, result, scope = admission_db
    async with AsyncSession(engine) as session, session.begin():
        transaction = session.get_transaction()
        actual = await AssistantExecutionAdmission.prepare(user, "as-a", session=session)
        assert actual is result
        assert session.get_transaction() is transaction
        assert session.in_transaction()
        assert not owned
        issue_call = runtime.verifier.aissue_scope.await_args
        assert issue_call.args[0] is session and issue_call.args[2] is user
        assert issue_call.args[1].source_type == "assistant"
        assert issue_call.args[1].source_version == "current"
        runtime.arequire_source_valid.assert_awaited_once_with(session, scope, user)
        runtime.ainspect_source.assert_not_awaited()


async def test_owned_session_is_active_during_scope_and_released_after_read(admission_db):
    _engine, owned, runtime, _getter, user, result, scope = admission_db

    async def execute(session, supplied_scope, identity):
        assert session.in_transaction()
        assert supplied_scope is scope and identity is user
        return result

    runtime.arequire_source_valid.side_effect = execute
    assert await AssistantExecutionAdmission.prepare(user, "as-a") is result
    assert len(owned) == 1 and not owned[0].in_transaction()


async def test_inspect_only_forwards_actual_secret_to_owner_request(admission_db):
    engine, _owned, runtime, _getter, user, result, scope = admission_db
    async with AsyncSession(engine) as session, session.begin():
        assert (
            await AssistantExecutionAdmission.prepare(
                user, "as-a", session=session, purpose="inspect", inspect_token="secret-token"
            )
            is result
        )
        request = runtime.verifier.aissue_scope.await_args.args[1]
        assert request.inspect_token == "secret-token"
        assert "secret-token" not in repr(request)
        runtime.ainspect_source.assert_awaited_once_with(session, scope, user)
        runtime.arequire_source_valid.assert_not_awaited()


async def test_inspect_token_cannot_be_promoted_to_execute(admission_db):
    engine, _owned, runtime, _getter, user, _result, _scope = admission_db
    async with AsyncSession(engine) as session, session.begin():
        with pytest.raises(ValueError):
            await AssistantExecutionAdmission.prepare(user, "as-a", session=session, inspect_token="secret")
        runtime.verifier.aissue_scope.assert_not_awaited()


async def test_missing_coverage_and_invalid_references_propagate_without_retry_or_commit(admission_db):
    engine, owned, runtime, _getter, user, _result, _scope = admission_db
    async with AsyncSession(engine) as session, session.begin():
        error = ReferenceCoverageNotReadyError()
        runtime.verifier.aissue_scope.side_effect = error
        with pytest.raises(ReferenceCoverageNotReadyError) as caught:
            await AssistantExecutionAdmission.prepare(user, "as-a", session=session)
        assert caught.value is error and session.in_transaction()
        runtime.verifier.aissue_scope.side_effect = None
        runtime.arequire_source_valid.side_effect = ResourceReferenceInvalidError()
        with pytest.raises(ResourceReferenceInvalidError):
            await AssistantExecutionAdmission.prepare(user, "as-a", session=session)
        assert session.in_transaction()
        assert not owned


async def test_borrowed_session_requires_existing_transaction(admission_db):
    engine, owned, runtime, _getter, user, _result, _scope = admission_db
    async with AsyncSession(engine) as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await AssistantExecutionAdmission.prepare(user, "as-a", session=session)
        assert not session.in_transaction() and not owned
        runtime.verifier.aissue_scope.assert_not_awaited()


async def test_unconfigured_runtime_fails_closed(admission_db):
    _engine, _owned, runtime, getter, user, _result, _scope = admission_db
    getter.side_effect = ReferenceCoverageNotReadyError(reason="unconfigured")
    with pytest.raises(ReferenceCoverageNotReadyError):
        await AssistantExecutionAdmission.prepare(user, "as-a")
    runtime.verifier.aissue_scope.assert_not_awaited()


async def _actual_owner_runtime(source_db, monkeypatch):
    """Real SourceOwner/Core/identity, with a test-only target boundary.

    Production model/knowledge Owners are integrated after their checkpoint;
    this boundary is never installed in the application's composition.
    """
    from sqlmodel import SQLModel

    from bisheng.permission.application.identity import PermissionActor, set_current_permission_actor
    from bisheng.resource_reference.application.contracts import reference_set_digest
    from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
    from bisheng.resource_reference.application.source_contracts import ReferenceTargetReadFact, SourceReadRequest
    from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime
    from bisheng.resource_reference.application.source_verification import SourceReadVerifier
    from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
    from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
    from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository

    engine, owner, user, _permission = source_db
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(
                conn, tables=[BusinessReferenceSet.__table__, BusinessResourceReference.__table__]
            )
        )
    async with AsyncSession(engine) as session, session.begin():
        snapshot = await owner.aresolve_source(session, SourceReadRequest("assistant", "owned"), user)
        session.add(
            BusinessReferenceSet(
                tenant_id=101,
                source_type="assistant",
                source_id="owned",
                source_version="__root__",
                record_kind="root_guard",
                source_revision=4,
                extractor_version="root-guard-v1",
                digest=reference_set_digest(()),
                effective=False,
                ready=False,
            )
        )
        session.add(
            BusinessReferenceSet(
                tenant_id=101,
                source_type="assistant",
                source_id="owned",
                source_version="current",
                source_revision=3,
                extractor_version=snapshot.extractor_version,
                digest=reference_set_digest(snapshot.references),
                effective=True,
                ready=True,
            )
        )
        for ref in snapshot.references:
            session.add(
                BusinessResourceReference(
                    tenant_id=101,
                    source_type="assistant",
                    source_id="owned",
                    source_version="current",
                    slot_key=ref.slot_key,
                    target_type=ref.target.target_type.value,
                    target_id=ref.target.target_id,
                    target_tenant_id=101,
                    source_revision=3,
                )
            )
    verifier = SourceReadVerifier({"assistant": owner}, AuthenticatedSourceReadIdentity())

    class TargetBoundary:
        async def ainspect_source_targets(self, session, scope, keys, *, identity):
            await verifier.aassert_target_keys(
                session, scope, identity, keys, allowed_types={"model", "knowledge_space"}
            )
            return tuple(ReferenceTargetReadFact(key, "valid", True, 101) for key in keys)

        async def ainspect_transient_targets(self, *args, **kwargs):
            raise AssertionError("assistant has no preview admission")

    target = TargetBoundary()
    runtime = ReferenceSourceReadRuntime(
        verifier, SourceReadRepository(verifier), {"model": target, "knowledge_space": target}
    )
    monkeypatch.setattr(admission_module, "get_reference_read_runtime", AsyncMock(return_value=runtime))
    token = set_current_permission_actor(PermissionActor(user_id=user.user_id, current_tenant_id=101))
    return engine, user, token


async def test_actual_core_and_source_owner_share_business_configuration_and_transaction(source_db, monkeypatch):
    from bisheng.permission.application.identity import reset_current_permission_actor

    engine, user, token = await _actual_owner_runtime(source_db, monkeypatch)
    try:
        async with AsyncSession(engine) as session, session.begin():
            result = await AssistantExecutionAdmission.prepare(user, "owned", session=session)
            assert result.source_revision == 3 and result.root_revision == 4
            assert {ref.target.target_id for ref in result.snapshot.references} == {"7", "10"}
            assert not session.identity_map and session.in_transaction()
    finally:
        reset_current_permission_actor(token)


async def test_actual_core_refuses_unindexed_business_drift_instead_of_repairing_it(source_db, monkeypatch):
    from sqlalchemy import update

    from bisheng.database.models.assistant import Assistant
    from bisheng.permission.application.identity import reset_current_permission_actor

    engine, user, token = await _actual_owner_runtime(source_db, monkeypatch)
    try:
        async with AsyncSession(engine) as session, session.begin():
            await session.execute(
                update(Assistant).where(Assistant.id == "owned", Assistant.tenant_id == 101).values(model_name="8")
            )
            with pytest.raises(ReferenceCoverageNotReadyError):
                await AssistantExecutionAdmission.prepare(user, "owned", session=session)
            assert not session.identity_map
    finally:
        reset_current_permission_actor(token)
