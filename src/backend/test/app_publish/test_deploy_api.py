"""T038 — the ``/api/v2/apps`` endpoints ``bisheng deploy`` talks to (AC-01 / AC-03 / AC-04 / AC-11).

This is the demo path's front door, so the tests are about the guards rather
than the happy path (which the pipeline suite already owns end to end).

Four guards, in the order the endpoints apply them:

1. **Credential and scope.** ``app:manage``, on every endpoint individually.
   A session cookie is not an alternative here — ``/api/v2`` only knows
   ``Bearer bs-sak-…``.
2. **Is the app factory installed at all** (16207). Deliberately *after*
   authentication so an anonymous caller cannot fingerprint the deployment
   shape, and deliberately before ownership because on a plain installation
   there are no applications to own. Without it, ``deploy`` against a normal
   BiSheng walks all the way to an orchestrator RPC and dies on a timeout.
3. **Ownership**, read from ``resource_owner_user_id`` — the natural person the
   key creates resources for. Reading ``subject_user_id`` instead would compare
   against the service account, which owns nothing.
4. **The two submission gates** (16251 / 16252), asked before the approval gate
   ever sees the request, because the gate answers a duplicate by silently
   handing back the existing instance.
"""

from __future__ import annotations

import pytest

from .conftest import OWNER_USER_ID, SERVICE_ACCOUNT_USER_ID

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
    """Owner and acting subject are two columns because they are two people (INV-29)."""
    from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao
    from bisheng.app_publish.domain.services import publish_pipeline_service

    fake_f054_services.responses["create_draft"] = "app-new"
    monkeypatch.setattr(publish_pipeline_service, "enqueue_pipeline", _noop)

    async with api_app(principal=service_account_principal()) as client:
        payload = _body(await _upload(client, tarball_factory()))

    async with publish_db() as session:
        row = await AppDeploymentDao.aget(session, payload["data"]["deployment_id"])
    assert row.owner_user_id == OWNER_USER_ID
    assert row.submitted_by_user_id == SERVICE_ACCOUNT_USER_ID


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


async def test_every_v2_endpoint_requires_app_manage(publish_db):
    """Each endpoint carries the dependency itself; none inherits it from the router.

    A router-level dependency would be invisible here, and the whole point of
    F049's per-endpoint factory is that adding an endpoint without a scope is a
    loud failure rather than an open door.
    """
    from bisheng.app_publish.api.endpoints.deploy import app_manage_subject
    from bisheng.app_publish.api.router import v2_router

    for route in v2_router.routes:
        names = {getattr(dep.call, "__name__", "") for dep in route.dependant.dependencies}
        assert app_manage_subject.__name__ in names, f"{route.path} does not require app:manage"


async def test_runtime_gate_declared_after_the_credential_on_every_endpoint(publish_db):
    """Authenticate first, then answer "not installed" — never the other way round."""
    from bisheng.app_publish.api.endpoints.deploy import app_manage_subject, require_app_runtime_enabled
    from bisheng.app_publish.api.router import v2_router

    for route in v2_router.routes:
        order = [getattr(dep.call, "__name__", "") for dep in route.dependant.dependencies]
        assert order.index(app_manage_subject.__name__) < order.index(require_app_runtime_enabled.__name__), (
            f"{route.path} answers 16207 before authenticating"
        )


async def test_scope_name_is_validated_at_import():
    """A typo must fail at startup, not degrade into "no scope required"."""
    from bisheng.app_publish.api.endpoints import deploy
    from bisheng.open_api.domain.scopes import is_known_scope

    assert deploy._SCOPE == "app:manage"
    assert is_known_scope(deploy._SCOPE)


async def test_session_cookie_cannot_call_v2_endpoints(publish_db, api_app, owner_user):
    """``/api/v2`` only knows ``Bearer bs-sak-…``; a logged-in browser is not a credential.

    The dependency is left real here (no ``principal``), so the request goes
    through F049's credential validation and is refused.
    """
    async with api_app(payload=owner_user.payload) as client:
        response = await client.get("/api/v2/apps/deploy-limits", cookies={"access_token_cookie": "x"})

    assert response.status_code != 200 or response.json().get("status_code") not in (0, 200)


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


async def test_delegate_scope_is_not_issuable_this_release():
    """AC-04's "a delegating key is always refused" is structurally true for now.

    The ``delegate`` position cannot be granted at all in this release — the
    registry keeps its code only so that a request carrying it gets a precise
    26024 instead of a generic denial. Asserted rather than assumed, because the
    day it becomes issuable this endpoint family needs an explicit rule.
    """
    from bisheng.open_api.domain.scopes import DELEGATE_SCOPE_CODE, OPEN_API_SCOPES

    assert DELEGATE_SCOPE_CODE not in {scope.code for scope in OPEN_API_SCOPES}


async def _noop(*args, **kwargs):
    """Stand-in for ``enqueue_pipeline``: the receive leg is under test, not Celery."""
    return None
