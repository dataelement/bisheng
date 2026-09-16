"""F052 T104 — the "same set, whichever door" claims, at the layer that can prove them.

覆盖 AC: AC-08, AC-19, AC-41, AC-43

"The facade returns exactly the set this identity would see searching the
platform itself" is ultimately a claim about OpenFGA, Milvus and Elasticsearch
agreeing, and the full sample (AC-40 / AC-42 / AC-44) therefore belongs to the
CI middleware stage — see the module note at the bottom for what it must seed
and assert, and design §7 ③ for the 114 walkthrough that substitutes for it.

What *is* provable here, and is where the equality would actually break, is the
seam: the identity each caller hands the facade. Two callers that build the same
``RetrievalIdentity`` and pass the same request cannot see different sets,
because below that seam there is one implementation. So these tests pin the
seam — plus the structural fact that nothing on this path can touch a session.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import MagicMock

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
# Still owed to the CI middleware stage (AC-40, AC-42, AC-44)
# ---------------------------------------------------------------------------
#
# The store-level set equality is NOT asserted in this file, and deliberately
# not stubbed either: a skipped-or-NotImplemented test reads as coverage while
# proving nothing. What the middleware stage has to seed and assert:
#
#   sample — service account SA1 granted space S1 (file f1 visible, f2 revoked
#   individually, f3 inside an unauthorised folder, f4 detached by a custom
#   permission mode) plus document library L1; space S2 granted to nobody;
#   natural person U1 granted identically.
#
#   AC-40  facade(SA1) chunks are exactly those of f1 plus those of L1, and no
#          others; naming S2 answers 26321.
#   AC-41  the same key through POST /api/v2/filelib/retrieve and through the
#          MCP search tool yields the same chunk set for the same query.
#   AC-42  from_user(U1) + whitelist=[S1] equals U1's own in-platform search
#          restricted to S1, f2 / f3 / f4 absent from both.
#   AC-44  with OpenFGA stopped: facade, v2 and the MCP tool each raise
#          19002 / 19201 and return zero chunks — never a shorter list.
#
# Seeding helpers for the four permission-source variants do not exist yet;
# they are the actual blocker, not the assertions.
