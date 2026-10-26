"""T059 — dual-attribution recording of capability calls (AC-55).

AC-55 is one sentence with a sharp edge in the middle: actor = the application,
subject = the current access user, **and only a model call** may put 「应用自身」
in the subject slot — explicitly labelled, never as an absent value. Retrieval
with no access user is refused, so a retrieval record always names a person.

The tests are therefore in two halves: what this module writes (retrieval), and
what F051 already writes (models), which is asserted rather than duplicated.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlmodel import select

from bisheng.app_publish.domain.models.capability_call_record import (
    CAPABILITY_KNOWLEDGE,
    RESULT_REFUSED,
    RESULT_SUCCESS,
    AppCapabilityCallRecord,
)
from bisheng.app_publish.domain.services import capability_audit
from bisheng.app_publish.domain.services.capability_audit import (
    SUBJECT_KIND_APP_SELF,
    SUBJECT_KIND_USER,
    assert_model_attribution,
    record_retrieval,
)
from bisheng.app_publish.domain.services.capability_bus_service import CapabilityBusService
from bisheng.common.errcode.app_publish import AppCapabilityRevokedError
from bisheng.common.errcode.mcp_face import RetrievalIdentityMissingError

ACCESS_USER_ID = 93077


async def _records(publish_db) -> list[AppCapabilityCallRecord]:
    async with publish_db() as session:
        return list((await session.exec(select(AppCapabilityCallRecord))).all())


@pytest.fixture()
def fake_facade(monkeypatch):
    """A facade double that returns a fixed effective scope."""
    from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalIdentity
    from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService

    state = {"effective": [], "raise": None}

    async def _retrieve(identity, req, *, version_repo=None):
        if identity is None:
            raise RetrievalIdentityMissingError()
        if state["raise"] is not None:
            raise state["raise"]
        return SimpleNamespace(chunks=[], total=3, effective_scope=list(state["effective"]), truncated_params={})

    async def _from_user(user_id, tenant_id, **kwargs):
        return SimpleNamespace(actor=SimpleNamespace(subject_id=user_id), login_user=None)

    monkeypatch.setattr(RetrievalFacadeService, "retrieve", classmethod(lambda cls, *a, **k: _retrieve(*a, **k)))
    monkeypatch.setattr(RetrievalIdentity, "from_user", classmethod(lambda cls, *a, **k: _from_user(*a, **k)))
    return state


async def _online_app_declaring(publish_db, app_factory, knowledge_ids):
    from bisheng.database.models.app_version import AppVersionDao

    app_row, version = await app_factory(state="online", name="调研应用")
    async with publish_db() as session:
        row = await AppVersionDao.aget(session, app_row.id, version.id)
        row.capabilities = {"knowledge_bases": [{"id": str(one)} for one in knowledge_ids]}
        session.add(row)
        await session.commit()
    return app_row, version


# ---------------------------------------------------------------------------
# Retrieval — both attributions, every time
# ---------------------------------------------------------------------------


async def test_a_retrieval_records_the_app_as_actor_and_the_visitor_as_subject(
    publish_db, app_factory, knowledge_factory, fake_facade
):
    kb = await knowledge_factory(name="产品手册")
    app_row, version = await _online_app_declaring(publish_db, app_factory, [kb.id])
    fake_facade["effective"] = [kb.id]

    await CapabilityBusService.retrieve(app_id=app_row.id, access_user_id=ACCESS_USER_ID, query="报销流程")

    (record,) = await _records(publish_db)
    # Actor: the application, by uuid, with its display name alongside.
    assert (record.app_id, record.app_name) == (app_row.id, "调研应用")
    # Subject: the person, explicitly kinded.
    assert (record.subject_kind, record.subject_user_id) == (SUBJECT_KIND_USER, ACCESS_USER_ID)
    assert record.capability == CAPABILITY_KNOWLEDGE
    assert record.result == RESULT_SUCCESS
    assert record.version_id == version.id


async def test_the_record_carries_the_retrieval_target_not_the_question(
    publish_db, app_factory, knowledge_factory, fake_facade
):
    kb = await knowledge_factory(name="产品手册")
    other = await knowledge_factory(name="制度汇编")
    app_row, _version = await _online_app_declaring(publish_db, app_factory, [kb.id, other.id])
    fake_facade["effective"] = [kb.id]

    await CapabilityBusService.retrieve(
        app_id=app_row.id,
        access_user_id=ACCESS_USER_ID,
        query="社保基数怎么算",
        knowledge_ids=[kb.id],
    )

    (record,) = await _records(publish_db)
    assert record.targets == {"requested": [kb.id], "effective": [kb.id]}
    assert record.chunk_count == 3
    # The question itself is the user's, not the audit trail's.
    serialised = record.model_dump()
    assert "社保基数怎么算" not in str(serialised)


async def test_a_refusal_is_recorded_too_with_its_code(publish_db, app_factory, knowledge_factory, fake_facade):
    from bisheng.common.errcode.mcp_face import KnowledgeCapabilityRevokedError

    kb = await knowledge_factory(name="产品手册")
    app_row, _version = await _online_app_declaring(publish_db, app_factory, [kb.id])
    fake_facade["raise"] = KnowledgeCapabilityRevokedError(knowledge_id=kb.id)

    with pytest.raises(AppCapabilityRevokedError):
        await CapabilityBusService.retrieve(app_id=app_row.id, access_user_id=ACCESS_USER_ID, query="报销流程")

    (record,) = await _records(publish_db)
    assert (record.result, record.error_code) == (RESULT_REFUSED, 16273)
    assert record.subject_user_id == ACCESS_USER_ID


async def test_a_refusal_the_bus_itself_raises_is_recorded_like_any_other(
    publish_db, app_factory, knowledge_factory, fake_facade
):
    """Which layer said no must not decide whether the attempt is in the ledger.

    Naming an undeclared knowledge base is refused by the bus before the facade
    runs (16274). It is still a call this application made for this visitor, and
    "what did this app keep reaching for" is only answerable if it is recorded —
    a 26322 refusal raised one layer deeper already is.
    """
    from bisheng.common.errcode.app_publish import AppCapabilityNotDeclaredError

    kb = await knowledge_factory(name="产品手册")
    undeclared = await knowledge_factory(name="财务档案")
    app_row, _version = await _online_app_declaring(publish_db, app_factory, [kb.id])

    with pytest.raises(AppCapabilityNotDeclaredError):
        await CapabilityBusService.retrieve(
            app_id=app_row.id,
            access_user_id=ACCESS_USER_ID,
            query="报销流程",
            knowledge_ids=[undeclared.id],
            credential_id=4242,
        )

    (record,) = await _records(publish_db)
    assert (record.result, record.error_code) == (RESULT_REFUSED, 16274)
    assert record.targets == {"requested": [undeclared.id], "effective": []}
    assert (record.subject_kind, record.subject_user_id) == (SUBJECT_KIND_USER, ACCESS_USER_ID)
    # The key the application acted with — one per container start, so this is
    # what ties the row to the instance that produced it.
    assert record.credential_id == 4242
    # And the facade never ran: the refusal is the bus's own.
    assert fake_facade["effective"] == []


async def test_a_retrieval_with_no_access_user_is_refused_and_attributed_to_nobody(
    publish_db, app_factory, knowledge_factory, fake_facade
):
    """AC-55's sharp edge on the retrieval side.

    There is no subject to name, so there is no row — inventing one (the owner,
    the application, a zero) is exactly what the clause forbids. The refusal is
    not lost: the caller gets 26320.
    """
    kb = await knowledge_factory(name="产品手册")
    app_row, _version = await _online_app_declaring(publish_db, app_factory, [kb.id])

    with pytest.raises(RetrievalIdentityMissingError):
        await CapabilityBusService.retrieve(app_id=app_row.id, access_user_id=None, query="报销流程")

    assert await _records(publish_db) == []


async def test_recording_never_breaks_a_working_retrieval(
    monkeypatch, publish_db, app_factory, knowledge_factory, fake_facade
):
    kb = await knowledge_factory(name="产品手册")
    app_row, _version = await _online_app_declaring(publish_db, app_factory, [kb.id])
    fake_facade["effective"] = [kb.id]

    class Exploding:
        @classmethod
        async def ainsert(cls, session, row):
            raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(capability_audit, "AppCapabilityCallRecordDao", Exploding)

    result = await CapabilityBusService.retrieve(app_id=app_row.id, access_user_id=ACCESS_USER_ID, query="报销流程")

    assert result.total == 3
    assert await _records(publish_db) == []


async def test_the_table_is_insert_only(publish_db, app_factory, knowledge_factory, fake_facade):
    """No update path exists — a record of something that happened does not change."""
    from bisheng.app_publish.domain.models import capability_call_record

    dao_methods = {name for name in vars(capability_call_record.AppCapabilityCallRecordDao) if not name.startswith("_")}
    assert dao_methods == {"ainsert"}


# ---------------------------------------------------------------------------
# Models — F051 already writes the pair; this pins that it keeps doing so
# ---------------------------------------------------------------------------


def test_a_model_call_may_name_the_application_as_its_own_subject():
    """The one place 「应用自身」 is allowed — and it must say so explicitly."""
    record = SimpleNamespace(app_id="app-uuid", subject_kind=SUBJECT_KIND_APP_SELF, subject_id=None)

    assert_model_attribution(record)


def test_a_model_call_for_a_visitor_names_the_visitor():
    record = SimpleNamespace(app_id="app-uuid", subject_kind=SUBJECT_KIND_USER, subject_id=ACCESS_USER_ID)

    assert_model_attribution(record)


@pytest.mark.parametrize(
    "record",
    [
        SimpleNamespace(app_id="", subject_kind=SUBJECT_KIND_APP_SELF, subject_id=None),
        SimpleNamespace(app_id="app-uuid", subject_kind=None, subject_id=None),
        SimpleNamespace(app_id="app-uuid", subject_kind=SUBJECT_KIND_USER, subject_id=None),
    ],
    ids=["no actor", "unkinded subject", "a user subject with no user"],
)
def test_half_an_attribution_is_a_failure(record):
    with pytest.raises(AssertionError):
        assert_model_attribution(record)


async def test_the_model_face_stamps_the_pair_on_its_own_records():
    """The real writer, not a double: F051's policy decides both halves.

    Without an access token the subject is 「应用自身」; with a verified one it is
    the visitor. Either way the actor is the application's **uuid** — the field
    a per-application query reads (F055 T055 note ①).
    """
    from bisheng.open_api.domain.services import model_range_policy
    from bisheng.open_api.domain.services.model_range_policy import (
        ACCESS_TOKEN_HEADER,
        AccessSubject,
        resolve_range_and_subject,
    )
    from test.open_api.model_gateway_fixtures import hosted_app_principal

    class Port:
        async def declared_model_names(self, app_id, tenant_id):
            return frozenset({"qwen-max"})

    class Verifier:
        def verify(self, token, *, app_id, tenant_id):
            return AccessSubject(user_id=ACCESS_USER_ID)

    previous = (
        model_range_policy.get_hosted_app_declaration_port(),
        model_range_policy.get_access_subject_verifier(),
    )
    model_range_policy.register_hosted_app_declaration_port(Port())
    model_range_policy.register_access_subject_verifier(Verifier())
    try:
        principal = hosted_app_principal()
        _range, app_self = await resolve_range_and_subject(principal, {})
        _range, for_user = await resolve_range_and_subject(principal, {ACCESS_TOKEN_HEADER: "signed"})
    finally:
        model_range_policy.register_hosted_app_declaration_port(previous[0])
        model_range_policy.register_access_subject_verifier(previous[1])

    assert_model_attribution(
        SimpleNamespace(app_id=app_self.app_id, subject_kind=app_self.subject_kind, subject_id=app_self.subject_id)
    )
    assert_model_attribution(
        SimpleNamespace(app_id=for_user.app_id, subject_kind=for_user.subject_kind, subject_id=for_user.subject_id)
    )
    assert app_self.subject_kind == SUBJECT_KIND_APP_SELF
    assert (for_user.subject_kind, for_user.subject_id) == (SUBJECT_KIND_USER, ACCESS_USER_ID)
    assert app_self.app_id == principal.subject_ref


async def test_record_retrieval_writes_nothing_it_was_not_given(publish_db, app_factory):
    """The writer's own contract, independent of the bus."""
    app_row, _version = await app_factory(state="online", name="调研应用")

    await record_retrieval(
        app_id=app_row.id,
        app_name="调研应用",
        tenant_id=app_row.tenant_id,
        version_id=None,
        access_user_id=ACCESS_USER_ID,
        requested=None,
        effective=[5, 6],
        latency_ms=12,
    )

    (record,) = await _records(publish_db)
    assert record.targets == {"requested": [], "effective": [5, 6]}
    assert record.latency_ms == 12
    assert record.error_code is None
