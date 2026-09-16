"""T057 — knowledge capability injection and fail-closed (AC-50 / AC-52).

Four claims, and each one has a way of being quietly false:

* **the whitelist comes from the platform.** The application sends a query and,
  at most, a narrowing subset of ids; nothing it sends can widen the scope. The
  test that matters names an id the access user *can* see and the application
  never declared, and requires a refusal.
* **reach = whitelist ∩ the access user's visible scope**, asserted as a set
  equality against what the same user gets retrieving on the platform — AC-50's
  "不多给不少给" is a set equation, so the test is one too.
* **no access user, no retrieval** — never the owner, never "everything
  declared", never a public subset. The interesting variants are "the header is
  absent" and "the token is present but does not verify".
* **a hosted application cannot reach the facade by another door.** The two
  faces that build an identity from a credential refuse this actor kind, so a
  face added later that forgets the bus fails closed rather than inheriting the
  owner's visibility.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bisheng.app_publish.domain.services import capability_bus_service
from bisheng.app_publish.domain.services.capability_bus_service import (
    CapabilityBusService,
    hosted_app_access_user,
    load_effective_declaration,
)
from bisheng.common.errcode.app_publish import AppCapabilityNotDeclaredError, AppCapabilityRevokedError
from bisheng.common.errcode.mcp_face import KnowledgeCapabilityRevokedError, RetrievalIdentityMissingError
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum

ACCESS_USER_ID = 93001


@pytest.fixture()
def recorded_retrievals(monkeypatch):
    """Replace the facade with a recorder that honours the whitelist it is given.

    The facade's own behaviour is F052's suite to prove; what this suite has to
    prove is which *arguments* reach it, so the double narrows exactly as the
    real one documents (``whitelist ∩ visible``) and records the call.
    """
    from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService

    calls: list[dict] = []
    visible = {"ids": set()}

    async def _retrieve(identity, req, *, version_repo=None):
        calls.append({"identity": identity, "req": req})
        if identity is None:
            raise RetrievalIdentityMissingError()
        scope = set(req.whitelist or []) & visible["ids"]
        if req.knowledge_ids:
            scope &= set(req.knowledge_ids)
        return SimpleNamespace(chunks=[], total=0, effective_scope=sorted(scope), truncated_params={})

    async def _from_user(user_id, tenant_id, **kwargs):
        return SimpleNamespace(actor=SimpleNamespace(subject_id=user_id), login_user=None)

    monkeypatch.setattr(RetrievalFacadeService, "retrieve", classmethod(lambda cls, *a, **k: _retrieve(*a, **k)))
    from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalIdentity

    monkeypatch.setattr(RetrievalIdentity, "from_user", classmethod(lambda cls, *a, **k: _from_user(*a, **k)))
    return SimpleNamespace(calls=calls, visible=visible)


async def _online_app_declaring(publish_db, app_factory, knowledge_refs):
    from bisheng.database.models.app_version import AppVersionDao

    app_row, version = await app_factory(state="online")
    async with publish_db() as session:
        row = await AppVersionDao.aget(session, app_row.id, version.id)
        row.capabilities = {"knowledge_bases": list(knowledge_refs)}
        session.add(row)
        await session.commit()
    return app_row


# ---------------------------------------------------------------------------
# The whitelist is the platform's (AC-50)
# ---------------------------------------------------------------------------


async def test_the_whitelist_is_the_declaration_the_application_never_supplies_it(
    publish_db, app_factory, knowledge_factory, recorded_retrievals
):
    declared = await knowledge_factory(name="产品手册")
    other = await knowledge_factory(name="财务档案")
    app_row = await _online_app_declaring(publish_db, app_factory, [{"id": str(declared.id)}])
    recorded_retrievals.visible["ids"] = {declared.id, other.id}

    result = await CapabilityBusService.retrieve(app_id=app_row.id, access_user_id=ACCESS_USER_ID, query="报销流程")

    assert recorded_retrievals.calls[0]["req"].whitelist == [declared.id]
    # The user can see both; through this application only the declared one.
    assert result.effective_scope == [declared.id]


async def test_a_knowledge_base_the_user_can_see_but_the_app_never_declared_is_refused(
    publish_db, app_factory, knowledge_factory, recorded_retrievals
):
    declared = await knowledge_factory(name="产品手册")
    undeclared = await knowledge_factory(name="财务档案")
    app_row = await _online_app_declaring(publish_db, app_factory, [{"id": str(declared.id)}])
    recorded_retrievals.visible["ids"] = {declared.id, undeclared.id}

    with pytest.raises(AppCapabilityNotDeclaredError) as excinfo:
        await CapabilityBusService.retrieve(
            app_id=app_row.id,
            access_user_id=ACCESS_USER_ID,
            query="报销流程",
            knowledge_ids=[undeclared.id],
        )

    assert excinfo.value.code == 16274
    # Refused before the facade ran: naming the capability is the whole point.
    assert recorded_retrievals.calls == []


async def test_a_declaration_by_name_resolves_and_an_ambiguous_one_does_not(publish_db, app_factory, knowledge_factory):
    unique = await knowledge_factory(name="产品手册")
    await knowledge_factory(name="重名库")
    await knowledge_factory(name="重名库")
    app_row = await _online_app_declaring(
        publish_db, app_factory, [{"name": "产品手册"}, {"name": "重名库"}, {"name": "不存在的库"}]
    )

    declaration = await load_effective_declaration(app_row.id)

    assert declaration.knowledge_whitelist == [unique.id]
    reasons = {one.label: one.reason for one in declaration.knowledge}
    assert reasons == {
        "产品手册": capability_bus_service.REASON_OK,
        "重名库": capability_bus_service.REASON_AMBIGUOUS,
        "不存在的库": capability_bus_service.REASON_REVOKED,
    }


async def test_a_declared_qa_library_is_not_retrievable(publish_db, app_factory, knowledge_factory):
    qa = await knowledge_factory(name="问答库", knowledge_type=KnowledgeTypeEnum.QA.value)
    app_row = await _online_app_declaring(publish_db, app_factory, [{"id": str(qa.id)}])

    declaration = await load_effective_declaration(app_row.id)

    # Unsupported type answers exactly like "gone" — telling the two apart would
    # let a declaration probe for knowledge bases the owner may not see.
    assert declaration.knowledge_whitelist == []
    assert declaration.knowledge[0].reason == capability_bus_service.REASON_REVOKED


# ---------------------------------------------------------------------------
# AC-50's set equality
# ---------------------------------------------------------------------------


async def test_the_reachable_set_equals_the_intersection_exactly(
    publish_db, app_factory, knowledge_factory, recorded_retrievals
):
    """AC-50 「不多给不少给」, written as the set equation it is."""
    declared_and_visible = await knowledge_factory(name="A")
    declared_not_visible = await knowledge_factory(name="B")
    visible_not_declared = await knowledge_factory(name="C")

    app_row = await _online_app_declaring(
        publish_db,
        app_factory,
        [{"id": str(declared_and_visible.id)}, {"id": str(declared_not_visible.id)}],
    )
    recorded_retrievals.visible["ids"] = {declared_and_visible.id, visible_not_declared.id}

    declaration = await load_effective_declaration(app_row.id)
    result = await CapabilityBusService.retrieve(app_id=app_row.id, access_user_id=ACCESS_USER_ID, query="任何问题")

    whitelist = set(declaration.knowledge_whitelist)
    user_visible = set(recorded_retrievals.visible["ids"])
    assert set(result.effective_scope) == whitelist & user_visible


# ---------------------------------------------------------------------------
# Fail-closed (AC-52)
# ---------------------------------------------------------------------------


async def test_no_access_user_means_refused_never_the_owner(
    publish_db, app_factory, knowledge_factory, recorded_retrievals
):
    declared = await knowledge_factory(name="产品手册")
    app_row = await _online_app_declaring(publish_db, app_factory, [{"id": str(declared.id)}])
    recorded_retrievals.visible["ids"] = {declared.id}

    with pytest.raises(RetrievalIdentityMissingError) as excinfo:
        await CapabilityBusService.retrieve(app_id=app_row.id, access_user_id=None, query="报销流程")

    assert excinfo.value.code == 26320
    # The facade was reached with no identity — that is the single implementation
    # of "no identity, no retrieval" — and it never fell back to a whitelist-wide
    # pass: nothing was returned.
    assert recorded_retrievals.calls[0]["identity"] is None


async def test_an_application_that_is_not_online_holds_no_capability(
    publish_db, app_factory, knowledge_factory, recorded_retrievals
):
    declared = await knowledge_factory(name="产品手册")
    app_row = await _online_app_declaring(publish_db, app_factory, [{"id": str(declared.id)}])
    from bisheng.database.models.app import AppDao

    async with publish_db() as session:
        row = await AppDao.aget(session, app_row.id)
        row.state = "stopped"
        session.add(row)
        await session.commit()

    with pytest.raises(AppCapabilityNotDeclaredError):
        await CapabilityBusService.retrieve(app_id=app_row.id, access_user_id=ACCESS_USER_ID, query="报销流程")
    assert recorded_retrievals.calls == []


def test_an_unverifiable_access_token_is_no_access_user(monkeypatch):
    """A forged, expired or wrong-application token must not degrade to "the app".

    ``hosted_app_access_user`` returns ``None``, which every caller turns into a
    refusal — the alternative, falling through to the application itself, would
    make attribution something the caller can steer by sending garbage.
    """
    from bisheng.open_api.domain.services import model_range_policy

    class RefusingVerifier:
        def verify(self, token, *, app_id, tenant_id):
            return None

    monkeypatch.setattr(model_range_policy, "_access_subject_verifier", RefusingVerifier())
    principal = SimpleNamespace(subject_ref="app-uuid", tenant_id=1)
    request = SimpleNamespace(headers={"X-BiSheng-Access-Token": "forged"})

    assert hosted_app_access_user(request, principal) is None
    assert hosted_app_access_user(SimpleNamespace(headers={}), principal) is None


def test_a_verified_token_names_the_visitor(monkeypatch):
    from bisheng.open_api.domain.services import model_range_policy

    class Verifier:
        def verify(self, token, *, app_id, tenant_id):
            assert (token, app_id, tenant_id) == ("signed", "app-uuid", 1)
            return model_range_policy.AccessSubject(user_id=ACCESS_USER_ID)

    monkeypatch.setattr(model_range_policy, "_access_subject_verifier", Verifier())
    principal = SimpleNamespace(subject_ref="app-uuid", tenant_id=1)

    assert hosted_app_access_user(SimpleNamespace(headers={"X-BiSheng-Access-Token": "signed"}), principal) == (
        ACCESS_USER_ID
    )


# ---------------------------------------------------------------------------
# No second door into the facade
# ---------------------------------------------------------------------------


def test_a_hosted_app_principal_cannot_build_a_facade_identity():
    """The structural half of AC-52.

    Without this, any face that builds an identity from the credential — today
    ``POST /api/v2/filelib/retrieve`` and the MCP search tool, tomorrow whatever
    is added next — would hand the application its *owner's* visibility with no
    whitelist at all, by omission rather than by decision.
    """
    from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalIdentity

    principal = SimpleNamespace(
        actor_kind="hosted_app",
        authorization_subject_type="user",
        authorization_subject_id=42,
        tenant_id=1,
        actor_id=5,
        actor_name="调研应用",
        effective_user_id=None,
        subject_ref="app-uuid",
    )

    with pytest.raises(RetrievalIdentityMissingError):
        RetrievalIdentity.from_open_api_principal(principal)


# ---------------------------------------------------------------------------
# Revocation surfaces as 16273 rather than as a quietly smaller search
# ---------------------------------------------------------------------------


async def test_a_deleted_declared_knowledge_base_becomes_16273_with_its_name(
    monkeypatch, publish_db, app_factory, knowledge_factory
):
    declared = await knowledge_factory(name="产品手册")
    app_row = await _online_app_declaring(publish_db, app_factory, [{"id": str(declared.id)}])

    from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalIdentity
    from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService

    async def _raise(identity, req, *, version_repo=None):
        raise KnowledgeCapabilityRevokedError(knowledge_id=declared.id)

    monkeypatch.setattr(RetrievalFacadeService, "retrieve", classmethod(lambda cls, *a, **k: _raise(*a, **k)))

    async def _from_user(user_id, tenant_id, **kwargs):
        return SimpleNamespace(actor=SimpleNamespace(subject_id=user_id), login_user=None)

    monkeypatch.setattr(RetrievalIdentity, "from_user", classmethod(lambda cls, *a, **k: _from_user(*a, **k)))

    with pytest.raises(AppCapabilityRevokedError) as excinfo:
        await CapabilityBusService.retrieve(app_id=app_row.id, access_user_id=ACCESS_USER_ID, query="报销流程")

    assert excinfo.value.code == 16273
    # The owner recognises the knowledge base's name, not the facade's numeric id.
    assert excinfo.value.capability == "产品手册"
    assert excinfo.value.reason == capability_bus_service.REASON_REVOKED
