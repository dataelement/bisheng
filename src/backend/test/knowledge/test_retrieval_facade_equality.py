"""F052 T104 — the "same set, whichever door" claims, at the layer that can prove them.

覆盖 AC: AC-08, AC-19, AC-41, AC-43, AC-44

"The facade returns exactly the set this identity would see searching the
platform itself" is ultimately a claim about OpenFGA, Milvus and Elasticsearch
agreeing, and the seeded sample (AC-40 / AC-42) therefore belongs to the CI
middleware stage — see the module note at the bottom for what it must seed and
assert, and design §7 ③ for the 114 walkthrough that substitutes for it.

What *is* provable here, and is where the equality would actually break, is the
seam: the identity each caller hands the facade. Two callers that build the same
``RetrievalIdentity`` and pass the same request cannot see different sets,
because below that seam there is one implementation. So these tests pin the
seam — plus the structural fact that nothing on this path can touch a session,
plus AC-44's fail-closed behaviour at each of the three doors that AC names
(MCP search tool, v2 ``POST /filelib/retrieve``, hosted runtime), which is
decided in this path rather than in the store.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalIdentity
from bisheng.knowledge.domain.services import retrieval_facade_service as facade_mod
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.permission.application.identity import get_current_permission_actor


def _principal(**overrides) -> OpenApiPrincipal:
    payload = {
        "credential_id": 3,
        "actor_kind": "service_account",
        "actor_id": 7,
        "actor_name": "dev-agent",
        "tenant_id": 1,
        "resource_owner_user_id": 11,
        "scopes": frozenset({"knowledge:read"}),
        "authorization_subject_type": "service_account",
        "authorization_subject_id": 7,
        "effective_user_id": None,
    }
    payload.update(overrides)
    return OpenApiPrincipal(**payload)


# ---------------------------------------------------------------------------
# AC-41 — one key, two doors, one set
# ---------------------------------------------------------------------------


def test_every_open_face_caller_builds_the_identity_the_same_way():
    """The v2 endpoint must not hand-roll an identity of its own.

    If it ever constructs a ``PermissionActor`` or a ``UserPayload`` directly,
    the MCP tool and v2 can drift apart while both still "use the facade" —
    which is precisely the divergence AC-41 exists to prevent.
    """

    import bisheng.open_endpoints.api.endpoints.filelib as filelib_mod

    source = Path(filelib_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    endpoint = next(
        node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "retrieve_chunks"
    )
    called = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        for node in ast.walk(endpoint)
        if isinstance(node, ast.Call)
    }
    assert "from_open_api_principal" in called
    assert "PermissionActor" not in called, "the endpoint must not build its own actor"
    assert "UserPayload" not in called, "the endpoint must not build its own login user"


def test_identity_from_the_same_principal_is_equal():
    """Same credential in, same execution identity out — every time."""

    principal = _principal()
    first = RetrievalIdentity.from_open_api_principal(principal)
    second = RetrievalIdentity.from_open_api_principal(principal)

    assert first.actor == second.actor
    assert (first.login_user.user_id, first.login_user.tenant_id) == (
        second.login_user.user_id,
        second.login_user.tenant_id,
    )


async def test_the_two_open_doors_hand_the_facade_the_very_same_call(monkeypatch):
    """AC-41 at the seam: one key, one query — v2 and the MCP tool call identically.

    The static guard above says the endpoint does not *build* its own identity.
    This one goes further and compares what the two doors actually pass: equal
    ``RetrievalIdentity`` and equal ``RetrievalRequest`` means the set below
    cannot differ, because below that seam there is one implementation. Stores
    are not involved, so this holds without middleware; the seeded set equality
    over real Milvus/ES stays owed to CI (module note at the bottom).

    ``whitelist`` is part of the comparison on purpose: a developer key's range
    is what an administrator granted it, and a face that started declaring one
    would narrow that key on its own door only.
    """

    from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalFacadeResult
    from bisheng.open_api.domain.context import (
        reset_current_open_api_principal,
        set_current_open_api_principal,
    )
    from bisheng.open_api.mcp.tools import knowledge as mcp_knowledge
    from bisheng.open_endpoints.api.endpoints import filelib as filelib_mod
    from bisheng.open_endpoints.domain.schemas.filelib import RetrieveReq

    calls: list[tuple] = []

    async def retrieve(identity, req, **_kwargs):
        calls.append((identity, req))
        return RetrievalFacadeResult()

    monkeypatch.setattr(facade_mod.RetrievalFacadeService, "retrieve", retrieve)

    principal = _principal()
    monkeypatch.setattr(filelib_mod, "get_current_open_api_principal", lambda: principal)
    await filelib_mod.retrieve_chunks(
        request=MagicMock(),
        req=RetrieveReq(query="how do I deploy", knowledge_base_ids=[8], top_k=10, max_content=15000),
        version_repo=MagicMock(),
    )

    token = set_current_open_api_principal(principal)
    try:
        await mcp_knowledge.bisheng_knowledge_search(
            query="how do I deploy", knowledge_ids=[8], top_k=10, max_content=15000
        )
    finally:
        reset_current_open_api_principal(token)

    assert len(calls) == 2
    (v2_identity, v2_request), (mcp_identity, mcp_request) = calls
    assert v2_identity.actor == mcp_identity.actor
    assert v2_identity.login_user == mcp_identity.login_user
    assert v2_request == mcp_request
    assert v2_request.whitelist is None and mcp_request.whitelist is None


# ---------------------------------------------------------------------------
# AC-43 — delegated mode is pure substitution
# ---------------------------------------------------------------------------


def test_mode_d_identity_is_the_represented_user_and_nothing_else():
    """No residue of the delegating service account, and no privilege added."""

    delegated = RetrievalIdentity.from_open_api_principal(
        _principal(mode="D", authorization_subject_type="user", authorization_subject_id=42, effective_user_id=42)
    )

    assert (delegated.actor.subject_type, delegated.actor.subject_id) == ("user", 42)
    assert delegated.login_user.user_id == 42
    assert delegated.actor.super_admin is False
    assert delegated.actor.tenant_admin_tenant_ids == frozenset()
    assert delegated.login_user.is_global_super is False


def test_service_account_identity_can_never_be_an_administrator():
    """坑 7 / F049 AC-22: a leaked key must not reach the admin shortcut."""

    identity = RetrievalIdentity.from_open_api_principal(_principal())

    assert identity.actor.subject_type == "service_account"
    assert identity.actor.super_admin is False
    assert identity.actor.tenant_admin_tenant_ids == frozenset()


def test_identity_keeps_the_gates_data_scope_narrowing():
    """F066: a narrowed personal token must stay narrowed inside the facade.

    The narrowing lives in the permission runtime and is keyed off
    ``actor.data_scope``; the facade installs ``identity.actor`` over whatever
    the gate left, so an actor rebuilt here with the default ``all`` scope does
    not merely lose a hint — it **widens** what the credential can retrieve,
    silently and on a live endpoint.
    """

    from bisheng.permission.application.data_scope import DATA_SCOPE_PERSONAL
    from bisheng.permission.application.identity import (
        reset_current_permission_actor,
        set_current_permission_actor,
    )
    from bisheng.permission.domain.services.permission_action_service import PermissionActor

    principal = _principal(
        actor_kind="natural_person",
        actor_id=42,
        authorization_subject_type="user",
        authorization_subject_id=42,
        effective_user_id=42,
    )
    gate_actor = PermissionActor(
        subject_type="user",
        subject_id=42,
        tenant_id=1,
        data_scope=DATA_SCOPE_PERSONAL,
    )

    token = set_current_permission_actor(gate_actor)
    try:
        identity = RetrievalIdentity.from_open_api_principal(principal)
    finally:
        reset_current_permission_actor(token)

    assert identity.actor.data_scope == DATA_SCOPE_PERSONAL


def test_identity_keeps_the_gates_administrator_facts():
    """design 坑 8: administrator facts come from the installed actor.

    Re-deriving them as ``False`` narrows an administrator's personal token,
    which breaks the "same set through either door" claim (AC-41 / AC-43) in
    the quiet direction — fewer results, no error.
    """

    from bisheng.permission.application.identity import (
        reset_current_permission_actor,
        set_current_permission_actor,
    )
    from bisheng.permission.domain.services.permission_action_service import PermissionActor

    principal = _principal(
        actor_kind="natural_person",
        actor_id=42,
        authorization_subject_type="user",
        authorization_subject_id=42,
        effective_user_id=42,
    )
    gate_actor = PermissionActor(
        subject_type="user",
        subject_id=42,
        tenant_id=1,
        tenant_admin_tenant_ids=frozenset({1}),
    )

    token = set_current_permission_actor(gate_actor)
    try:
        identity = RetrievalIdentity.from_open_api_principal(principal)
    finally:
        reset_current_permission_actor(token)

    assert identity.actor.tenant_admin_tenant_ids == frozenset({1})


def test_identity_never_adopts_an_actor_for_a_different_subject():
    """Adoption is keyed on the subject, so an unrelated actor cannot leak in."""

    from bisheng.permission.application.identity import (
        reset_current_permission_actor,
        set_current_permission_actor,
    )
    from bisheng.permission.domain.services.permission_action_service import PermissionActor

    someone_else = PermissionActor(
        subject_type="user",
        subject_id=999,
        tenant_id=1,
        super_admin=True,
    )

    token = set_current_permission_actor(someone_else)
    try:
        identity = RetrievalIdentity.from_open_api_principal(_principal())
    finally:
        reset_current_permission_actor(token)

    assert (identity.actor.subject_type, identity.actor.subject_id) == ("service_account", 7)
    assert identity.actor.super_admin is False


async def test_from_user_does_not_inherit_the_ambient_actor():
    """AC-42: the hosted runtime's access user is not the application.

    ``resolve_permission_actor`` returns the ContextVar's actor when one is
    installed (design 坑 5), and F055 reaches this constructor inside a request
    authenticated with the application's own credential. Inheriting it would
    hand the access user the application's visibility — the exact widening the
    hosted-runtime promise rules out.
    """

    from bisheng.permission.application.identity import (
        reset_current_permission_actor,
        set_current_permission_actor,
    )
    from bisheng.permission.domain.services.permission_action_service import PermissionActor

    app_actor = PermissionActor(subject_type="service_account", subject_id=7, tenant_id=1)

    token = set_current_permission_actor(app_actor)
    try:
        # tenant 1 is the default tenant, so no tenant-admin round trip happens.
        identity = await RetrievalIdentity.from_user(42, 1)
        assert get_current_permission_actor() is app_actor, "the ambient actor must be restored"
    finally:
        reset_current_permission_actor(token)

    assert (identity.actor.subject_type, identity.actor.subject_id) == ("user", 42)


def test_from_user_does_not_assume_administrator_facts():
    """F055 hands the facade a real user; the facts come from the permission layer."""

    signature = inspect.signature(RetrievalIdentity.from_user)
    assert "data_scope" in signature.parameters
    source = inspect.getsource(RetrievalIdentity.from_user)
    assert "resolve_permission_actor" in source, "administrator facts must be resolved, not assumed"
    assert "is_global_super=False" in source


# ---------------------------------------------------------------------------
# AC-08 / AC-19 — the retrieval path cannot touch a session
# ---------------------------------------------------------------------------


def test_retrieval_path_imports_no_session_modules():
    facade_path = Path(facade_mod.__file__)
    paths = [facade_path, facade_path.with_name("retrieval_engine.py")]

    forbidden = ("chat_session", "models.message", "models.session", "knowledge_space_chat_service")
    offenders: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders.extend(f"{path.name}:{node.lineno}:{name}" for name in names if any(t in name for t in forbidden))

    assert not offenders, f"the retrieval path must stay session-decoupled: {offenders}"


def test_facade_never_receives_a_request_object():
    """AC-19 is structural, not a convention: there is no place to put one."""

    for name in ("retrieve", "list_accessible_knowledge", "check_reachable"):
        parameters = inspect.signature(getattr(facade_mod.RetrievalFacadeService, name)).parameters
        assert "request" not in parameters, f"{name} must not take a Request"

    engine_params = inspect.signature(facade_mod.RetrievalEngine.__init__).parameters
    assert "request" not in engine_params


def test_facade_does_not_cache_visibility():
    """design 坑 23 red line: any TTL cache breaks INV-28 and INV-30.

    Phrased as a guard rather than a comment because a cache is exactly the
    "obvious optimisation" a future reader adds without re-deriving why the
    five-second revocation bound forbids it.
    """

    source = Path(facade_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    suspicious = {"lru_cache", "cached_property", "cache", "TTLCache", "aiocache"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = {alias.name.rsplit(".", 1)[-1] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            names = {alias.name for alias in node.names}
        else:
            continue
        overlap = names & suspicious
        assert not overlap, (
            f"the facade must not cache visibility decisions ({sorted(overlap)}): "
            "answer 'what happens to the 5s revocation bound' first — design 坑 23"
        )


def test_engine_is_constructed_per_retrieval_not_shared():
    """A shared engine would carry one identity's visibility service into another."""

    source = inspect.getsource(facade_mod.RetrievalFacadeService.retrieve)
    assert "RetrievalEngine(identity.login_user" in source


def test_chunk_carries_enough_to_cite(monkeypatch):
    """AC-19: the result has to be traceable back to a file, not just text."""

    row = MagicMock()
    row.id = 8
    row.type = 3
    row.name = "Handbook"
    doc = MagicMock()
    doc.page_content = "body"
    doc.metadata = {
        "document_id": 10,
        "document_name": "a.pdf",
        "chunk_index": 2,
        "document_update_time": "2026-09-16 08:30:00",
    }

    chunk = facade_mod.RetrievalFacadeService._to_chunk(row, doc)

    assert (chunk.knowledge_id, chunk.knowledge_name, chunk.knowledge_type) == (8, "Handbook", 3)
    assert (chunk.document_id, chunk.document_name, chunk.chunk_index) == (10, "a.pdf", 2)
    assert chunk.document_update_time == "2026-09-16 08:30:00"


# ---------------------------------------------------------------------------
# AC-44 — a permission outage is fail-closed at every door, not just one
# ---------------------------------------------------------------------------


async def _facade_door(identity, knowledge_ids):
    from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalRequest

    return await facade_mod.RetrievalFacadeService.retrieve(
        identity, RetrievalRequest(query="q", knowledge_ids=knowledge_ids)
    )


async def _v2_door(knowledge_ids, monkeypatch):
    from bisheng.open_endpoints.api.endpoints import filelib as filelib_mod
    from bisheng.open_endpoints.domain.schemas.filelib import RetrieveReq

    monkeypatch.setattr(filelib_mod, "get_current_open_api_principal", lambda: _principal())
    return await filelib_mod.retrieve_chunks(
        request=MagicMock(),
        req=RetrieveReq(query="q", knowledge_base_ids=knowledge_ids),
        version_repo=MagicMock(),
    )


async def _mcp_door(knowledge_ids, monkeypatch):
    from bisheng.open_api.domain.context import (
        reset_current_open_api_principal,
        set_current_open_api_principal,
    )
    from bisheng.open_api.mcp.tools import knowledge as mcp_knowledge

    token = set_current_open_api_principal(_principal())
    try:
        return await mcp_knowledge.bisheng_knowledge_search(query="q", knowledge_ids=knowledge_ids)
    finally:
        reset_current_open_api_principal(token)


async def _hosted_runtime_door(knowledge_ids, monkeypatch):
    """A hosted application retrieving for its visitor — AC-44's third named door.

    It is the one door that does not call the facade directly: F055 routes it
    through ``CapabilityBusService``, which wraps the call in
    ``except BaseErrorCode`` because every refusal still owes the capability
    ledger a row (AC-55). That handler is precisely where "log it and return
    what we have" gets written by someone tidying up, so leaving this door out
    would exempt the only place the regression could actually be introduced.

    Only the two collaborators that need a database are doubled — the
    declaration read and the ledger write. The facade underneath is the real
    one, so the outage travels the real path.
    """

    from bisheng.app_publish.domain.services import capability_audit
    from bisheng.app_publish.domain.services.capability_bus_service import (
        CapabilityBusService,
        DeclaredKnowledge,
        EffectiveDeclaration,
    )

    declaration = EffectiveDeclaration(
        app_id="app-fail-closed",
        tenant_id=1,
        version_id="v1",
        app_name="报销助手",
        knowledge=tuple(DeclaredKnowledge(label=str(one), knowledge_id=one) for one in knowledge_ids),
    )

    async def require_declaration(_app_id):
        return declaration

    async def record_retrieval(**_kwargs):
        return None

    monkeypatch.setattr(CapabilityBusService, "_require_declaration", staticmethod(require_declaration))
    monkeypatch.setattr(capability_audit, "record_retrieval", record_retrieval)

    return await CapabilityBusService.retrieve(
        app_id=declaration.app_id,
        access_user_id=42,
        query="q",
        knowledge_ids=list(knowledge_ids),
    )


_DOORS = {
    "facade": lambda identity, ids, monkeypatch: _facade_door(identity, ids),
    "v2": lambda identity, ids, monkeypatch: _v2_door(ids, monkeypatch),
    "mcp": lambda identity, ids, monkeypatch: _mcp_door(ids, monkeypatch),
    "hosted_runtime": lambda identity, ids, monkeypatch: _hosted_runtime_door(ids, monkeypatch),
}


@pytest.mark.parametrize("door", sorted(_DOORS))
async def test_a_permission_outage_returns_an_error_and_zero_chunks_at_every_door(
    door, monkeypatch, fake_engine, knowledge_rows
):
    """The engine must never run when visibility could not be decided.

    Returning "what we managed to check" is the dangerous shape here: it is a
    *shorter* list, indistinguishable from a legitimately narrow grant, so the
    over-disclosure never looks like a failure. Asserted at the three doors
    AC-44 names — the MCP search tool, v2 ``POST /filelib/retrieve`` and the
    hosted runtime — plus the facade itself, because a fail-closed facade with
    one door that catches the exception and degrades is exactly the regression
    this AC is about.

    The fault is injected where the outage actually surfaces —
    ``batch_check_business_actions`` raising ``PermissionServiceUnavailableError``
    is what a stopped OpenFGA produces. Stopping the real engine (and the seeded
    sample behind it) stays with the CI middleware stage; what that adds is the
    store's behaviour, not this path's.
    """

    from bisheng.common.errcode.permission import PermissionServiceUnavailableError

    knowledge_rows(8)

    async def outage(*_args, **_kwargs):
        raise PermissionServiceUnavailableError()

    monkeypatch.setattr(facade_mod, "batch_check_business_actions", outage)
    identity = RetrievalIdentity.from_open_api_principal(_principal())

    with pytest.raises(PermissionServiceUnavailableError):
        await _DOORS[door](identity, [8], monkeypatch)

    assert not [engine for engine in fake_engine.instances if engine.calls], (
        "the retrieval engine ran while visibility was undecidable — "
        "an unfiltered or partially filtered result is exactly what AC-44 forbids"
    )


# ---------------------------------------------------------------------------
# The store-level half (AC-40, AC-42) lives where it can actually run
# ---------------------------------------------------------------------------
#
# Set equality over real Milvus/ES is NOT asserted in this file, and
# deliberately not stubbed either: a skipped-or-NotImplemented test reads as
# coverage while proving nothing. It is written out in full — sample and
# assertions — in ``test/e2e/test_e2e_f052_retrieval_set_equality.py``, whose
# sample the helper ``test/e2e/helpers/retrieval_sample.py`` seeds:
#
#   sample — service account SA1 granted space S1 (file f1 reachable; f2 CUSTOM
#   at the file, an individual revocation; f3 inside folder D1, which detached;
#   f4 CUSTOM under an authorised folder) plus document library L1; space S2
#   granted to nobody; natural person U1 granted identically, holding a PAT.
#
#   AC-40  the open face returns exactly f1's chunks plus L1's, and no others;
#          naming S2 answers 26321 instead of a quietly shorter list.
#   AC-41  the same key through POST /api/v2/filelib/retrieve and through the
#          MCP search tool yields the same (document_id, chunk_index) set.
#   AC-42  U1's PAT through the open face equals what U1 browses in S1 with
#          their own session; f2 / f3 / f4 absent from both.
#   AC-44  with OpenFGA actually stopped: v2 and the MCP tool each answer
#          19002 / 19201 with zero chunks. The *decision* is asserted above by
#          fault injection at all four doors; what a stopped engine adds is
#          that the permission layer really does raise rather than time out
#          into an empty allow-map, which cannot be checked without it.
#
# That suite is ``@pytest.mark.e2e`` and skipped unless ``F052_E2E=1``; it needs
# a deployment with MySQL + Redis + OpenFGA + MinIO + Milvus/ES **and a running
# knowledge Celery worker**, because an unindexed sample makes every set
# trivially empty.
