"""T424: native Session reads retain the exact W3 scope and current-read gate.

覆盖 AC: AC-37, AC-68, AC-79, AC-83, AC-87, AC-89, AC-91, AC-92
Actual SQL/C3 and index rows; business/target ports are explicit protocol doubles.
"""

from copy import copy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine, select

from bisheng.common.errcode.knowledge import (
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.database.models.assistant import Assistant
from bisheng.resource_reference.application.contracts import reference_set_digest
from bisheng.resource_reference.application.source_contracts import ReadIdentityFacts, ReferenceTargetReadFact
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime
from bisheng.resource_reference.application.source_verification import SourceOwnerReadScope, SourceReadVerifier
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository
from test.knowledge_unification import test_source_read_scope as scopes

source_tenant = scopes.source_tenant


class NativeIdentity(scopes.IdentityPort):
    def capture(self, identity):
        return ReadIdentityFacts(_resolve_tenant_id(), (identity.credential, identity.request_nonce))


class NativeSource(scopes.SqlSourceOwner):
    def read(self, session, identity, *, lock):
        self.calls.append("root" if lock else "candidate")
        if not identity.allowed:
            raise ResourceReferenceInvalidError()
        statement = select(Assistant.id, Assistant.tenant_id, Assistant.model_name).where(Assistant.id == "assistant-a")
        if lock:
            statement = statement.with_for_update()
        with session.no_autoflush:
            row = session.exec(statement).one()
        return scopes.snapshot(tenant_id=row.tenant_id, model=row.model_name)

    def resolve_source(self, session, request, identity):
        return self.read(session, identity, lock=False)

    def revalidate_source(self, session, request, identity, expected):
        return self.read(session, identity, lock=True)


class NativeTargets(scopes.ReadTargetOwner):
    valid = True
    incomplete = False

    def inspect_source_targets(self, session, scope, keys, *, identity):
        self.calls.append("targets")
        if self.incomplete:
            return ()
        return tuple(
            ReferenceTargetReadFact(key, "valid" if self.valid else "invalid_deleted", self.valid, 101) for key in keys
        )


@pytest.fixture
def native():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        engine, tables=[Assistant.__table__, BusinessReferenceSet.__table__, BusinessResourceReference.__table__]
    )
    with Session(engine) as session:
        digest = reference_set_digest(scopes.REFS)
        session.add(Assistant(id="assistant-a", name="a", tenant_id=101, user_id=7, model_name="11"))
        base = dict(
            tenant_id=101,
            source_type="assistant",
            source_id="assistant-a",
            extractor_version="assistant-v1",
            digest=digest,
        )
        session.add(
            BusinessReferenceSet(
                **base,
                source_version="__root__",
                record_kind="root_guard",
                source_revision=4,
                ready=False,
                effective=False,
            )
        )
        session.add(
            BusinessReferenceSet(
                **base, source_version="current", record_kind="source", source_revision=3, ready=True, effective=True
            )
        )
        session.add(
            BusinessResourceReference(
                tenant_id=101,
                source_type="assistant",
                source_id="assistant-a",
                source_version="current",
                slot_key="model_name",
                target_type="model",
                target_id="11",
                target_tenant_id=101,
                source_revision=3,
            )
        )
        session.commit()
    owner = NativeSource()
    verifier = SourceReadVerifier({"assistant": owner}, NativeIdentity())
    target = NativeTargets(owner.calls)
    runtime = ReferenceSourceReadRuntime(verifier, SourceReadRepository(verifier), {"model": target})
    value = SimpleNamespace(
        engine=engine,
        owner=owner,
        verifier=verifier,
        target=target,
        runtime=runtime,
        identity=SimpleNamespace(credential="original", request_nonce="request", allowed=True),
    )
    try:
        yield value
    finally:
        engine.dispose()


def test_native_complete_targets_then_actual_root_then_current_index(native):
    ctx = native
    with Session(ctx.engine) as session:
        scope = ctx.verifier.issue_scope(session, scopes.REQUEST, ctx.identity)

        def current_read(state):
            if (
                state.is_select
                and state.statement._for_update_arg is not None
                and "business_reference_set" in str(state.statement)
            ):
                ctx.owner.calls.append("index")

        event.listen(session, "do_orm_execute", current_read)
        result = ctx.runtime.require_source_valid(session, scope, ctx.identity)
        assert ctx.owner.calls[:4] == ["candidate", "targets", "root", "index"]
        assert result.snapshot == scopes.snapshot() and result.source_revision == 3 and result.root_revision == 4
        assert not session.identity_map and not session.new and not session.dirty


@pytest.mark.parametrize("kind", ["copy", "equal_clone", "other_identity", "changed_identity", "commit", "bypass"])
def test_native_scope_original_identity_and_active_transaction(native, kind):
    ctx = native
    with Session(ctx.engine) as session:
        scope = ctx.verifier.issue_scope(session, scopes.REQUEST, ctx.identity)
        identity = ctx.identity
        if kind == "copy":
            scope = copy(scope)
        elif kind == "equal_clone":
            original = scope

            class EqualScope(SourceOwnerReadScope):
                def __hash__(self):
                    return hash(original)

                def __eq__(self, other):
                    return other is original or other is self

            scope = EqualScope(original.snapshot, original.purpose, original._nonce)
        elif kind == "other_identity":
            identity = copy(identity)
        elif kind == "changed_identity":
            identity.credential = "renewed"
        elif kind == "commit":
            session.commit()
        if kind == "bypass":
            with bypass_tenant_filter(), pytest.raises(ResourceReferenceInvalidError):
                ctx.runtime.require_source_valid(session, scope, identity)
        else:
            with pytest.raises(ResourceReferenceInvalidError):
                ctx.runtime.require_source_valid(session, scope, identity)
        assert ctx.owner.calls == ["candidate"]


def test_native_root_cannot_be_revalidated_without_actual_targets(native):
    with Session(native.engine) as session:
        scope = native.verifier.issue_scope(session, scopes.REQUEST, native.identity)
        with pytest.raises(ResourceReferenceInvalidError):
            native.verifier.revalidate_scope(session, scope, native.identity)
        assert native.owner.calls == ["candidate"]


def test_native_incomplete_targets_never_reach_root(native):
    native.target.incomplete = True
    with Session(native.engine) as session:
        scope = native.verifier.issue_scope(session, scopes.REQUEST, native.identity)
        with pytest.raises(ResourceReferenceInvalidError):
            native.runtime.require_source_valid(session, scope, native.identity)
        assert native.owner.calls == ["candidate", "targets"]


def test_native_execute_rejects_invalid_but_inspect_keeps_facts(native):
    native.target.valid = False
    with Session(native.engine) as session:
        scope = native.verifier.issue_scope(session, scopes.REQUEST, native.identity)
        with pytest.raises(ResourceReferenceInvalidError):
            native.runtime.require_source_valid(session, scope, native.identity)
    with Session(native.engine) as session:
        scope = native.verifier.issue_scope(session, replace(scopes.REQUEST, purpose="inspect"), native.identity)
        result = native.runtime.inspect_source(session, scope, native.identity)
        assert result.target_states[0].state == "invalid_deleted"


def test_native_inspection_cannot_be_reused_for_execution(native):
    with Session(native.engine) as session:
        scope = native.verifier.issue_scope(session, replace(scopes.REQUEST, purpose="inspect"), native.identity)
        with pytest.raises(ResourceReferenceInvalidError):
            native.runtime.require_source_valid(session, scope, native.identity)
        assert native.owner.calls == ["candidate"]


def test_native_missing_index_is_not_an_empty_source(native):
    with Session(native.engine) as session:
        row = session.exec(select(BusinessReferenceSet).where(BusinessReferenceSet.source_version == "current")).one()
        session.delete(row)
        session.commit()
        scope = native.verifier.issue_scope(session, scopes.REQUEST, native.identity)
        with pytest.raises(ReferenceCoverageNotReadyError):
            native.runtime.require_source_valid(session, scope, native.identity)
        assert native.owner.calls == ["candidate"]
