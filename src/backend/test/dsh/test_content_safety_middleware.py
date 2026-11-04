"""Coverage AC: AC-03, AC-42, AC-45.

Use the registered receiver, real CustomMiddleware, HMAC verifier and ingestion.
Synthetic JWT decoding and external DAO/Redis ports isolate browser admission;
no test replaces the ownership decision, credential verification or tenant scope.
SQLite transaction evidence does not establish MySQL/DM8 integration behavior.
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest
from starlette.requests import ClientDisconnect

from bisheng.common.services.config_service import settings
from bisheng.core.cache import redis_manager
from bisheng.core.context import tenant as context
from bisheng.user.domain.models.user import UserDao
from bisheng.utils import http_middleware
from test.dsh import test_content_safety_api as api_tests
from test.dsh.test_content_safety_api import assert_error, assert_receipt, post, raw_event
from test.dsh.test_content_safety_ingest import rows
from test.dsh.test_content_safety_runtime import PATH, headers

safety_api = api_tests.api


def scope_snapshot():
    return (
        context.current_tenant_id.get(),
        context.get_admin_scope_tenant_id(),
        context.get_visible_tenant_ids(),
        context.get_is_management_api(),
        context.is_tenant_filter_bypassed(),
        context.is_strict_tenant_filter(),
    )


CLEAN_SCOPE = (None, None, None, False, False, False)


@contextmanager
def installed_scope(*, dirty):
    tokens = [
        context.current_tenant_id.set(999 if dirty else None),
        context.set_admin_scope_tenant_id(202 if dirty else None),
        context.set_visible_tenant_ids(frozenset({1, 202}) if dirty else None),
        context.set_is_management_api(dirty),
        context._bypass_tenant_filter.set(dirty),
        context._strict_tenant_filter.set(dirty),
    ]
    try:
        yield scope_snapshot()
    finally:
        for token in reversed(tokens):
            token.var.reset(token)


@pytest.fixture
def middleware_api(safety_api, monkeypatch):
    api = safety_api
    monkeypatch.setattr(settings.multi_tenant, "enabled", True)
    decoded = []

    def decode(token):
        decoded.append(token)
        return {"user_id": 22, "tenant_id": 202, "token_version": 1}

    # Keep the production token-version decision, replacing only its DAO read.
    versions = AsyncMock(return_value=2)
    redis = AsyncMock(side_effect=AssertionError("Unexpected Redis access"))
    monkeypatch.setattr(http_middleware, "_decode_jwt_subject", decode)
    monkeypatch.setattr(UserDao, "aget_token_version", versions)
    monkeypatch.setattr(redis_manager, "get_redis_client", redis)
    original_verify = api.runtime.verify_source
    observed = []

    def verify(raw, request_headers, method, path):
        observed.append(scope_snapshot())
        return original_verify(raw, request_headers, method, path)

    monkeypatch.setattr(api.runtime, "verify_source", verify)
    api.app.add_middleware(http_middleware.CustomMiddleware)
    api.browser_decodes, api.browser_versions, api.redis = decoded, versions, redis
    api.entry_scopes = observed
    with installed_scope(dirty=False):
        yield api


def assert_no_browser_admission(api):
    assert api.browser_decodes == []
    api.browser_versions.assert_not_awaited()
    api.redis.assert_not_awaited()


def test_only_exact_post_receiver_owns_service_authentication():
    assert http_middleware.owns_dsh_credential("POST", PATH)
    assert not any(PATH.startswith(prefix) for prefix in http_middleware.TENANT_CHECK_EXEMPT_PATHS)


async def test_signed_service_callback_without_browser_cookie_reaches_real_commit(middleware_api, content_safety_event):
    api = middleware_api
    event = content_safety_event()
    response = await post(api, raw_event(api, event))
    assert_receipt(response, event)
    assert api.entry_scopes == [CLEAN_SCOPE]
    assert_no_browser_admission(api)
    facts, audits = rows(api.engine)
    assert len(facts) == len(audits) == api.sessions.commits == 1


@pytest.mark.parametrize(
    "credentials",
    [
        {"Cookie": "access_token_cookie=synthetic-stale-browser"},
        {"Authorization": "Bearer synthetic-expired-user-token"},
        {
            "Cookie": "access_token_cookie=synthetic-stale-browser",
            "Authorization": "Bearer synthetic-expired-user-token",
        },
    ],
)
async def test_signed_historical_callback_ignores_browser_credentials(
    middleware_api, content_safety_event, credentials
):
    api = middleware_api
    event = content_safety_event()
    raw = raw_event(api, event)
    response = await post(api, raw, request_headers={**headers(raw), **credentials})
    assert_receipt(response, event)
    assert api.entry_scopes == [CLEAN_SCOPE]
    assert_no_browser_admission(api)
    facts, audits = rows(api.engine)
    assert facts[0].tenant_id == audits[0].tenant_id == 101
    assert rows(api.engine, 202) == ([], [])


@pytest.mark.parametrize(
    "credentials",
    [
        {},
        {"Authorization": "Bearer synthetic-desktop-token"},
        {"Cookie": "access_token_cookie=synthetic-browser-token"},
        {"X-Signature": "0" * 64},
    ],
)
async def test_unsigned_or_user_authenticated_requests_still_require_real_service_signature(
    middleware_api, content_safety_event, credentials
):
    api = middleware_api
    response = await post(api, raw_event(api, content_safety_event()), request_headers=credentials)
    assert_error(response, 401, "content_safety_authentication_failed")
    assert api.entry_scopes == [CLEAN_SCOPE]
    assert_no_browser_admission(api)
    assert api.factories == api.sessions.sessions == []
    assert rows(api.engine) == ([], [])


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", PATH),
        ("PUT", PATH),
        ("PATCH", PATH),
        ("POST", PATH + "/"),
        ("POST", PATH + "/other"),
        ("POST", PATH + "-other"),
        ("POST", "/api/v1/internal/dsh/other"),
        ("POST", "/api/v1/dsh/authorize"),
    ],
)
async def test_neighbors_non_post_and_browser_routes_retain_browser_admission(
    middleware_api, content_safety_event, method, path
):
    import httpx

    api = middleware_api
    assert not http_middleware.owns_dsh_credential(method, path)
    assert not any(path.startswith(prefix) for prefix in http_middleware.TENANT_CHECK_EXEMPT_PATHS)
    raw = raw_event(api, content_safety_event())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app), base_url="https://bisheng.invalid"
    ) as client:
        response = await client.request(
            method,
            path,
            content=raw,
            headers={
                **headers(raw),
                "Cookie": "access_token_cookie=synthetic-stale-browser",
            },
        )
    assert response.status_code == 401 and response.json()["status_code"] == 19103
    assert api.browser_decodes == ["synthetic-stale-browser"]
    api.browser_versions.assert_awaited_once_with(22)
    api.redis.assert_not_awaited()
    assert api.entry_scopes == api.verification == api.factories == api.sessions.sessions == []


@pytest.mark.parametrize("outcome", ["committed", "auth_error", "dependency_error"])
async def test_service_boundary_clears_all_stale_scope_and_restores_it_after_response(
    middleware_api, content_safety_event, outcome
):
    api = middleware_api
    event = content_safety_event()
    raw = raw_event(api, event)
    request_headers = headers(raw)
    if outcome == "auth_error":
        request_headers = {"X-Signature": "0" * 64}
    elif outcome == "dependency_error":

        def fail_commit(_session):
            raise RuntimeError("Synthetic SQL failure")

        api.sessions.before_commit = fail_commit
    with installed_scope(dirty=True) as original:
        response = await post(api, raw, request_headers=request_headers)
        assert scope_snapshot() == original
    assert api.entry_scopes == [CLEAN_SCOPE]
    assert_no_browser_admission(api)
    if outcome == "committed":
        assert_receipt(response, event)
        assert all(scope == (101, None, frozenset({101}), False) for scope in api.sessions.scopes)
        facts, audits = rows(api.engine)
        assert facts[0].tenant_id == audits[0].tenant_id == 101
    else:
        assert_error(
            response,
            401 if outcome == "auth_error" else 503,
            "content_safety_authentication_failed" if outcome == "auth_error" else "content_safety_event_unavailable",
        )
        assert rows(api.engine) == ([], [])


async def test_upload_disconnect_restores_scope_without_verifying_or_acknowledging(
    middleware_api, content_safety_event
):
    api = middleware_api
    raw = raw_event(api, content_safety_event())
    observed = []

    async def interrupted_upload():
        observed.append(scope_snapshot())
        yield raw[:32]
        raise ClientDisconnect()

    with installed_scope(dirty=True) as original:
        with pytest.raises(ClientDisconnect):
            await post(api, raw, content=interrupted_upload())
        assert scope_snapshot() == original
    assert observed == [CLEAN_SCOPE]
    assert_no_browser_admission(api)
    assert api.entry_scopes == api.verification == api.factories == api.sessions.sessions == []
    assert rows(api.engine) == ([], [])
