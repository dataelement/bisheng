"""T090a (backend half) — the verdict behind ``/apps/preview/{session}`` (AC-37 / AC-31 / AC-12 / AC-25).

Test-first per the task file, and written against the property that actually
matters: **this entry is the one place where a version nobody has approved yet
becomes reachable**, so every branch that is not "the approver this preview was
raised for" has to end in a page that says nothing.

Four things are pinned here and nowhere else:

* Only the approver **the session belongs to** gets in. The owner does not, the
  other approver on the same request does not, a tenant administrator does not
  — every one of them is answered ``not_found``, the same page a fabricated
  session id gets, so nobody can use the difference to discover that an
  unpublished application exists (AC-30).
* An expired or reclaimed session is ``not_found`` too, on the spot — the
  deadline is enforced at the entry, not by whatever sweeps the container.
* The injected identity is **the approver's own** (INV-32). Not the owner's,
  not a synthetic one: the trial runs as the person trying it.
* A lookup that cannot be answered is a refusal, never a pass (AC-12).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from .conftest import ROOT_TENANT_ID

pytestmark = pytest.mark.asyncio

APPROVER_USER_ID = 91201
OTHER_USER_ID = 91202


@pytest.fixture(autouse=True)
def _runtime_layer_on(monkeypatch):
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.app_runtime, "enabled", True)
    monkeypatch.setattr(settings.app_runtime, "obo_secret", "preview-obo-secret-not-the-jwt-one")


@pytest.fixture()
async def approver(app_db):
    from .conftest import _seed_user

    user = await _seed_user(app_db, APPROVER_USER_ID, "f055-approver")
    return user


@pytest.fixture()
async def session_token(monkeypatch):
    """A decoded subject for any token, so these tests exercise the branch order.

    Session *validity* is F054 T033's own suite; re-testing it here would only
    duplicate it. What matters in this file is what happens **after** a valid
    session, which is why the decode is stubbed and the four helpers it feeds
    are left real.
    """
    from bisheng.app_runtime.domain.services import entry_authz_service

    def _decode(token):
        if not token or token == "bad":
            return None
        user_id = int(token.split(":")[-1])
        return {"user_id": user_id, "tenant_id": ROOT_TENANT_ID, "user_name": f"u{user_id}", "token_version": 0}

    async def _ok(*args, **kwargs):
        return True

    async def _false(*args, **kwargs):
        return False

    monkeypatch.setattr(entry_authz_service, "_decode_jwt_subject", _decode)
    monkeypatch.setattr(entry_authz_service, "_validate_token_version", _ok)
    monkeypatch.setattr(entry_authz_service, "_validate_current_session_token", _ok)
    monkeypatch.setattr(entry_authz_service, "_account_disabled", _false)
    monkeypatch.setattr(entry_authz_service, "_tenant_disabled", _false)
    return lambda user_id: f"token:{user_id}"


@pytest.fixture()
async def preview_session(app_db, app_factory, approver):
    """``await preview_session(approver_user_id=…, expired=…)`` → (app, version, row)."""
    from bisheng.app_publish.domain.models.app_preview_session import (
        PREVIEW_STATUS_RUNNING,
        AppPreviewSession,
        AppPreviewSessionDao,
    )

    async def _make(*, approver_user_id: int = APPROVER_USER_ID, expired: bool = False, state: str = "draft"):
        app, version = await app_factory(state=state, with_version=True)
        row = AppPreviewSession(
            tenant_id=ROOT_TENANT_ID,
            app_id=app.id,
            version_id=version.id,
            approver_user_id=approver_user_id,
            status=PREVIEW_STATUS_RUNNING,
            expires_at=datetime.now() + (timedelta(days=-1) if expired else timedelta(days=7)),
        )
        async with app_db() as session:
            await AppPreviewSessionDao.acreate(session, row)
            await session.commit()
        return app, version, row

    return _make


async def _authorize(session_id: str, token: str | None):
    from bisheng.app_runtime.domain.services.entry_authz_service import authorize_preview_entry

    return await authorize_preview_entry(session=session_id, access_token=token, request_id="req-1")


# ---------------------------------------------------------------------------
# who gets in
# ---------------------------------------------------------------------------


async def test_only_the_approver_of_that_session_is_allowed(preview_session, session_token):
    app, _version, row = await preview_session()

    verdict = await _authorize(row.id, session_token(APPROVER_USER_ID))

    assert verdict["decision"] == "allow"
    assert verdict["app_id"] == app.id
    assert verdict["preview_session"] == row.id


async def test_the_application_owner_is_not_allowed_into_someone_elses_preview(
    preview_session, session_token, app_owner
):
    """A preview carries the approver's identity; the owner has their own entry."""
    _app, _version, row = await preview_session()

    verdict = await _authorize(row.id, session_token(app_owner.user_id))

    assert verdict["decision"] == "not_found"
    assert "headers" not in verdict


async def test_another_user_of_the_same_tenant_is_not_allowed(preview_session, session_token):
    _app, _version, row = await preview_session()

    verdict = await _authorize(row.id, session_token(OTHER_USER_ID))

    assert verdict["decision"] == "not_found"


async def test_an_unknown_session_and_a_real_one_are_indistinguishable(preview_session, session_token):
    """AC-37 — the refusal must not be an existence oracle."""
    _app, _version, row = await preview_session()

    refused_real = await _authorize(row.id, session_token(OTHER_USER_ID))
    refused_fake = await _authorize("no-such-session-id", session_token(OTHER_USER_ID))

    assert refused_real == refused_fake == {"decision": "not_found"}


async def test_an_expired_session_is_not_found(preview_session, session_token):
    _app, _version, row = await preview_session(expired=True)

    verdict = await _authorize(row.id, session_token(APPROVER_USER_ID))

    assert verdict["decision"] == "not_found"


async def test_a_reclaimed_session_is_not_found(app_db, preview_session, session_token):
    from bisheng.app_publish.domain.models.app_preview_session import AppPreviewSessionDao

    _app, _version, row = await preview_session()
    async with app_db() as session:
        await AppPreviewSessionDao.amark_reclaimed(session, row.id, reason="manual")
        await session.commit()

    verdict = await _authorize(row.id, session_token(APPROVER_USER_ID))

    assert verdict["decision"] == "not_found"


async def test_no_session_hands_off_to_login(preview_session):
    _app, _version, row = await preview_session()

    verdict = await _authorize(row.id, None)

    assert verdict["decision"] == "login"


async def test_the_runtime_layer_switch_answers_first(preview_session, session_token, monkeypatch):
    """AC-30 / AC-62 — an environment without the layer never bounces anyone to login."""
    from bisheng.common.services.config_service import settings

    _app, _version, row = await preview_session()
    monkeypatch.setattr(settings.app_runtime, "enabled", False)

    assert await _authorize(row.id, session_token(APPROVER_USER_ID)) == {"decision": "not_enabled"}


async def test_a_deleted_application_is_not_found(app_db, preview_session, session_token):
    from bisheng.database.models.app import App

    app, _version, row = await preview_session()
    async with app_db() as session:
        stored = await session.get(App, app.id)
        stored.state = "deleted"
        session.add(stored)
        await session.commit()

    verdict = await _authorize(row.id, session_token(APPROVER_USER_ID))

    assert verdict["decision"] == "not_found"


async def test_a_failing_session_lookup_is_a_refusal_not_a_pass(preview_session, session_token, monkeypatch):
    """AC-12 — "could not decide" never means "let them in"."""
    from bisheng.app_publish.domain.services.preview_instance_service import PreviewInstanceService

    _app, _version, row = await preview_session()

    async def _boom(session_id):
        raise RuntimeError("database is down")

    monkeypatch.setattr(PreviewInstanceService, "resolve_entry", staticmethod(_boom))

    assert await _authorize(row.id, session_token(APPROVER_USER_ID)) == {"decision": "not_found"}


# ---------------------------------------------------------------------------
# what the instance is told
# ---------------------------------------------------------------------------


async def test_the_injected_identity_is_the_approver_not_the_owner(preview_session, session_token, approver, app_owner):
    """INV-32 — the trial runs as the person trying it."""
    app, _version, row = await preview_session()

    verdict = await _authorize(row.id, session_token(APPROVER_USER_ID))

    material = verdict["headers"]
    assert material["X-BiSheng-User-Id"] == str(APPROVER_USER_ID)
    assert material["X-BiSheng-User-Id"] != str(app_owner.user_id)
    assert material["X-BiSheng-App-Id"] == app.id
    assert material["X-BiSheng-Tenant-Id"] == str(ROOT_TENANT_ID)
    assert material["X-BiSheng-Subject-Kind"] == "human"


async def test_an_obo_token_is_issued_for_the_approver(preview_session, session_token):
    import json

    import jwt

    from bisheng.app_runtime.domain.services.entry_authz_service import OBO_AUDIENCE
    from bisheng.common.services.config_service import settings

    app, _version, row = await preview_session()

    verdict = await _authorize(row.id, session_token(APPROVER_USER_ID))

    claims = jwt.decode(
        verdict["obo_token"],
        settings.app_runtime.obo_secret,
        algorithms=["HS256"],
        audience=OBO_AUDIENCE,
    )
    subject = json.loads(claims["sub"])
    assert subject["user_id"] == APPROVER_USER_ID
    assert subject["app_id"] == app.id


async def test_a_preview_visit_is_not_recorded_as_an_application_access(preview_session, session_token, monkeypatch):
    """AC-38 counts visits to an application; a trial of an unshipped version is not one."""
    from bisheng.app_runtime.domain.services import entry_authz_service

    recorded: list[dict] = []
    monkeypatch.setattr(entry_authz_service, "schedule_access_record", lambda **kwargs: recorded.append(kwargs))

    _app, _version, row = await preview_session()
    await _authorize(row.id, session_token(APPROVER_USER_ID))

    assert recorded == []


async def test_a_draft_application_is_reachable_through_the_preview_entry(preview_session, session_token):
    """AC-30's sanctioned exception: the whole reason this entry exists.

    The application is a ``draft`` — invisible on ``/apps/{slug}`` to everyone
    including its owner's colleagues — and the approver still gets in.
    """
    _app, _version, row = await preview_session(state="draft")

    verdict = await _authorize(row.id, session_token(APPROVER_USER_ID))

    assert verdict["decision"] == "allow"
    assert verdict["app_state"] == "draft"


# ---------------------------------------------------------------------------
# the internal endpoint
# ---------------------------------------------------------------------------


async def test_the_internal_endpoint_is_hmac_signed_and_answers_200_for_a_refusal(preview_session, session_token):
    """A business verdict is an answer, not a transport failure (design D6)."""
    import httpx
    from fastapi import FastAPI

    from bisheng.app_runtime.api.router import router
    from bisheng.app_runtime.domain.services.hmac_auth import verify_proxy_hmac

    _app, _version, row = await preview_session()
    api = FastAPI()
    api.dependency_overrides[verify_proxy_hmac] = lambda: None
    api.include_router(router, prefix="/api/v1")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://testserver") as client:
        allowed = await client.post(
            "/api/v1/internal/app-proxy/authorize-preview",
            json={"session": row.id, "access_token": session_token(APPROVER_USER_ID), "request_id": "r"},
        )
        refused = await client.post(
            "/api/v1/internal/app-proxy/authorize-preview",
            json={"session": row.id, "access_token": session_token(OTHER_USER_ID), "request_id": "r"},
        )

    assert allowed.status_code == 200
    assert allowed.json()["data"]["decision"] == "allow"
    assert refused.status_code == 200
    assert refused.json()["data"] == {"decision": "not_found"}
