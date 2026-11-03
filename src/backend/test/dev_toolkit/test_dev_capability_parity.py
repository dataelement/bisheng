"""Capability parity for the protocol surfaces shipped in the 130 workbench port.

Local and hosted applications use the same model admission and retrieval
identity checks. The standalone F052 Open MCP transport is not part of this
port; its transport/registry contracts belong to that feature's own suite.
The existing desktop Work MCP endpoint is a separate authenticated surface.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from bisheng.common.errcode.mcp_face import RetrievalIdentityMissingError
from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService
from bisheng.open_api.api.endpoints.model_gateway import router as model_gateway_router
from bisheng.open_api.domain.scopes import get_open_api_scope_marker

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
