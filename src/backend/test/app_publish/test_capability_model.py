"""T056 — model capability injection through F051's face (AC-49 / AC-51 / AC-54).

What is actually being pinned here:

* the four environment names a container starts with, spelled exactly as F051
  design D2 and F054 ``contracts-runtime-manager.md`` §5 write them — a typo in
  one of them is a silent "the app has no model" in production;
* that an **undeclared** model is not callable, decided by the port this module
  registers and enforced by F051's own resolver, not by a second rule here;
* that there is no place in this product where an application configures a
  provider account or an endpoint of its own (AC-54), asserted structurally
  rather than by looking at a screen;
* that the runtime credential this pipeline issues actually calls F051's face
  and gets **declared ∩ tenant-enabled** back (F051 T022), start to finish
  through the real issuer, the real ``validate_bearer`` and the real resolver —
  the three tests at the bottom of the "end to end" section;
* that the two error-code families do not overlap (F051 T024): a model
  capability's runtime verdict is always a 262 code, and this feature's
  ``16273`` / ``16274`` are only ever raised for a non-model capability.
"""

from __future__ import annotations

import pytest

from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration
from bisheng.app_publish.domain.services import capability_bus_service
from bisheng.app_publish.domain.services.capability_bus_service import (
    KNOWLEDGE_SCOPE,
    MODEL_API_KEY_ENV,
    MODEL_BASE_URL_ENV,
    MODEL_BASE_URL_RESERVED_ENV,
    MODEL_SCOPE,
    REASON_OK,
    REASON_REVOKED,
    HostedAppDeclarationAdapter,
    derive_scopes,
    load_effective_declaration,
    model_capability_status,
    model_face_base_url,
    runtime_capability_env,
    undeployable_scopes,
)


def _declaration(models=(), knowledge=()):
    return CapabilityDeclaration.model_validate(
        {
            "models": [{"name": name} for name in models],
            "knowledge_bases": [{"id": str(one)} for one in knowledge],
        }
    )


# ---------------------------------------------------------------------------
# Environment injection (AC-49)
# ---------------------------------------------------------------------------


async def test_the_injected_names_are_the_four_the_contract_fixes(monkeypatch, app_factory, publish_db):
    app_row, _version = await app_factory(state="online")
    monkeypatch.setattr(capability_bus_service.settings.open_api, "public_base_url", "https://kb.example.com")

    issued = {}

    async def _issue(app_id, *, scopes=()):
        issued["app_id"] = app_id
        issued["scopes"] = list(scopes)
        return "bs-app-plaintext"

    monkeypatch.setattr(capability_bus_service.AppRuntimeCredentialService, "issue", _issue)

    env = await runtime_capability_env(app_row.id, declaration=_declaration(models=["qwen-max"]))

    assert env == {
        "BISHENG_APP_TOKEN": "bs-app-plaintext",
        MODEL_API_KEY_ENV: "bs-app-plaintext",
        MODEL_BASE_URL_ENV: "https://kb.example.com/api/v2/model/v1",
        MODEL_BASE_URL_RESERVED_ENV: "https://kb.example.com/api/v2/model/v1",
    }
    # The token is the same value under both names — an official OpenAI client
    # reads OPENAI_API_KEY with no configuration at all (design D13).
    assert env[MODEL_API_KEY_ENV] == env["BISHENG_APP_TOKEN"]
    assert issued == {"app_id": app_row.id, "scopes": [MODEL_SCOPE]}


async def test_an_application_that_declares_no_model_gets_no_model_environment(monkeypatch, app_factory):
    app_row, _version = await app_factory(state="online")
    monkeypatch.setattr(capability_bus_service.settings.open_api, "public_base_url", "https://kb.example.com")

    async def _issue(app_id, *, scopes=()):
        return "bs-app-plaintext"

    monkeypatch.setattr(capability_bus_service.AppRuntimeCredentialService, "issue", _issue)

    env = await runtime_capability_env(app_row.id, declaration=_declaration(knowledge=[7]))

    # It still gets an identity — that is what makes retrieval possible — but
    # nothing that would let it dial a model it never declared.
    assert set(env) == {"BISHENG_APP_TOKEN"}


async def test_the_base_url_is_derived_never_guessed(monkeypatch):
    monkeypatch.setattr(capability_bus_service.settings.open_api, "public_base_url", "")
    monkeypatch.setattr(capability_bus_service.settings.app_runtime, "entry_base_url", "https://apps.example.com/")

    assert model_face_base_url() == "https://apps.example.com/api/v2/model/v1"

    monkeypatch.setattr(capability_bus_service.settings.app_runtime, "entry_base_url", "")
    # Undeterminable answers with an empty string, which leaves the variable out
    # of the container entirely — a call then fails visibly instead of dialling
    # an address nobody serves.
    assert model_face_base_url() == ""


async def test_an_undeterminable_base_url_still_injects_the_token(monkeypatch, app_factory):
    app_row, _version = await app_factory(state="online")
    monkeypatch.setattr(capability_bus_service.settings.open_api, "public_base_url", "")
    monkeypatch.setattr(capability_bus_service.settings.app_runtime, "entry_base_url", "")

    async def _issue(app_id, *, scopes=()):
        return "bs-app-plaintext"

    monkeypatch.setattr(capability_bus_service.AppRuntimeCredentialService, "issue", _issue)

    env = await runtime_capability_env(app_row.id, declaration=_declaration(models=["qwen-max"]))

    assert env["BISHENG_APP_TOKEN"] == "bs-app-plaintext"
    assert MODEL_BASE_URL_ENV not in env


# ---------------------------------------------------------------------------
# Scope derivation (AC-51) and what this deployment can issue
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("models", "knowledge", "expected"),
    [
        ((), (), []),
        (("qwen-max",), (), [MODEL_SCOPE]),
        ((), (7,), [KNOWLEDGE_SCOPE]),
        (("qwen-max",), (7,), [MODEL_SCOPE, KNOWLEDGE_SCOPE]),
    ],
)
def test_scopes_come_only_from_what_was_declared(models, knowledge, expected):
    assert derive_scopes(_declaration(models=models, knowledge=knowledge)) == expected


def test_a_model_declaration_needs_the_extension_scope_this_deployment_may_not_offer(monkeypatch):
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.open_platform, "enabled", False)
    # ``model:invoke`` is gated on open_platform; ``knowledge:read`` never is.
    assert undeployable_scopes(_declaration(models=["qwen-max"])) == [MODEL_SCOPE]
    assert undeployable_scopes(_declaration(knowledge=[7])) == []

    monkeypatch.setattr(settings.open_platform, "enabled", True)
    assert undeployable_scopes(_declaration(models=["qwen-max"])) == []


# ---------------------------------------------------------------------------
# The declaration port F051 asks (AC-51)
# ---------------------------------------------------------------------------


async def test_the_port_reports_the_running_versions_models(publish_db, app_factory):
    from bisheng.database.models.app_version import AppVersionDao

    app_row, version = await app_factory(state="online")
    async with publish_db() as session:
        row = await AppVersionDao.aget(session, app_row.id, version.id)
        row.capabilities = {"models": [{"name": "qwen-max"}, {"name": "provider/gpt-4o"}]}
        session.add(row)
        await session.commit()

    declared = await HostedAppDeclarationAdapter().declared_model_names(app_row.id, app_row.tenant_id)

    assert declared == frozenset({"qwen-max", "provider/gpt-4o"})


async def test_declaring_no_models_is_an_empty_set_not_unknown(publish_db, app_factory):
    app_row, _version = await app_factory(state="online")

    declared = await HostedAppDeclarationAdapter().declared_model_names(app_row.id, app_row.tenant_id)

    # Empty set and None are two different answers on F051's face: 26215 ("you
    # did not declare it") versus 26216 ("the platform cannot tell right now").
    assert declared == frozenset()
    assert declared is not None


@pytest.mark.parametrize("state", ["draft", "stopped", "pending_capacity", "deleted"])
async def test_an_application_that_is_not_online_declares_nothing_knowable(publish_db, app_factory, state):
    app_row, _version = await app_factory(state=state)

    assert await HostedAppDeclarationAdapter().declared_model_names(app_row.id, app_row.tenant_id) is None


async def test_another_tenants_application_is_unknowable_rather_than_readable(publish_db, app_factory):
    app_row, _version = await app_factory(state="online")

    assert await HostedAppDeclarationAdapter().declared_model_names(app_row.id, 987654) is None


async def test_the_pending_version_does_not_grant_itself_capabilities(publish_db, app_factory):
    """An iteration under approval must not widen the running range (AC-51).

    The declaration is read off ``current_version_id``; submitting a version that
    declares a new model would otherwise let an owner grant themselves a
    capability without anyone approving it.
    """
    from datetime import datetime

    from bisheng.database.models.app import AppDao
    from bisheng.database.models.app_version import VERSION_KIND_ITERATION, AppVersion, AppVersionDao

    app_row, version = await app_factory(state="online")
    async with publish_db() as session:
        running = await AppVersionDao.aget(session, app_row.id, version.id)
        running.capabilities = {"models": [{"name": "qwen-max"}]}
        session.add(running)
        pending = AppVersion(
            app_id=app_row.id,
            version_no=2,
            kind=VERSION_KIND_ITERATION,
            code_object_key="apps/x/versions/v2/code.tar.gz",
            manifest={},
            capabilities={"models": [{"name": "qwen-max"}, {"name": "gpt-4o"}]},
            injections={},
            tier_id="light",
            runtime="python3.11",
            submitted_at=datetime.now(),
        )
        await AppVersionDao.ainsert(session, pending)
        stored = await AppDao.aget(session, app_row.id)
        stored.pending_version_id = pending.id
        session.add(stored)
        await session.commit()

    declared = await HostedAppDeclarationAdapter().declared_model_names(app_row.id, app_row.tenant_id)

    assert declared == frozenset({"qwen-max"})


# ---------------------------------------------------------------------------
# AC-54 — no provider account or endpoint configuration anywhere
# ---------------------------------------------------------------------------


def test_no_capability_surface_accepts_a_provider_account_or_endpoint():
    """AC-54, asserted structurally rather than by inspecting a screen.

    The bus's whole public surface is checked for a parameter that would let a
    caller name a base URL, an API key or a provider account. There is none, and
    the injection helper's *only* source for the address is
    :func:`model_face_base_url`, which reads deployment settings.
    """
    import inspect

    from bisheng.app_publish.domain.services import capability_bus_service as bus

    forbidden = ("base_url", "endpoint", "api_key", "provider", "account", "secret")
    offenders = []
    for name in bus.__all__:
        member = getattr(bus, name)
        if not (inspect.isfunction(member) or inspect.isclass(member)):
            continue
        target = member if inspect.isfunction(member) else member.__init__
        try:
            params = inspect.signature(target).parameters
        except (TypeError, ValueError):
            continue
        offenders.extend(f"{name}.{param}" for param in params if any(needle in param.lower() for needle in forbidden))
    assert offenders == []


# ---------------------------------------------------------------------------
# End to end — the issued credential really calls F051's face (F051 T022)
# ---------------------------------------------------------------------------
#
# Everything above stubs one side or the other. These three go the whole way:
# ``AppRuntimeCredentialService.issue`` mints a real ``bs-app-`` key, the face's
# real ``validate_bearer`` resolves it through the ``hosted_app`` resolver the
# composition root installs, and the range comes from the adapter reading the
# running version's declaration out of the database. Only the model catalog is
# a double, because model management's rows are not part of this package's
# schema — and it is the *shared* double from the F051 suite, so the two sides
# cannot disagree about what a tenant has enabled.


@pytest.fixture()
async def published_app_client(monkeypatch, publish_db, credential_redis, hosted_app_resolver, app_factory):
    """``await published_app_client(models=("gpt-4o",))`` → an httpx client on the face.

    The application is online, its running version declares ``models``, and the
    ``Authorization`` header carries the plaintext the publish pipeline would
    have injected as ``BISHENG_APP_TOKEN``.
    """
    from httpx import ASGITransport, AsyncClient

    from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
    from bisheng.common.services.config_service import settings
    from bisheng.database.models.app_version import AppVersionDao
    from test.open_api.model_gateway_fixtures import (
        FakeBishengLLM,
        build_model_face_app,
        capture_records,
        install_catalog,
        install_fake_llm,
        model_row,
        server_row,
    )

    # ``model:invoke`` is an extension scope; without the switch the pipeline
    # cannot issue it at all and the credential would carry no permission.
    monkeypatch.setattr(settings.open_platform, "enabled", True)
    clients = []

    async def _open(*, models=(), tenant_models=(("gpt-4o", True), ("qwen-max", True))):
        app_row, version = await app_factory(state="online")
        async with publish_db() as session:
            row = await AppVersionDao.aget(session, app_row.id, version.id)
            row.capabilities = {"models": [{"name": name} for name in models]}
            session.add(row)
            await session.commit()

        install_catalog(
            monkeypatch,
            [server_row(1, "azure-openai", tenant_id=app_row.tenant_id)],
            [model_row(20 + index, 1, name, online=online) for index, (name, online) in enumerate(tenant_models)],
        )
        install_fake_llm(monkeypatch, FakeBishengLLM())
        records = capture_records(monkeypatch)

        plaintext = await AppRuntimeCredentialService.issue(app_row.id, scopes=[MODEL_SCOPE])
        client = AsyncClient(
            transport=ASGITransport(app=build_model_face_app()),
            base_url="http://test",
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        await client.__aenter__()
        clients.append(client)
        return client, app_row, records

    try:
        yield _open
    finally:
        for client in clients:
            await client.__aexit__(None, None, None)


async def test_a_published_application_can_call_exactly_what_it_declared(published_app_client):
    client, app_row, records = await published_app_client(models=("gpt-4o",))

    listed = await client.get("/api/v2/model/v1/models")
    called = await client.post(
        "/api/v2/model/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert [row["id"] for row in listed.json()["data"]] == ["gpt-4o"]
    assert called.status_code == 200
    # The ledger's application dimension is ``app.id``, and the credential that
    # produced the row is the one the pipeline issued.
    assert [(row.actor_kind, row.app_id) for row in records] == [("hosted_app", app_row.id)]


async def test_the_tenants_other_models_are_refused_for_this_application(published_app_client):
    client, _app_row, _records = await published_app_client(models=("gpt-4o",))

    response = await client.post(
        "/api/v2/model/v1/chat/completions",
        json={"model": "qwen-max", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 403
    assert response.json()["error"]["bisheng_code"] == 26215


async def test_taking_a_declared_model_offline_changes_the_verdict_not_the_declaration(published_app_client):
    """AC-53 on the model face: the declaration is untouched, the model is gone.

    F055's publish surface marks it 「已失效」 from the same fact; the caller
    hears 26212, which says "ask an administrator", rather than 26215, which
    would say "edit your manifest".
    """
    client, app_row, _records = await published_app_client(models=("gpt-4o",), tenant_models=(("gpt-4o", False),))

    response = await client.post(
        "/api/v2/model/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 404
    assert response.json()["error"]["bisheng_code"] == 26212
    # Still declared — nothing about the declaration changed.
    assert await HostedAppDeclarationAdapter().declared_model_names(app_row.id, app_row.tenant_id) == frozenset(
        {"gpt-4o"}
    )


# ---------------------------------------------------------------------------
# F051 T024 — one event, one error code family
# ---------------------------------------------------------------------------


def test_this_features_capability_codes_are_never_raised_for_a_model():
    """16273 / 16274 belong to knowledge bases; models answer in the 262 band.

    Two families describing the same event is how a caller ends up with two
    different remedies for one fix. The split is: a model capability's runtime
    verdict is F051's (26215 未声明 / 26212 已下线 / 26213 已收回), and every
    ``16273`` / ``16274`` raised in this module names a knowledge capability.
    Asserted by reading the source, because the alternative — waiting for a
    model path to raise one — is exactly the regression this test exists to
    catch before it ships.
    """
    import ast
    import inspect

    from bisheng.app_publish.domain.services import capability_bus_service as bus

    tree = ast.parse(inspect.getsource(bus))
    raised = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"AppCapabilityRevokedError", "AppCapabilityNotDeclaredError"}
    ]
    assert raised, "the capability bus stopped raising these at all — re-read the split before deleting this test"
    for call in raised:
        kinds = [
            keyword.value for keyword in call.keywords if keyword.arg == "kind" and isinstance(keyword.value, ast.Name)
        ]
        assert [one.id for one in kinds] == ["CAPABILITY_KIND_KNOWLEDGE"], (
            f"{call.func.id} at line {call.lineno} is raised without naming the knowledge capability kind; "
            "a model capability must answer in F051's 262 band instead"
        )


async def test_the_model_face_and_the_publish_surface_read_the_same_resolution(publish_db, app_factory, monkeypatch):
    """AC-63's 「已失效」 mark and the face's refusal come from one function.

    Two queries answering "is this model callable" is how a publish surface ends
    up showing a model as healthy that the face refuses — or, worse, the other
    way round, with an owner republishing to fix something that was never broken.

    Scope of the guarantee: online / offline / missing, which is what
    ``resolve_model_name`` decides. One corner is **not** covered and is known —
    a declaration that names a model bare and later becomes ambiguous (an
    administrator adds a second provider serving the same model name) reads as
    revoked here while ``ModelRange.allows`` still admits a *qualified* request
    for it, because the range test is set membership on the name rather than a
    re-resolution. F051 tasks.md deviation 20 carries it; do not read this test
    as evidence that the two sides agree in that case.
    """
    from bisheng.database.models.app_version import AppVersionDao
    from test.open_api.model_gateway_fixtures import install_catalog, model_row, server_row

    app_row, version = await app_factory(state="online")
    async with publish_db() as session:
        row = await AppVersionDao.aget(session, app_row.id, version.id)
        row.capabilities = {"models": [{"name": "gpt-4o"}, {"name": "retired"}]}
        session.add(row)
        await session.commit()

    install_catalog(
        monkeypatch,
        [server_row(1, "azure-openai", tenant_id=app_row.tenant_id)],
        [model_row(20, 1, "gpt-4o"), model_row(21, 1, "retired", online=False)],
    )

    declaration = await load_effective_declaration(app_row.id)
    rows = await model_capability_status(declaration)

    assert {row.label: row.revoked for row in rows} == {"gpt-4o": False, "retired": True}
    # Same fact, same source: the face's own resolver is what produced it.
    assert {row.label: row.reason for row in rows} == {"gpt-4o": REASON_OK, "retired": REASON_REVOKED}
