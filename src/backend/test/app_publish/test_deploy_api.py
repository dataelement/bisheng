"""T038 — the ``/api/v2/apps`` endpoints ``bisheng deploy`` talks to (AC-01 / AC-03 / AC-04 / AC-11).

This is the demo path's front door, so the tests are about the guards rather
than the happy path (which the pipeline suite already owns end to end).

Four guards, in the order the endpoints apply them:

1. **Credential, scope and identity mode** — beta2's single ``/api/v2``
   pipeline (F053 design K14): the aggregate router authenticates, then reads
   each endpoint's ``@open_api_scope("app:manage", modes=("S",))`` marker. A
   session cookie is not an alternative here — ``/api/v2`` only knows
   ``Bearer bs-sak-…`` / ``bs-pat-…``. The fixture keeps that pipeline real and
   patches only the credential lookup, so these tests exercise the actual
   refusals rather than a stub of them.
2. **Is the app factory installed at all** (16207). Deliberately *after*
   authentication so an anonymous caller cannot fingerprint the deployment
   shape, and deliberately before ownership because on a plain installation
   there are no applications to own. Without it, ``deploy`` against a normal
   BiSheng walks all the way to an orchestrator RPC and dies on a timeout.
3. **Ownership**, read from ``resource_owner_user_id`` — the natural person the
   key creates resources for (伴生 PRD §4.5 定义 6). Reading ``actor_id`` instead
   would compare against the service account, which owns nothing; a principal
   with no owner at all is refused (M9), never treated as owner 0.
4. **The two submission gates** (16251 / 16252), asked before the approval gate
   ever sees the request, because the gate answers a duplicate by silently
   handing back the existing instance.
"""

from __future__ import annotations

import pytest

from .conftest import OWNER_USER_ID, SERVICE_ACCOUNT_NAME, SERVICE_ACCOUNT_USER_ID

pytestmark = pytest.mark.asyncio


def _body(response):
    assert response.status_code == 200, response.text
    return response.json()


async def _upload(client, tarball, *, app_id: str | None = None, confirm: bool = False):
    files = {"package": ("app.tar.gz", tarball.read_bytes(), "application/gzip")}
    data = {"confirm_schema_change": str(confirm).lower()}
    if app_id:
        data["app_id"] = app_id
    return await client.post("/api/v2/apps/deploy", files=files, data=data)


# ---------------------------------------------------------------------------
# AC-01 — deploy-limits and the receive leg
# ---------------------------------------------------------------------------


async def test_deploy_limits_returns_settings_values(
    publish_db, api_app, service_account_principal, app_runtime_settings
):
    """The CLI reads its own package ceiling from here (F053 AC-32)."""
    app_runtime_settings(max_package_mb=7, max_unpacked_mb=11, max_package_entries=13)

    async with api_app(principal=service_account_principal()) as client:
        payload = _body(await client.get("/api/v2/apps/deploy-limits"))

    assert payload["data"] == {"max_package_mb": 7, "max_unpacked_mb": 11, "max_package_entries": 13}


async def test_first_deploy_creates_a_draft_owned_by_the_resource_owner(
    publish_db,
    api_app,
    service_account_principal,
    tarball_factory,
    fake_minio,
    fake_f054_services,
    tier_seed,
    audit_sink,
    monkeypatch,
):
    """AC-04 — ownership comes from ``resource_owner_user_id``, never the acting subject.

    F054's ``create_draft`` is the only way an application row may be created
    (决议-8), so the assertion is on what F055 asked *it* for.
    """
    from bisheng.app_publish.domain.services import publish_pipeline_service

    fake_f054_services.responses["create_draft"] = "app-new"
    monkeypatch.setattr(publish_pipeline_service, "enqueue_pipeline", _noop)

    async with api_app(principal=service_account_principal()) as client:
        payload = _body(await _upload(client, tarball_factory()))

    assert payload["data"]["app_id"] == "app-new"
    assert payload["data"]["deployment_id"]
    assert payload["data"]["version_id"]
    created = dict(fake_f054_services.calls[0][1])
    assert created["owner_user_id"] == OWNER_USER_ID
    assert created["owner_user_id"] != SERVICE_ACCOUNT_USER_ID


async def test_deploy_records_the_submitting_service_account_separately(
    publish_db,
    api_app,
    service_account_principal,
    tarball_factory,
    fake_minio,
    fake_f054_services,
    tier_seed,
    audit_sink,
    monkeypatch,
):
    """Owner and acting subject are two things because they are two things (INV-29).

    Under beta2 the acting subject is not a user row (migration plan M4), so
    ``submitted_by_user_id`` — a *user* id column — carries the platform's
    non-person operator value ``0`` rather than the service account's id: the
    ``app.release.*`` audit rows default their operator to this column, and a
    ``service_account.id`` written there would name whichever person shares
    the number. Which service account ran ``deploy`` is recorded where beta2
    records it for every v2 call — on the audit row, as operator name plus
    ``actor_kind`` / ``actor_id`` / ``credential_id`` metadata.
    """
    from bisheng.app_publish.domain.constants import AppReleaseAuditAction
    from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao
    from bisheng.app_publish.domain.services import publish_pipeline_service

    fake_f054_services.responses["create_draft"] = "app-new"
    monkeypatch.setattr(publish_pipeline_service, "enqueue_pipeline", _noop)

    async with api_app(principal=service_account_principal()) as client:
        payload = _body(await _upload(client, tarball_factory()))

    async with publish_db() as session:
        row = await AppDeploymentDao.aget(session, payload["data"]["deployment_id"])
    assert row.owner_user_id == OWNER_USER_ID
    assert row.submitted_by_user_id == publish_pipeline_service.NO_NATURAL_PERSON_SUBMITTER
    assert row.submitted_by_user_id != SERVICE_ACCOUNT_USER_ID, "a service_account.id is not a user id"

    submit = next(call for call in audit_sink if call["action"] == str(AppReleaseAuditAction.SUBMIT))
    assert submit["operator_id"] == publish_pipeline_service.NO_NATURAL_PERSON_SUBMITTER
    assert submit["operator_name"] == SERVICE_ACCOUNT_NAME
    assert submit["metadata"]["actor_kind"] == "service_account"
    assert submit["metadata"]["actor_id"] == SERVICE_ACCOUNT_USER_ID
    assert submit["metadata"]["credential_id"] == 1


async def test_iteration_deploy_of_another_owners_app_is_rejected_16205(
    publish_db, api_app, service_account_principal, tarball_factory, fake_minio, tier_seed, app_factory
):
    """A key may only publish its own resource owner's applications.

    This is a **business** rule, not a permission verdict: ``app:manage`` says
    the key may publish, the resource owner says whose applications.
    """
    app, _ = await app_factory(owner_user_id=OWNER_USER_ID + 500, with_version=False)

    async with api_app(principal=service_account_principal()) as client:
        payload = _body(await _upload(client, tarball_factory(), app_id=app.id))

    assert payload["status_code"] == 16205


async def test_app_runtime_disabled_returns_16207(publish_db, api_app, service_account_principal, tarball_factory):
    """A plain BiSheng answers "this feature is not installed", not a socket timeout."""
    async with api_app(principal=service_account_principal(), app_runtime_enabled=False) as client:
        payload = _body(await _upload(client, tarball_factory()))

    assert payload["status_code"] == 16207


async def test_deploy_limits_also_gated_by_16207(publish_db, api_app, service_account_principal):
    """The gate is on every endpoint, not only the expensive one."""
    async with api_app(principal=service_account_principal(), app_runtime_enabled=False) as client:
        payload = _body(await client.get("/api/v2/apps/deploy-limits"))

    assert payload["status_code"] == 16207


# ---------------------------------------------------------------------------
# AC-03 — the two submission gates, through HTTP
# ---------------------------------------------------------------------------


async def test_active_release_blocks_second_deploy_16251(
    publish_db,
    api_app,
    service_account_principal,
    tarball_factory,
    fake_minio,
    tier_seed,
    app_factory,
    deployment_factory,
):
    """Running ``deploy`` twice must fail loudly rather than look like it worked."""
    app, _ = await app_factory(with_version=False)
    await deployment_factory(app_id=app.id, stage="precheck_build", status="running")

    async with api_app(principal=service_account_principal()) as client:
        payload = _body(await _upload(client, tarball_factory(), app_id=app.id))

    assert payload["status_code"] == 16251


async def test_pending_online_blocks_deploy_16252(
    publish_db, api_app, service_account_principal, tarball_factory, fake_minio, tier_seed, app_factory
):
    """A parked application does not accept a new version until it is resolved.

    16252, not 16251: the remedies differ ("resolve the parked release" vs
    "wait for the one in flight").
    """
    app, _ = await app_factory(state="pending_capacity", with_version=False)

    async with api_app(principal=service_account_principal()) as client:
        payload = _body(await _upload(client, tarball_factory(), app_id=app.id))

    assert payload["status_code"] == 16252


# ---------------------------------------------------------------------------
# AC-11 — polling
# ---------------------------------------------------------------------------


async def test_deployment_polling_returns_failure_tuple(
    publish_db, api_app, service_account_principal, app_factory, deployment_factory
):
    """The CLI branches on ``code`` and prints ``message`` + ``hints``."""
    failure = {
        "stage": "precheck_manifest",
        "code": 16221,
        "message": "bisheng-app.yaml 校验失败",
        "details": {"errors": [{"field": "runtime", "reason": "missing"}]},
        "hints": ["在 bisheng-app.yaml 中补上 runtime: python3.11"],
    }
    app, version = await app_factory(with_version=True)
    deployment = await deployment_factory(
        app_id=app.id, stage="precheck_manifest", status="failed", version_id=version.id, failure=failure
    )

    async with api_app(principal=service_account_principal()) as client:
        payload = _body(await client.get(f"/api/v2/apps/deployments/{deployment.id}"))

    data = payload["data"]
    assert data["stage"] == "precheck_manifest"
    assert data["status"] == "failed"
    assert data["failure"] == failure
    assert data["app_state"] == app.state
    assert data["version_no"] == version.version_no


async def test_polling_another_owners_deployment_is_rejected(
    publish_db, api_app, service_account_principal, app_factory, deployment_factory
):
    """ "Not found" and "not yours" answer the same way — otherwise the id is an oracle."""
    app, _ = await app_factory(with_version=False)
    deployment = await deployment_factory(app_id=app.id, owner_user_id=OWNER_USER_ID + 777)

    async with api_app(principal=service_account_principal()) as client:
        payload = _body(await client.get(f"/api/v2/apps/deployments/{deployment.id}"))

    assert payload["status_code"] == 16205


async def test_unknown_deployment_id_answers_the_same_as_not_owned(publish_db, api_app, service_account_principal):
    async with api_app(principal=service_account_principal()) as client:
        payload = _body(await client.get("/api/v2/apps/deployments/no-such-id"))

    assert payload["status_code"] == 16205


# ---------------------------------------------------------------------------
# AC-04 — scope and identity
# ---------------------------------------------------------------------------


def _v2_routes():
    from fastapi.routing import APIRoute

    from bisheng.app_publish.api.router import v2_router

    routes = [route for route in v2_router.routes if isinstance(route, APIRoute)]
    assert len(routes) == 4, "the four CLI endpoints: deploy-limits, deploy, deployments/{id}, {app_id}/logs"
    return routes


async def test_every_v2_endpoint_carries_the_app_manage_marker_mode_s_only():
    """K14: the marker is the whole of an endpoint's declaration; INV-31: mode S only.

    A router-level dependency is invisible from here, and that is the point —
    ``verify_open_api_access`` refuses any route *without* a marker, so the
    thing to pin per endpoint is the marker, not a dependency name. ``modes``
    is asserted too because the decorator's default admits mode D, and a
    delegating key must not publish in somebody else's name.
    """
    from bisheng.open_api.domain.scopes import get_open_api_scope_marker

    for route in _v2_routes():
        marker = get_open_api_scope_marker(route.endpoint)
        assert marker is not None, f"{route.path} has no @open_api_scope marker: the pipeline would refuse it"
        assert marker.scope == "app:manage", route.path
        assert marker.modes == frozenset({"S"}), f"{route.path} admits a delegated call"


async def test_runtime_gate_resolves_after_the_router_level_credential(publish_db, api_app):
    """Authenticate first, then answer "not installed" — never the other way round.

    Asserted on the *mounted* app: FastAPI inserts router-level dependencies
    ahead of an endpoint's own in its ``Dependant``, so the order is a property
    of how ``bisheng/api/router.py`` mounts ``v2_router``, not of argument
    order in ``deploy.py``. The fixture mounts it the same way.
    """
    from bisheng.app_publish.api.endpoints.deploy import require_app_runtime_enabled
    from bisheng.open_api.api.dependencies import verify_open_api_access

    async with api_app() as client:
        routes = [route for route in client._transport.app.routes if route.path.startswith("/api/v2/apps")]
    assert len(routes) == 4
    for route in routes:
        order = [dep.call for dep in route.dependant.dependencies]
        assert order.index(verify_open_api_access) < order.index(require_app_runtime_enabled), (
            f"{route.path} answers 16207 before authenticating"
        )


async def test_scope_name_is_validated_when_the_marker_is_applied():
    """A typo must fail at import, not degrade into "no scope required".

    ``open_api_scope`` checks the name against the registry when the decorator
    runs, which for ``deploy.py`` is module import. ``_SCOPE`` is pinned so a
    rename of the constant cannot quietly point the four endpoints at another
    position.
    """
    import pytest as _pytest

    from bisheng.app_publish.api.endpoints import deploy
    from bisheng.open_api.domain.scopes import OPEN_API_SCOPE_CODES, open_api_scope

    assert deploy._SCOPE == "app:manage"
    assert deploy._SCOPE in OPEN_API_SCOPE_CODES
    with _pytest.raises(ValueError):
        open_api_scope("app:mannage")


async def test_session_cookie_cannot_call_v2_endpoints(publish_db, api_app, owner_user):
    """``/api/v2`` only knows ``Bearer bs-sak-…``; a logged-in browser is not a credential.

    The credential lookup is left real here (no ``principal``), so the request
    goes through beta2's parser and is refused with a real 401 / 26001 — the
    status the live app's v2 exception handler produces.
    """
    async with api_app(payload=owner_user.payload) as client:
        response = await client.get("/api/v2/apps/deploy-limits", cookies={"access_token_cookie": "x"})

    assert response.status_code == 401
    assert response.json()["status_code"] == 26001


async def test_malformed_bearer_is_refused_by_the_real_parser(publish_db, api_app, service_account_principal):
    """The fixture patches the *lookup*, not the parser: a header that is not a key never reaches it."""
    async with api_app(principal=service_account_principal()) as client:
        response = await client.get("/api/v2/apps/deploy-limits", headers={"Authorization": "Bearer nope"})

    assert response.status_code == 401
    assert response.json()["status_code"] == 26001


async def test_key_without_app_manage_is_refused_26003(publish_db, api_app, service_account_principal):
    """A valid key with the wrong position gets the pipeline's 403, before 16207 or any body."""
    async with api_app(principal=service_account_principal(scopes=("knowledge:read",))) as client:
        response = await client.get("/api/v2/apps/deploy-limits")

    assert response.status_code == 403
    assert response.json()["status_code"] == 26003


async def test_delegated_call_is_refused_by_the_marker_26006(publish_db, api_app, service_account_principal):
    """INV-31 at the entrance: ``app:manage`` is mode S only.

    A mode-D principal (what ``X-On-Behalf-Of`` + ``delegate`` produces) is
    handed back unchanged by ``resolve_request_identity`` when no header is
    present, and then refused by ``modes=("S",)`` — the same refusal the CLI
    gets for a delegating key, and not a silent fallback to mode S.
    """
    async with api_app(principal=service_account_principal(mode="D")) as client:
        response = await client.get("/api/v2/apps/deploy-limits")

    assert response.status_code == 403
    assert response.json()["status_code"] == 26006


async def test_unmarked_v2_endpoint_is_refused_even_with_a_valid_key(publish_db, api_app, service_account_principal):
    """The fixture keeps K14's fail-closed default real — otherwise every test above proves nothing."""
    from fastapi import APIRouter

    extra = APIRouter()

    @extra.get("/apps/unmarked")
    async def unmarked():
        return {"unsafe": True}

    async with api_app(principal=service_account_principal()) as client:
        app = client._transport.app
        rpc = next(route for route in app.router.routes if getattr(route, "path", "") == "/api/v2/apps/deploy-limits")
        # Mount next to the real routes, under the same router-level dependency.
        app.include_router(extra, prefix="/api/v2", dependencies=list(rpc.dependencies))
        response = await client.get("/api/v2/apps/unmarked")

    assert response.status_code == 500
    assert response.json()["status_code"] == 26031


async def test_key_without_resource_owner_cannot_deploy(
    publish_db, api_app, service_account_principal, tarball_factory, fake_minio, fake_f054_services, tier_seed
):
    """M9: no resource owner → refused, never owner 0.

    A first publish through an ownerless key must not create an application
    owned by nobody; ``fake_f054_services`` proves ``create_draft`` was never
    asked. 16205 with ``reason=resource_owner_missing`` — the same code an
    ownership mismatch gets, because "whose apps may this key publish" has the
    answer "nobody's".
    """
    async with api_app(principal=service_account_principal(resource_owner_user_id=None)) as client:
        payload = _body(await _upload(client, tarball_factory()))

    assert payload["status_code"] == 16205
    assert payload["data"]["details"]["reason"] == "resource_owner_missing"
    assert [name for name, _ in fake_f054_services.calls if name == "create_draft"] == []


async def test_key_without_resource_owner_cannot_poll_an_ownerless_deployment(
    publish_db, api_app, service_account_principal, app_factory, deployment_factory
):
    """The old ``getattr(..., 0) or 0`` spelling would have matched an owner-0 row here."""
    app, _ = await app_factory(with_version=False)
    deployment = await deployment_factory(app_id=app.id, owner_user_id=0)

    async with api_app(principal=service_account_principal(resource_owner_user_id=None)) as client:
        payload = _body(await client.get(f"/api/v2/apps/deployments/{deployment.id}"))

    assert payload["status_code"] == 16205
    assert payload["data"]["details"]["reason"] == "resource_owner_missing"


async def test_logs_endpoint_is_owner_scoped(publish_db, api_app, service_account_principal, app_factory, monkeypatch):
    """``bisheng logs`` reads through the same service method as the detail page, entry="cli".

    That entry narrows it to the credential's resource owner: a tenant
    administrator's key must not read every application's logs in the tenant,
    which would widen the open API past what the key holder was granted.
    """
    from bisheng.app_runtime.domain.services import app_query_service

    seen: dict = {}

    async def _get_logs(app_id, *, actor, tail=None, since=None, keyword=None, entry="detail"):
        seen.update({"app_id": app_id, "user_id": actor.user_id, "entry": entry, "tail": tail})
        return {"lines": ["hello"]}

    monkeypatch.setattr(
        app_query_service.AppQueryService, "get_logs", classmethod(lambda cls, *a, **kw: _get_logs(*a, **kw))
    )
    app, _ = await app_factory(with_version=False)

    async with api_app(principal=service_account_principal()) as client:
        payload = _body(await client.get(f"/api/v2/apps/{app.id}/logs", params={"tail": 50}))

    # The payload carries the log lines plus the two fields that explain an
    # empty ``lines`` (F053 T034 write-back 2): without them "no output" and
    # "no running instance" are indistinguishable to the CLI.
    assert payload["data"]["lines"] == ["hello"]
    assert set(payload["data"]) == {"lines", "app_state", "pending_reason"}
    assert seen == {"app_id": app.id, "user_id": OWNER_USER_ID, "entry": "cli", "tail": 50}


async def _noop(*args, **kwargs):
    """Stand-in for ``enqueue_pipeline``: the receive leg is under test, not Celery."""
    return None
