"""T056 — model capability injection through F051's face (AC-49 / AC-51 / AC-54).

What is actually being pinned here:

* the four environment names a container starts with, spelled exactly as F051
  design D2 and F054 ``contracts-runtime-manager.md`` §5 write them — a typo in
  one of them is a silent "the app has no model" in production;
* that an **undeclared** model is not callable, decided by the port this module
  registers and enforced by F051's own resolver, not by a second rule here;
* that there is no place in this product where an application configures a
  provider account or an endpoint of its own (AC-54), asserted structurally
  rather than by looking at a screen.
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
    HostedAppDeclarationAdapter,
    derive_scopes,
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
