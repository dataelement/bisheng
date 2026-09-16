"""F051 T022 / T023: the face as a **hosted application** sees it.

The three files before this one prove the face works for a service-account key.
This one is about the other credential kind, and everything that is different
about it lives in two places:

* the **range** is the effective capability declaration intersected with what
  the tenant has enabled, read through F055's real
  ``HostedAppDeclarationAdapter`` rather than a hand-written fake — the fake
  cannot get the ``None`` / empty-set distinction wrong, and that distinction
  is the whole difference between 26216 and 26215;
* the **subject** is the visitor whose OBO token the application forwarded,
  verified by F054's real ``verify_obo_token``. A call with no token is
  attributed to ``app_self`` **explicitly**, and one with a broken token is
  refused rather than quietly downgraded to it — otherwise the ledger's user
  dimension would be something the caller can erase by sending garbage.

Both ports are exercised through the objects that ship, wired the way
``app_publish/composition.py`` wires them. ``test_model_range_policy`` covers
the same decisions with fakes at the unit level; the point here is that the
registered implementations agree with it.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from bisheng.common.services.config_service import settings
from bisheng.open_api.domain.models.model_call_record import SUBJECT_KIND_APP_SELF, SUBJECT_KIND_USER
from bisheng.open_api.domain.services import model_range_policy
from bisheng.open_api.domain.services.model_range_policy import (
    ACCESS_TOKEN_HEADER,
    register_access_subject_verifier,
    register_hosted_app_declaration_port,
)
from test.open_api.model_gateway_fixtures import (
    FakeBishengLLM,
    build_model_face_app,
    capture_records,
    hosted_app_principal,
    install_catalog,
    install_fake_llm,
    model_row,
    server_row,
)

CHAT_PATH = "/api/v2/model/v1/chat/completions"
MODELS_PATH = "/api/v2/model/v1/models"

APP_ID = "app-uuid-survey"
TENANT_ID = 9
VISITOR_USER_ID = 77

OBO_SECRET = "f051-hosted-app-obo-secret"

BODY = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}


# --- wiring ------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_ports():
    """Both ports are process-wide; put back whatever was installed.

    Restoring only the one a test replaced is the shape that hurts: a suite that
    leaves F055's real adapter registered makes the *next* file's hosted-app
    test read a database that is not there.
    """
    previous = (
        model_range_policy.get_hosted_app_declaration_port(),
        model_range_policy.get_access_subject_verifier(),
    )
    yield
    register_hosted_app_declaration_port(previous[0])
    register_access_subject_verifier(previous[1])


@pytest.fixture
def declaration(monkeypatch):
    """Register F055's real adapter over a scripted effective declaration.

    ``load_effective_declaration`` is the only thing stubbed — everything the
    adapter does with its answer (the tenant comparison, ``model_names``, the
    ``None`` passthrough) is the shipped code.
    """
    from bisheng.app_publish.domain.services import capability_bus_service
    from bisheng.app_publish.domain.services.capability_bus_service import (
        EffectiveDeclaration,
        HostedAppDeclarationAdapter,
    )

    def _install(models: tuple[str, ...] | None, *, tenant_id: int = TENANT_ID):
        async def _load(app_id: str):
            if models is None:
                # What the adapter is handed for an application that is not
                # online, was deleted, or has no current version.
                return None
            return EffectiveDeclaration(
                app_id=app_id,
                tenant_id=tenant_id,
                version_id="v1",
                app_name="survey",
                models=models,
            )

        monkeypatch.setattr(capability_bus_service, "load_effective_declaration", _load)
        register_hosted_app_declaration_port(HostedAppDeclarationAdapter())

    return _install


@pytest.fixture
def obo(monkeypatch):
    """Register F054's real verifier and hand back a token factory.

    The secret must differ from ``jwt_secret`` or the issuer refuses to sign at
    all (an OBO token that doubles as a platform session is the failure that
    check exists for), so both are pinned here.
    """
    from bisheng.app_runtime.domain.services.entry_authz_service import AccessSubjectVerifier, _issue_obo_token

    monkeypatch.setattr(settings.app_runtime, "obo_secret", OBO_SECRET, raising=False)
    monkeypatch.setattr(settings, "jwt_secret", "a-different-platform-secret", raising=False)
    register_access_subject_verifier(AccessSubjectVerifier())

    def _issue(*, app_id: str = APP_ID, user_id: int = VISITOR_USER_ID, tenant_id: int = TENANT_ID) -> str:
        token, _expires_at = _issue_obo_token(
            app_id=app_id,
            user_id=user_id,
            tenant_id=tenant_id,
            subject_kind="user",
        )
        assert token is not None, "the fixture's secrets must let a token be issued"
        return token

    return _issue


@pytest.fixture
def hosted(monkeypatch):
    """A hosted-application credential admitted at the door, with a catalog.

    The tenant publishes three chat models; ``retired`` is offline, which is how
    "declared but taken away" is told apart from "never declared".
    """
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(return_value=hosted_app_principal(app_id=APP_ID, tenant_id=TENANT_ID)),
    )
    install_catalog(
        monkeypatch,
        [server_row(1, "azure-openai", tenant_id=TENANT_ID)],
        [
            model_row(10, 1, "gpt-4o"),
            model_row(11, 1, "qwen-max"),
            model_row(12, 1, "retired", online=False),
        ],
    )
    install_fake_llm(monkeypatch, FakeBishengLLM(invoke_result=AIMessage(content="ok")))
    return capture_records(monkeypatch)


async def _call(method: str, path: str, *, headers: dict[str, str] | None = None, json_body: dict | None = None):
    app = build_model_face_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, headers=headers, json=json_body)


def _error(response) -> dict:
    return response.json()["error"]


# --- T022: the callable range is declared ∩ tenant-enabled -------------------


async def test_models_lists_the_intersection_and_nothing_else(hosted, declaration):
    # ``claude-3`` is declared and the tenant does not have it; ``qwen-max`` is
    # in the tenant and not declared. Both must be absent, for different
    # reasons — a list that showed either would offer an id that cannot be
    # called, which is the one thing /models must never do.
    declaration(("gpt-4o", "claude-3"))

    response = await _call("GET", MODELS_PATH)

    assert response.status_code == 200
    assert [row["id"] for row in response.json()["data"]] == ["gpt-4o"]


async def test_declaring_a_model_the_tenant_disabled_does_not_conjure_it(hosted, declaration):
    declaration(("claude-3",))

    response = await _call("GET", MODELS_PATH)

    assert response.json()["data"] == []


async def test_a_tenant_model_the_application_never_declared_is_26215(hosted, declaration):
    declaration(("gpt-4o",))

    response = await _call("POST", CHAT_PATH, json_body={**BODY, "model": "qwen-max"})

    assert response.status_code == 403
    assert _error(response)["bisheng_code"] == 26215
    assert _error(response)["code"] == "capability_undeclared"
    # The record still lands: the call reached model resolution, which is the
    # line AC-20 draws for "gets a usage row".
    assert [(row.result, row.error_code) for row in hosted] == [("capability_undeclared", 26215)]


async def test_a_declared_model_that_was_taken_offline_is_26212_not_26215(hosted, declaration):
    """AC-13 — the two verdicts send the owner to different people.

    26215 means "declare it and publish again"; 26212 means "ask an
    administrator why it disappeared". Collapsing them would send every owner
    down the wrong path half the time.
    """
    declaration(("retired",))

    response = await _call("POST", CHAT_PATH, json_body={**BODY, "model": "retired"})

    assert response.status_code == 404
    assert _error(response)["bisheng_code"] == 26212
    assert [(row.result, row.error_code) for row in hosted] == [("model_unavailable", 26212)]


async def test_a_declared_model_withdrawn_inside_the_cache_window_is_26213_not_26215(monkeypatch, hosted, declaration):
    """The capability-revoked boundary, from the other side.

    The catalog caches for up to a minute, so an administrator can delete the
    provider after the name resolved. The declaration still lists the model —
    answering "you did not declare it" would send the owner to edit a manifest
    that is correct, which is the exact confusion F055's 16273 / 16274 and this
    band are kept apart to avoid.
    """
    from bisheng.common.errcode.server import LlmProviderDeletedError
    from bisheng.llm.domain.services.llm import LLMService

    declaration(("gpt-4o",))

    async def explode(**_kwargs):
        raise LlmProviderDeletedError()

    monkeypatch.setattr(LLMService, "get_bisheng_llm", staticmethod(explode))

    response = await _call("POST", CHAT_PATH, json_body=BODY)

    assert response.status_code == 404
    assert _error(response)["bisheng_code"] == 26213
    assert [(row.result, row.error_code) for row in hosted] == [("model_unavailable", 26213)]


async def test_a_declared_model_the_tenant_never_had_is_26211(hosted, declaration):
    """Not 26215: the declaration is satisfied, the platform simply has no such
    model. Answering "undeclared" here would tell the owner to edit a manifest
    that is already correct."""
    declaration(("claude-3",))

    response = await _call("POST", CHAT_PATH, json_body={**BODY, "model": "claude-3"})

    assert response.status_code == 404
    assert _error(response)["bisheng_code"] == 26211


async def test_declaring_no_model_at_all_refuses_by_name_rather_than_by_range(hosted, declaration):
    declaration(())

    response = await _call("POST", CHAT_PATH, json_body=BODY)

    # An empty declaration is a *known* range, so the answer is 26215 — not
    # 26216, which would tell the caller to retry something that can never work.
    assert _error(response)["bisheng_code"] == 26215
    assert (await _call("GET", MODELS_PATH)).json()["data"] == []


# --- T022: AC-35, the second gate fails closed -------------------------------


async def test_without_a_registered_declaration_port_every_call_is_26216(hosted):
    for method, path, body in (("GET", MODELS_PATH, None), ("POST", CHAT_PATH, BODY)):
        response = await _call(method, path, json_body=body)

        assert response.status_code == 503
        assert _error(response)["bisheng_code"] == 26216


async def test_an_unreadable_declaration_never_falls_back_to_the_tenant_range(hosted, declaration):
    """``None`` from the port is "cannot tell", and the tenant range is the one
    answer that must never be reached from it — it would hand an application
    every model the tenant has."""
    declaration(None)

    response = await _call("GET", MODELS_PATH)

    assert response.status_code == 503
    assert _error(response)["bisheng_code"] == 26216


async def test_another_tenants_declaration_is_unreadable_rather_than_usable(hosted, declaration):
    # The adapter compares the declaration's tenant with the credential's. A
    # mismatch is answered as "cannot tell", never as the declaration itself.
    declaration(("gpt-4o",), tenant_id=TENANT_ID + 1)

    response = await _call("GET", MODELS_PATH)

    assert _error(response)["bisheng_code"] == 26216


# --- T023: who the call is attributed to -------------------------------------


async def test_a_forwarded_visitor_token_names_that_visitor_in_the_ledger(hosted, declaration, obo):
    declaration(("gpt-4o",))

    response = await _call("POST", CHAT_PATH, headers={ACCESS_TOKEN_HEADER: obo()}, json_body=BODY)

    assert response.status_code == 200
    (row,) = hosted
    assert (row.subject_kind, row.subject_id) == (SUBJECT_KIND_USER, VISITOR_USER_ID)
    # The application dimension is the uuid, never the display name: F056's
    # per-application query and the ledger's index both key on it.
    assert row.app_id == APP_ID
    assert (row.actor_kind, row.actor_name) == ("hosted_app", "survey-app")


async def test_a_call_with_no_token_is_labelled_app_self_rather_than_borrowing_the_owner(hosted, declaration, obo):
    """AC-21 — a background job inside the container has no visitor, and saying
    so is the honest row. Attributing it to the owner would put calls in a
    person's name that the person did not make."""
    declaration(("gpt-4o",))

    response = await _call("POST", CHAT_PATH, json_body=BODY)

    assert response.status_code == 200
    (row,) = hosted
    assert (row.subject_kind, row.subject_id) == (SUBJECT_KIND_APP_SELF, None)
    assert row.app_id == APP_ID
    # The owner is still on the row, as the traceable resource owner — a
    # different column with a different meaning from "who made this call".
    assert row.resource_owner_user_id == 12


@pytest.mark.parametrize(
    "token_factory",
    [
        pytest.param(lambda issue: issue(app_id="app-uuid-other"), id="another_applications_visitor"),
        pytest.param(lambda issue: issue(tenant_id=999), id="another_tenants_token"),
        pytest.param(lambda _issue: "not-a-jwt", id="malformed"),
        pytest.param(
            lambda _issue: jwt.encode(
                {
                    "sub": json.dumps({"app_id": APP_ID, "user_id": VISITOR_USER_ID, "tenant_id": TENANT_ID}),
                    "aud": "bisheng-app-obo",
                    "iss": settings.cookie_conf.jwt_iss,
                    "iat": int(time.time()) - 10,
                    "exp": int(time.time()) - 1,
                },
                OBO_SECRET,
                algorithm="HS256",
            ),
            id="expired",
        ),
        pytest.param(
            lambda _issue: jwt.encode(
                {
                    "sub": json.dumps({"app_id": APP_ID, "user_id": VISITOR_USER_ID, "tenant_id": TENANT_ID}),
                    "aud": "bisheng-app-obo",
                    "iss": settings.cookie_conf.jwt_iss,
                    "iat": int(time.time()),
                    "exp": int(time.time()) + 600,
                },
                "a-secret-this-platform-never-signed-with",
                algorithm="HS256",
            ),
            id="forged_signature",
        ),
    ],
)
async def test_a_token_that_does_not_verify_is_refused_not_downgraded(hosted, declaration, obo, token_factory):
    declaration(("gpt-4o",))

    response = await _call("POST", CHAT_PATH, headers={ACCESS_TOKEN_HEADER: token_factory(obo)}, json_body=BODY)

    assert response.status_code == 403
    assert _error(response)["bisheng_code"] == 26204
    # Refused before the model is touched, so no usage row and no provider call.
    assert hosted == []


async def test_the_callable_range_is_the_same_whoever_the_subject_is(hosted, declaration, obo):
    """Attribution and authorisation are separate axes. A visitor cannot widen
    what the application may call, and cannot narrow it either."""
    declaration(("gpt-4o",))

    anonymous = await _call("GET", MODELS_PATH)
    with_visitor = await _call("GET", MODELS_PATH, headers={ACCESS_TOKEN_HEADER: obo()})

    assert anonymous.json() == with_visitor.json()


async def test_the_subject_is_decided_before_the_range_is(hosted, declaration, obo):
    """A permanently invalid token must not be answered 26216 ("retry later")
    just because the declaration happens to be unreadable this second."""
    declaration(None)

    response = await _call("POST", CHAT_PATH, headers={ACCESS_TOKEN_HEADER: "not-a-jwt"}, json_body=BODY)

    assert _error(response)["bisheng_code"] == 26204


# --- T023: the registration itself -------------------------------------------


def test_the_composition_root_installs_both_ports(_restore_ports):
    """Registering one without the other is the shape that hurts: a readable
    declaration plus an unverifiable token would serve every call while
    attributing all of them to the application itself."""
    from bisheng.app_publish.composition import register
    from bisheng.app_publish.domain.services.capability_bus_service import HostedAppDeclarationAdapter
    from bisheng.app_runtime.domain.services import lifecycle_hooks, runtime_env_ports
    from bisheng.app_runtime.domain.services.entry_authz_service import AccessSubjectVerifier
    from bisheng.open_api.domain.models.api_credential import SUBJECT_KIND_HOSTED_APP
    from bisheng.open_api.domain.services.credential_validator import SUBJECT_RESOLVERS
    from bisheng.open_api.domain.services.execution_context import SUBJECT_EXECUTION_GUARDS

    lifecycle_hooks.clear_app_deleted_hooks()
    try:
        register()

        assert isinstance(model_range_policy.get_hosted_app_declaration_port(), HostedAppDeclarationAdapter)
        assert isinstance(model_range_policy.get_access_subject_verifier(), AccessSubjectVerifier)
    finally:
        SUBJECT_RESOLVERS.pop(SUBJECT_KIND_HOSTED_APP, None)
        SUBJECT_EXECUTION_GUARDS.pop(SUBJECT_KIND_HOSTED_APP, None)
        lifecycle_hooks.clear_app_deleted_hooks()
        runtime_env_ports.clear_capability_env_provider()


def test_both_process_entry_points_call_the_composition_root():
    """The API process serves the face; the Celery leg re-checks the identity a
    queued task carries. Wiring one and not the other is invisible by hand."""
    import ast
    import pathlib

    import bisheng

    root = pathlib.Path(bisheng.__file__).parent
    for relative in ("main.py", "worker/main.py"):
        source = (root / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "bisheng.app_publish.composition"
        ]
        assert imported, f"{relative} never imports the app_publish composition root"
