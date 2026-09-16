"""F053 T045 — a `bisheng dev` capability call is judged exactly like a hosted one.

AC-28's promise is not "the CLI enforces the right things"; it is that the CLI
enforces *nothing*, because there is only one judge. A local application calls
the same `/api/v2` faces with the same bearer as a hosted one, so the scope
check, the visibility filter and the fail-closed behaviour are literally the
same code — and `bisheng dev` deliberately does not check scopes before starting
(AC-29), which is only safe while that stays true.

What could break the promise is a *branch*: a face that treats a
`bs-sak-` caller differently from a `bs-app-` one, a second authentication path
in front of one of them, or a filter that has an "unfiltered" mode. This file
pins the absence of those, structurally, on the two faces `dev` reaches (F051's
model face and F052's MCP face plus the retrieval facade behind it).

The behavioural coverage of each face lives in `test/open_api/` and
`test/knowledge/`; nothing here duplicates it.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from bisheng.common.errcode.app_publish import AppPublishRuntimeLayerDisabledError
from bisheng.common.errcode.mcp_face import McpToolScopeMissingError, RetrievalIdentityMissingError
from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService
from bisheng.open_api.api.endpoints.model_gateway import router as model_gateway_router
from bisheng.open_api.domain.scopes import get_open_api_scope_marker
from bisheng.open_api.mcp import gate as mcp_gate
from bisheng.open_api.mcp.registry import installed_tools, require_tool, visible_tools


class _Principal:
    """The shape `require_tool` / `visible_tools` read — scopes and nothing else."""

    def __init__(self, *scopes: str) -> None:
        self._scopes = frozenset(scopes)

    def has_scope(self, scope: str) -> bool:
        return scope in self._scopes


# ---- F051: the model face -----------------------------------------------------


def test_every_model_face_route_is_gated_on_the_same_scope():
    """One scope, every route, including the catch-all.

    A route that forgot its marker would fail closed on `/api/v2`, but the
    inverse mistake — a route added with a *different* or absent scope — is what
    would let a `dev` caller reach something a hosted one cannot.
    """
    markers = {route.path: get_open_api_scope_marker(route.endpoint) for route in model_gateway_router.routes}
    assert markers, "the model face lost its routes"
    for path, marker in markers.items():
        assert marker is not None, f"{path} carries no @open_api_scope marker"
        assert marker.scope == "model:invoke", f"{path} is gated on {marker.scope}"
        # Mode S only: a delegating key acts as somebody else, and an app — local
        # or hosted — has nobody to act as.
        assert marker.modes == frozenset({"S"}), f"{path} admits modes {marker.modes}"


def test_the_model_face_has_no_notion_of_where_the_caller_runs():
    """No source-level branch on dev / local / hosted anywhere in the face.

    Checked on the source rather than by calling, because the failure being
    guarded is a future edit, and a behavioural test would only catch it on the
    one path it happens to exercise.
    """
    from bisheng.open_api.api.endpoints import model_gateway
    from bisheng.open_api.domain.services import model_gateway_service

    for module in (model_gateway, model_gateway_service):
        source = inspect.getsource(module).lower()
        for token in ("is_dev", "bisheng dev", "local_dev_call", "skip_scope"):
            assert token not in source, f"{module.__name__} branches on {token!r}"


# ---- F052: the MCP face and the retrieval facade ------------------------------


def test_the_mcp_gate_reuses_the_v2_admission_functions():
    """Not a second copy of authentication — the same two functions `/api/v2` runs.

    This is what makes "a revoked key stops working within five seconds" and
    "editing the key's scopes takes effect on the next call" true for a local
    developer without anybody re-implementing them.
    """
    source = inspect.getsource(mcp_gate)
    assert "admit_open_api_principal" in source
    assert "open_api_execution_scope" in source
    assert "from bisheng.open_api.api.dependencies import" in source


@pytest.mark.parametrize("spec", installed_tools(), ids=lambda spec: spec.name)
def test_every_mcp_tool_refuses_a_credential_without_its_scope(spec):
    """The granted scope decides, for every tool, with no exception list.

    Only tools whose server-side dependency is installed are parametrised: an
    absent one answers "no such tool", which is a different (and also correct)
    refusal — the point here is that none of them answers "go ahead".
    """
    with pytest.raises(McpToolScopeMissingError):
        require_tool(_Principal(), spec.name)


def test_a_credential_sees_only_the_tools_its_scopes_cover():
    """`visible_tools` and `require_tool` agree — listing is not a wider door."""
    principal = _Principal("knowledge:read")
    visible = {spec.name for spec in visible_tools(principal)}
    assert visible, "knowledge:read should still admit the retrieval tools"
    for spec in installed_tools():
        if spec.name in visible:
            continue
        # Either the scope is missing, or the tool belongs to a layer this
        # deployment does not run — never a call that goes through.
        with pytest.raises((McpToolScopeMissingError, AppPublishRuntimeLayerDisabledError)):
            require_tool(principal, spec.name)


async def test_the_retrieval_facade_refuses_rather_than_falling_back_to_everything():
    """No resolvable identity is a refusal — never "search the whole tenant".

    The `dev` case that makes this matter: the mini proxy injects the service
    account as the visitor, so an application that forwards no visitor identity
    has to be refused here rather than quietly retrieving as nobody.
    """
    from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalRequest

    request = RetrievalRequest(query="任意问题")
    no_actor = SimpleNamespace(actor=None, login_user=None)
    anonymous_actor = SimpleNamespace(actor=SimpleNamespace(subject_id=None), login_user=None)
    for identity in (None, no_actor, anonymous_actor):
        with pytest.raises(RetrievalIdentityMissingError):
            await RetrievalFacadeService.retrieve(identity, request)
