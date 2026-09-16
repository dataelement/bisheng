"""F052 T103a — v2 ``POST /filelib/retrieve`` runs on the unified facade.

覆盖 AC: AC-11, AC-24, AC-25, AC-26, AC-43, AC-44

The request and response **shapes** are unchanged (AC-25). What changes is the
error vocabulary: the three old distinguishable "you can't have that knowledge
base" answers (404 NotFoundError / 403 SpacePermissionDeniedError / 10962
unsupported type) collapse into one 26321, because a caller that can tell them
apart can enumerate knowledge bases it may not see.
"""

from unittest.mock import MagicMock

import pytest

from bisheng.common.errcode.mcp_face import KnowledgeUnreachableError
from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.knowledge.domain.schemas.retrieval_facade import (
    RetrievalChunk,
    RetrievalFacadeResult,
)
from bisheng.open_api.domain.context import (
    OpenApiPrincipal,
)
from bisheng.open_endpoints.api.endpoints import filelib as filelib_mod
from bisheng.open_endpoints.domain.schemas.filelib import RetrieveReq, RetrieveResp


def _service_account_principal() -> OpenApiPrincipal:
    return OpenApiPrincipal(
        credential_id=3,
        actor_kind="service_account",
        actor_id=7,
        actor_name="dev-agent",
        tenant_id=1,
        resource_owner_user_id=11,
        scopes=frozenset({"knowledge:read"}),
        authorization_subject_type="service_account",
        authorization_subject_id=7,
        effective_user_id=None,
    )


def _delegated_principal() -> OpenApiPrincipal:
    return OpenApiPrincipal(
        credential_id=3,
        actor_kind="service_account",
        actor_id=7,
        actor_name="dev-agent",
        tenant_id=1,
        resource_owner_user_id=11,
        scopes=frozenset({"knowledge:read", "delegate"}),
        mode="D",
        authorization_subject_type="user",
        authorization_subject_id=42,
        effective_user_id=42,
        on_behalf_of_user_id=42,
    )


@pytest.fixture
def facade_spy(monkeypatch):
    """Capture what the endpoint hands the facade, and what it does with the result."""

    calls: list[dict] = []
    outcome: dict = {
        "result": RetrievalFacadeResult(
            chunks=[
                RetrievalChunk(
                    knowledge_id=8,
                    knowledge_type=3,
                    knowledge_name="Handbook",
                    document_id=10,
                    document_name="a.pdf",
                    chunk_index=2,
                    content="body",
                    document_update_time="2026-09-16 08:30:00",
                )
            ],
            total=1,
            effective_scope=[8],
        )
    }

    async def retrieve(identity, req, **kwargs):
        calls.append({"identity": identity, "req": req, "kwargs": kwargs})
        if "raises" in outcome:
            raise outcome["raises"]
        return outcome["result"]

    monkeypatch.setattr(filelib_mod.RetrievalFacadeService, "retrieve", retrieve)
    holder = MagicMock()
    holder.calls = calls
    holder.outcome = outcome
    return holder


@pytest.fixture
def as_principal(monkeypatch):
    """Stand in for the v2 gate, which installs the principal ContextVar.

    Patched rather than set for real: pytest-asyncio runs each coroutine in its
    own context, so a token taken in a sync fixture cannot be reset in one.
    """

    def install(principal: OpenApiPrincipal | None):
        monkeypatch.setattr(filelib_mod, "get_current_open_api_principal", lambda: principal)
        return principal

    return install


async def _call(req: RetrieveReq):
    return await filelib_mod.retrieve_chunks(request=MagicMock(), req=req, version_repo=MagicMock())


# ---------------------------------------------------------------------------
# AC-25 / AC-43 — the identity the endpoint builds
# ---------------------------------------------------------------------------


async def test_endpoint_builds_identity_from_principal_mode_s(facade_spy, as_principal):
    as_principal(_service_account_principal())

    await _call(RetrieveReq(query="q", knowledge_base_ids=[8]))

    identity = facade_spy.calls[0]["identity"]
    assert identity.actor.subject_type == "service_account"
    assert identity.actor.subject_id == 7
    # 坑 8: no init_login_user round trip, and never an administrator by default.
    assert identity.login_user.is_global_super is False


async def test_endpoint_mode_d_identity_is_target_user(facade_spy, as_principal):
    """AC-43 — the capability; mode D's admission and acceptance belong to F050."""

    as_principal(_delegated_principal())

    await _call(RetrieveReq(query="q", knowledge_base_ids=[8]))

    identity = facade_spy.calls[0]["identity"]
    assert (identity.actor.subject_type, identity.actor.subject_id) == ("user", 42)
    assert identity.login_user.user_id == 42


async def test_endpoint_forwards_query_targets_and_tag_filters(facade_spy, as_principal):
    as_principal(_service_account_principal())

    await _call(
        RetrieveReq(
            query="what is the policy",
            knowledge_base_ids=[8, 9],
            filters={"knowledge_base_filters": [{"knowledge_base_id": 8, "tags": ["hr"], "tag_match_mode": "ANY"}]},
            top_k=25,
            max_content=1234,
        )
    )

    req = facade_spy.calls[0]["req"]
    assert req.query == "what is the policy"
    assert req.knowledge_ids == [8, 9]
    assert req.tag_filters == {8: ["hr"]}
    assert (req.top_k, req.max_content) == (25, 1234)
    # No declared scope on the open API face — that is F055's input, not v2's.
    assert req.whitelist is None


# ---------------------------------------------------------------------------
# AC-25 — the contract shape is untouched
# ---------------------------------------------------------------------------


async def test_response_shape_unchanged(facade_spy, as_principal):
    as_principal(_service_account_principal())

    response = await _call(RetrieveReq(query="q", knowledge_base_ids=[8]))

    payload = response.data
    assert isinstance(payload, RetrieveResp)
    assert set(payload.model_dump()) == {"chunks", "total"}
    assert set(payload.chunks[0].model_dump()) == {
        "content",
        "knowledge_id",
        "document_id",
        "document_name",
        "chunk_index",
        "document_update_time",
    }
    assert payload.chunks[0].knowledge_id == 8
    assert payload.chunks[0].document_update_time == "2026-09-16 08:30:00"
    assert payload.total == 1


def test_empty_knowledge_base_ids_still_400():
    """``min_length=1`` stays: the v2 request contract does not change."""

    with pytest.raises(ValueError):
        RetrieveReq(query="q", knowledge_base_ids=[])


def test_max_content_above_cap_is_422_not_silently_clamped():
    """design D6 ②: ``RetrieveResp`` has nowhere to report a clamp, so refuse."""

    with pytest.raises(ValueError):
        RetrieveReq(query="q", knowledge_base_ids=[8], max_content=100000)

    # The cap itself is still accepted.
    assert RetrieveReq(query="q", knowledge_base_ids=[8], max_content=60000).max_content == 60000


def test_top_k_cap_matches_the_facade_cap():
    from bisheng.knowledge.domain.schemas.retrieval_facade import RETRIEVAL_TOP_K_MAX

    field = RetrieveReq.model_fields["top_k"]
    caps = [getattr(one, "le", None) for one in field.metadata]
    assert RETRIEVAL_TOP_K_MAX in caps


# ---------------------------------------------------------------------------
# AC-11 / AC-24 / AC-44 — the error vocabulary
# ---------------------------------------------------------------------------


async def test_unreachable_maps_to_26321_http_404(facade_spy, as_principal):
    as_principal(_service_account_principal())
    facade_spy.outcome["raises"] = KnowledgeUnreachableError(unreachable_ids=[9])

    with pytest.raises(KnowledgeUnreachableError) as exc:
        await _call(RetrieveReq(query="q", knowledge_base_ids=[8, 9]))

    from bisheng.open_api.api.exception_handlers import open_api_http_status

    assert exc.value.code == 26321
    assert open_api_http_status(exc.value) == 404


async def test_permission_unavailable_is_503_with_19002_not_26030(facade_spy, as_principal):
    """design D6: 26030 means "credential validation is down" — wrong thing to say."""

    as_principal(_service_account_principal())
    facade_spy.outcome["raises"] = PermissionServiceUnavailableError()

    with pytest.raises(PermissionServiceUnavailableError) as exc:
        await _call(RetrieveReq(query="q", knowledge_base_ids=[8]))

    from bisheng.open_api.api.exception_handlers import open_api_http_status

    assert open_api_http_status(exc.value) == 503
    assert exc.value.code == 19002


# ---------------------------------------------------------------------------
# AC-26 — the facade is the only retrieval path on the open face
# ---------------------------------------------------------------------------


def test_no_bypass_of_facade_in_open_face():
    import ast
    from pathlib import Path

    import bisheng.open_api as open_api_pkg
    import bisheng.open_endpoints as open_endpoints_pkg

    banned = ("aretrieve_chunks", "RetrievalEngine", "KnowledgeSpaceChatService")
    offenders: list[str] = []
    for package in (open_endpoints_pkg, open_api_pkg):
        root = Path(package.__file__).parent
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if not any(token in source for token in banned):
                continue
            tree = ast.parse(source)
            for node in ast.walk(tree):
                name = None
                if isinstance(node, ast.Attribute):
                    name = node.attr
                elif isinstance(node, ast.Name):
                    name = node.id
                elif isinstance(node, ast.alias):
                    name = node.name.rsplit(".", 1)[-1]
                if name in banned:
                    offenders.append(f"{path}:{getattr(node, 'lineno', '?')}:{name}")

    assert not offenders, "the open face must retrieve only through RetrievalFacadeService; found: " + ", ".join(
        offenders
    )


def test_open_face_imports_the_facade():
    import bisheng.open_endpoints.api.endpoints.filelib as module

    assert module.RetrievalFacadeService is not None
    assert isinstance(getattr(module, "RetrievalIdentity", None), type)


def test_filelib_no_longer_wraps_permission_outage_as_credential_outage():
    from pathlib import Path

    source = Path(filelib_mod.__file__).read_text(encoding="utf-8")
    assert "OpenApiAuthDependencyUnavailableError" not in source


async def test_version_repo_is_handed_to_the_facade(facade_spy, as_principal):
    as_principal(_service_account_principal())
    repo = MagicMock()

    await filelib_mod.retrieve_chunks(
        request=MagicMock(), req=RetrieveReq(query="q", knowledge_base_ids=[8]), version_repo=repo
    )

    assert facade_spy.calls[0]["kwargs"]["version_repo"] is repo


async def test_missing_principal_is_refused_by_the_facade(as_principal, monkeypatch):
    """AC-23 reaches v2 too: no principal in context, no retrieval.

    The real facade runs here on purpose — the point is that the endpoint does
    not invent an identity of its own when the gate left none behind.
    """

    from bisheng.common.errcode.mcp_face import RetrievalIdentityMissingError
    from bisheng.knowledge.domain.services import retrieval_facade_service as facade_mod

    as_principal(None)
    monkeypatch.setattr(facade_mod, "RetrievalEngine", MagicMock(side_effect=AssertionError("must not retrieve")))

    with pytest.raises(RetrievalIdentityMissingError):
        await _call(RetrieveReq(query="q", knowledge_base_ids=[8]))
