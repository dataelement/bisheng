"""Live identity/policy HTTP acceptance; never run against imported application state.

DSH_SAFETY_E2E=1 explicitly opts in. Both deployment-bound 0600 session files,
DSH_E2E_USER_ID, and the frozen LiveSafetySettings parameters are mandatory.
Only newly issued PKCE sessions are revoked. Policy changes additionally require
an exclusive serial provider/window and the unmodified SafetyPolicyLease.
Unverified: A/B tenants and leaf-admin scope; namespace/full-token cache isolation;
replica policy/digest/absolute TTL; physical profile counts and 30s expiry;
singleflight/cancelled waiters; Redis faults/capacity; trusted identity changes;
OFF/METADATA audit facts and server diagnostic redaction. These need separate
explicit isolated facilities and are not represented by placeholder test cases.
"""

import asyncio
import os
import time
import uuid

import httpx
import pytest
import pytest_asyncio

from test.e2e.helpers.auth import auth_headers
from test.e2e.helpers.dsh import logout_desktop_session, refresh_desktop_session
from test.e2e.helpers.dsh_content_safety import (
    LiveSafetyError,
    LiveSafetyHTTP,
    LiveSafetySettings,
    SafetyPolicyLease,
    Secret,
    checked_json,
    wait_until,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("DSH_SAFETY_E2E") != "1", reason="Explicit live DSH safety environment required"),
]
POLICY_FIELDS = ("enabled", "input_enabled", "output_enabled", "words_types", "custom_words", "auto_reply")
NOTICE = "This request was stopped by the test content policy."


def _require(condition, message):
    if not condition:
        raise LiveSafetyError(message)


def _native_error(response, code):
    """Inspect only frozen error fields; never include credentials or body in failures."""
    _require(response.status_code == 401, "Expected a real HTTP authentication rejection")
    try:
        value = response.json()
    except ValueError:
        raise LiveSafetyError("Authentication rejection returned invalid JSON") from None
    _require(
        isinstance(value, dict)
        and isinstance(value.get("error"), dict)
        and value["error"].get("code") in ({code} if isinstance(code, str) else code)
        and value["error"].get("type") == "authentication_error",
        "Authentication rejection changed its exact public error",
    )
    _require(isinstance(value.get("request_id"), str) and bool(value["request_id"]), "Error request identifier missing")


def _policy_error(response, code):
    _require(response.status_code == code, "Policy rejection changed its HTTP status")
    try:
        value = response.json()
    except ValueError:
        raise LiveSafetyError("Policy rejection returned invalid JSON") from None
    _require(
        isinstance(value, dict) and value.get("status_code", value.get("statusCode")) == code,
        "Policy rejection changed its business status",
    )


class IdentityRun:
    """Own issued credentials, never the supplied platform sessions or arbitrary sessions."""

    def __init__(self, http, user_settings, user_id, record):
        self.http, self.user_settings, self.user_id, self.record = http, user_settings, user_id, record
        self.sessions = {}
        self.scenarios = []

    def __repr__(self):
        return "IdentityRun(<redacted>)"

    @property
    def base(self):
        return self.http.settings.api_base

    @staticmethod
    def headers(tokens):
        return {"Authorization": Secret("Bearer " + tokens["access_token"])}

    async def issue(self):
        tokens = await self.http.desktop_session(self.user_settings.platform_token)
        _require(
            isinstance(tokens.get("session_id"), str) and tokens.get("token_type") == "Bearer",
            "PKCE did not issue a native session",
        )
        self.sessions[tokens["session_id"]] = tokens
        await self.profile(tokens)
        return tokens

    async def profile(self, tokens):
        headers = self.headers(tokens)
        value = checked_json(await self.http.native.get(self.base + "/dsh/profile", headers=headers), unified=False)
        _require(
            isinstance(value, dict)
            and isinstance(value.get("user"), dict)
            and isinstance(value.get("tenant"), dict)
            and value["user"].get("id") == str(self.user_id)
            and value["tenant"].get("id") == "1",
            "Native identity differs from the selected platform actor/deployment",
        )
        return value

    async def models(self, tokens):
        value = checked_json(
            await self.http.native.get(self.base + "/dsh/models", headers=self.headers(tokens)), unified=False
        )
        rows = value.get("data") if isinstance(value, dict) else None
        _require(isinstance(rows, list) and bool(rows), "Ordinary native actor has no observable authorized model")
        identifiers = [row.get("id") for row in rows if isinstance(row, dict)]
        _require(
            len(identifiers) == len(rows)
            and all(
                isinstance(item, str) and item.startswith("bisheng:") and item[8:].isdecimal() for item in identifiers
            )
            and len(set(identifiers)) == len(identifiers),
            "Native catalog contains invalid or duplicate governed model identifiers",
        )
        return rows

    async def rotate(self, tokens):
        value = await refresh_desktop_session(self.http.native, tokens["refresh_token"], api_base=self.base)
        value = {key: Secret(item) if key in {"access_token", "refresh_token"} else item for key, item in value.items()}
        _require(value.get("session_id") == tokens["session_id"], "Refresh switched the owned session")
        _require(
            value["access_token"] != tokens["access_token"] and value["refresh_token"] != tokens["refresh_token"],
            "Refresh did not rotate the complete native credentials",
        )
        self.sessions[value["session_id"]] = value
        await self.profile(value)
        return value

    async def logout(self, tokens):
        await logout_desktop_session(self.http.native, tokens["access_token"], api_base=self.base)
        self.sessions.pop(tokens["session_id"], None)

    async def model_exchange(self, tokens, scenario, *, word="", expected=1, deadline=90):
        before = await wait_until(self.http.provider_totals, lambda value: value["active"] == 0, timeout=40)
        attributed = await self.http.provider_counts(scenario)
        response = await self.http.native.post(
            self.base + "/dsh/chat/completions",
            headers=self.headers(tokens),
            json={
                "model": f"bisheng:{self.http.settings.chat_model_id}",
                "stream": False,
                "messages": [{"role": "user", "content": f"F111_SCENARIO:{scenario} {word}"}],
            },
            timeout=deadline,
        )
        after = await self.http.provider_totals()
        observed = await self.http.provider_counts(scenario)
        physical_delta = after["model_posts"] - before["model_posts"]
        attributed_delta = observed["requests"] - attributed["requests"]
        _require(
            physical_delta == expected and attributed_delta == expected,
            "Observed physical and attributed model request delta differs from expected admission",
        )
        self.record("f111_model_http_status", response.status_code)
        self.record("f111_model_physical_delta", physical_delta)
        self.record("f111_model_attributed_delta", attributed_delta)
        return response

    async def scenario(self):
        identifier = self.http.settings.prefix + "identity-" + uuid.uuid4().hex[:8]
        self.scenarios.append(identifier)
        await self.http.provider_scenario(identifier, text="Safe synthetic reply.")
        return identifier

    async def cleanup(self):
        failures = 0
        for tokens in tuple(self.sessions.values()):
            try:
                await self.logout(tokens)
            except (AssertionError, httpx.HTTPError):
                failures += 1
        _require(failures == 0, "One or more test-owned native sessions could not be revoked")


@pytest_asyncio.fixture
async def live_identity(record_property):
    if os.environ.get("PYTEST_XDIST_WORKER"):
        raise pytest.UsageError("Live identity/policy acceptance must run serially")
    user_file = os.environ.get("DSH_E2E_USER_SESSION_FILE")
    user_id = os.environ.get("DSH_E2E_USER_ID", "")
    if not user_file or not user_id.isascii() or not user_id.isdecimal() or not 0 < int(user_id) <= 2**63 - 1:
        raise pytest.UsageError(
            "Live identity acceptance requires an explicit ordinary-user session and positive user id"
        )
    settings = LiveSafetySettings.from_env(require_models=False)
    ordinary = LiveSafetySettings.from_env(dict(os.environ) | {"DSH_E2E_SESSION_FILE": user_file}, require_models=False)
    _require(ordinary.platform_token != settings.platform_token, "Management and ordinary sessions must be separate")
    async with LiveSafetyHTTP(settings) as http:
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as browser:
            actor = checked_json(
                await browser.get(settings.api_base + "/user/info", headers=auth_headers(ordinary.platform_token))
            )
        _require(
            isinstance(actor, dict)
            and actor.get("user_id") == int(user_id)
            and actor.get("is_global_super") is False
            and actor.get("leaf_tenant_id") == 1,
            "Selected platform actor must be the explicit non-global user in tenant one",
        )
        run = IdentityRun(http, ordinary, int(user_id), record_property)
        try:
            yield run
        finally:
            await run.cleanup()


async def test_real_pkce_profile_catalog_and_repeated_identity(live_identity):
    """Coverage AC: AC-13, AC-16. Actual PKCE identity/catalog, not a profile-call-count claim."""
    run = live_identity
    tokens = await run.issue()
    rows = await run.models(tokens)
    for _ in range(3):
        await run.profile(tokens)
    run.record("f111_native_identity", "pkce_profile_catalog_repeated_identity_confirmed")
    run.record("f111_authorized_model_count", len(rows))


async def test_complete_issued_credentials_and_refresh_keep_current_verified_identity(live_identity):
    """Coverage AC: AC-13, AC-16. Separate issued credentials and refresh do not change verified identity."""
    run = live_identity
    first, second = await run.issue(), await run.issue()
    _require(first["session_id"] != second["session_id"], "Independent PKCE exchanges reused an owned session")
    _require(first["access_token"] != second["access_token"], "Independent PKCE credentials are identical")
    refreshed = await run.rotate(first)
    await run.profile(second)
    await run.models(refreshed)
    run.record("f111_native_refresh", "two_real_sessions_and_refresh_identity_confirmed")


async def test_logout_rejects_old_access_and_refresh_on_backend_identity_routes(live_identity):
    """Coverage AC: AC-16, AC-17. Backend checks revocation; Gateway cache invalidation is not inferred."""
    run = live_identity
    original = await run.issue()
    current = await run.rotate(original)
    await run.logout(current)
    for tokens in (original, current):
        for path in ("/dsh/profile", "/dsh/models"):
            _native_error(await run.http.native.get(run.base + path, headers=run.headers(tokens)), "session_revoked")
    _native_error(
        await run.http.native.post(
            run.base + "/dsh/token", json={"grant_type": "refresh_token", "refresh_token": current["refresh_token"]}
        ),
        "session_revoked",
    )
    run.record("f111_backend_revocation", "old_and_refreshed_access_rejected_session_revoked")


async def test_administrative_visibility_guard_is_independent_of_native_identity(live_identity):
    """Coverage AC: AC-07, AC-08. Real admin allowed/ordinary denied, without invoking licensed Gateway policy."""
    run = live_identity
    tokens = await run.issue()
    rows = await run.models(tokens)
    owned = next((row for row in rows if row["id"] == f"bisheng:{run.http.settings.chat_model_id}"), None)
    _require(
        owned is not None and owned.get("display_name", "").startswith(run.http.settings.prefix),
        "Management denial test requires the explicit test-owned model",
    )
    model_id = owned["id"].removeprefix("bisheng:")
    path = run.base + f"/dsh/admin/models/{model_id}/visibility"
    before = checked_json(await run.http.admin.get(path, params={"tenant_id": 1}))
    _require(isinstance(before, dict) and type(before.get("version")) is int, "Admin visibility snapshot missing")
    body = {key: before[key] for key in ("version", "everyone", "subjects", "credit_multiplier")}
    async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as ordinary:
        for method in ("GET", "PUT"):
            response = await ordinary.request(
                method,
                path,
                params={"tenant_id": 1},
                headers={**auth_headers(run.user_settings.platform_token), "Origin": run.http.settings.platform_origin},
                **({"json": body} if method == "PUT" else {}),
            )
            try:
                envelope = response.json()
            except ValueError:
                raise LiveSafetyError("Management denial did not return its business envelope") from None
            _require(
                response.status_code in {200, 403}
                and isinstance(envelope, dict)
                and envelope.get("status_code") == 19801,
                "Ordinary actor was not denied by the real platform administrator guard",
            )
    after = checked_json(await run.http.admin.get(path, params={"tenant_id": 1}))
    _require(after == before, "Rejected ordinary-user writes changed model visibility")
    run.record("f111_management_guard", "admin_read_allowed_ordinary_get_put_denied_19801")


@pytest_asyncio.fixture
async def live_policy(live_identity):
    run = live_identity
    if os.environ.get("DSH_E2E_EXCLUSIVE_PROVIDER") != "1" or not run.http.settings.allow_policy_mutation:
        raise pytest.UsageError(
            "Policy tests require explicit exclusive provider and policy-mutation window permission"
        )
    response = await run.http.admin.get(
        run.base.removesuffix("/api/v1") + "/api/sensitive/dsh/capabilities", params={"tenant_id": 1}
    )
    try:
        envelope = response.json()
    except ValueError:
        raise LiveSafetyError("Safety capabilities returned invalid JSON") from None
    if isinstance(envelope, dict) and envelope.get("status_code", envelope.get("statusCode")) == 11001:
        raise pytest.UsageError("Deployment license is unavailable (11001); policy acceptance has not started")
    capability = checked_json(response)
    _require(
        isinstance(capability, dict)
        and capability.get("available") is True
        and capability.get("enabled") is True
        and capability.get("configuration_ready") is True,
        "Licensed Gateway safety deployment is not ready/enabled",
    )
    tokens = await run.issue()
    rows = await run.models(tokens)
    identifier = run.http.settings.chat_model_id
    model = next((row for row in rows if row["id"] == f"bisheng:{identifier}"), None)
    _require(
        identifier is not None
        and model is not None
        and model.get("display_name", "").startswith(run.http.settings.prefix),
        "Policy tests require an explicit, authorized, test-owned Chat model",
    )
    visibility = checked_json(await run.http.admin.get(run.base + f"/dsh/admin/models/{identifier}/visibility"))
    _require(visibility.get("everyone") is False, "Test model must remain explicitly private")
    try:
        async with SafetyPolicyLease(run.http, tenant_id=1) as lease:
            yield run, tokens, lease
    finally:
        for scenario in run.scenarios:
            run.http.owned.require("scenario", scenario, scenario)
            path = run.http.settings.provider_control_url + "/__control/scenarios/" + scenario
            current = await run.http.control.get(path)
            if current.status_code == 400:
                # A failed scenario registration may leave nothing to remove.
                _require(current.json().get("error", {}).get("code") == "test_invalid", "Scenario lookup failed")
                continue
            checked_json(current, unified=False)
            await wait_until(
                lambda scenario=scenario: run.http.provider_counts(scenario),
                lambda value: value["active"] == 0,
                timeout=40,
            )
            checked_json(await run.http.control.delete(path), unified=False)
            removed = await run.http.control.get(path)
            _require(
                removed.status_code == 400 and removed.json().get("error", {}).get("code") == "test_invalid",
                "Owned provider scenario was not removed",
            )


async def test_policy_validation_cas_and_post_window_input_block(live_policy):
    """Coverage AC: AC-06, AC-09, AC-10, AC-11. Single-Gateway observation after the advertised update window."""
    run, tokens, lease = live_policy
    await lease.save(
        enabled=False, input_enabled=False, output_enabled=False, words_types=["2"], custom_words="", auto_reply=""
    )
    await asyncio.sleep(5.25)
    before = await lease.read()
    desired = {key: before[key] for key in POLICY_FIELDS}
    for invalid in (
        {"enabled": True, "input_enabled": True, "custom_words": "", "auto_reply": NOTICE},
        {"enabled": True, "input_enabled": True, "custom_words": "f111-test-word", "auto_reply": ""},
        {"enabled": True, "input_enabled": True, "custom_words": "f111-test-word", "auto_reply": "x" * 2049},
    ):
        _policy_error(
            await run.http.admin.put(
                lease.path, params={"tenant_id": 1}, json={"expected_version": before["version"], **desired, **invalid}
            ),
            400,
        )
        _require(await lease.read() == before, "Invalid policy changed the committed snapshot")
    scenario = await run.scenario()
    word = "f111-policy-word-" + uuid.uuid4().hex[:12]
    positive = await run.model_exchange(tokens, scenario, word=word)
    body = checked_json(positive, unified=False)
    _require(
        body.get("choices", [{}])[0].get("message", {}).get("content") == "Safe synthetic reply.",
        "Positive control did not return the registered provider response",
    )
    committed = await lease.save(
        enabled=True, input_enabled=True, output_enabled=False, custom_words=word, auto_reply=NOTICE
    )
    started = time.monotonic()
    # Match the protocol suite: five-second publication window plus 250ms scheduler margin.
    # This is a post-window observation, not a precise multi-replica propagation latency measurement.
    await asyncio.sleep(5.25)
    elapsed = time.monotonic() - started
    blocked = await run.model_exchange(tokens, scenario, word=word, expected=0)
    try:
        value = blocked.json()
    except ValueError:
        raise LiveSafetyError("Policy blocking result was not JSON") from None
    _require(
        blocked.status_code == 403
        and isinstance(value, dict)
        and isinstance(value.get("error"), dict)
        and value["error"].get("code") == "content_blocked"
        and value["error"].get("message") == NOTICE
        and "choices" not in value,
        "New policy did not explicitly block input after the advertised publication window",
    )
    stale = {"expected_version": before["version"], **desired}
    _policy_error(await run.http.admin.put(lease.path, params={"tenant_id": 1}, json=stale), 409)
    _require(await lease.read() == committed, "CAS conflict overwrote the successful policy")
    run.record("f111_policy_commit_version", committed["version"])
    run.record("f111_policy_post_window_wait_seconds", round(elapsed, 6))


async def test_gateway_policy_rejects_ordinary_platform_actor(live_policy):
    """Coverage AC: AC-07, AC-08. Licensed admin positive read does not authorize the ordinary actor."""
    run, _, lease = live_policy
    before = await lease.read()
    command = {"expected_version": before["version"], **{key: before[key] for key in POLICY_FIELDS}}
    async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as ordinary:
        for method in ("GET", "PUT"):
            response = await ordinary.request(
                method,
                lease.path,
                params={"tenant_id": 1},
                headers={**auth_headers(run.user_settings.platform_token), "Origin": run.http.settings.platform_origin},
                **({"json": command} if method == "PUT" else {}),
            )
            _policy_error(response, 403)
    _require(await lease.read() == before, "Rejected policy management changed the committed snapshot")
    run.record("f111_gateway_management_guard", "ordinary_get_put_denied_403")


async def test_revoked_native_session_is_not_model_permission(live_policy):
    """Coverage AC: AC-16, AC-17. Revocation blocks a warmed credential; cache-hit location remains unobserved."""
    run, tokens, lease = live_policy
    await lease.save(
        enabled=True,
        input_enabled=True,
        output_enabled=False,
        words_types=["2"],
        custom_words="f111-absent-" + uuid.uuid4().hex,
        auto_reply=NOTICE,
    )
    await asyncio.sleep(5.25)
    scenario = await run.scenario()
    positive = checked_json(await run.model_exchange(tokens, scenario), unified=False)
    _require(
        positive.get("choices", [{}])[0].get("message", {}).get("content") == "Safe synthetic reply.",
        "Model permission positive control failed",
    )
    await run.logout(tokens)
    rejected = await run.model_exchange(tokens, scenario, expected=0)
    # An expired identity-cache entry may revalidate at preflight; neither path may invoke a model.
    _native_error(rejected, {"session_revoked", "invalid_access_token"})
    run.record("f111_model_revocation", "revoked_credential_rejected_zero_second_physical_model_post")
