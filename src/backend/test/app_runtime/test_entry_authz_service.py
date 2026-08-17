"""T032 — the five-step entry verdict, in the order that defines what leaks.

Every test here is a statement about what a *stranger* can learn from
``/apps/{slug}``. The ordering assertions are as load bearing as the allow
path: a correct verdict reached in the wrong order still tells an unauthenticated
visitor which application names exist.
"""

from __future__ import annotations

import json
from urllib.parse import unquote

import jwt
import pytest

from bisheng.app_runtime.domain.constants import AppState

pytestmark = pytest.mark.usefixtures("app_db")

OBO_SECRET = "f054-obo-secret-not-the-session-one"


@pytest.fixture()
def runtime_enabled(monkeypatch):
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.app_runtime, "enabled", True, raising=False)
    monkeypatch.setattr(settings.app_runtime, "obo_secret", OBO_SECRET, raising=False)
    monkeypatch.setattr(settings.app_runtime, "obo_ttl_seconds", 900, raising=False)
    return settings


@pytest.fixture()
def visible(monkeypatch):
    """``visible.allow = False`` flips the visible-scope answer.

    The F048 runtime itself is covered by ``test_app_permission_registration``;
    what this module owns is what the entry path *does* with each answer.
    """
    from bisheng.app_runtime.domain.services import entry_authz_service

    state = {"allow": True, "calls": []}

    async def _check(actor, *, resource_type, resource_id, action):
        state["calls"].append((resource_type, resource_id, action))
        return state["allow"]

    monkeypatch.setattr(entry_authz_service, "check_business_action", _check)
    return state


@pytest.fixture()
def no_tenant_blacklist(monkeypatch):
    """Redis is not available in a unit run; the blacklist answers "not disabled"."""
    from bisheng.app_runtime.domain.services import entry_authz_service

    disabled: set[int] = set()

    async def _disabled(tenant_id: int) -> bool:
        return int(tenant_id) in disabled

    monkeypatch.setattr(entry_authz_service, "_tenant_disabled", _disabled)
    return disabled


def _token(user_id: int, user_name: str = "u", tenant_id: int = 1, token_version: int = 0) -> str:
    from bisheng.user.domain.services.auth import AuthJwt

    return AuthJwt().create_access_token(
        {"user_id": user_id, "user_name": user_name, "tenant_id": tenant_id, "token_version": token_version}
    )


async def _verdict(slug, token, **kwargs):
    from bisheng.app_runtime.domain.services.entry_authz_service import authorize_entry

    return await authorize_entry(slug=slug, access_token=token, request_id="req-1", **kwargs)


class TestStepOrder:
    async def test_layer_not_deployed_short_circuits(self, app_db, app_factory, monkeypatch):
        """AC-30 — answered before the session check, so a visitor to an
        environment without the factory is never bounced through a login."""
        from bisheng.common.services.config_service import settings

        monkeypatch.setattr(settings.app_runtime, "enabled", False, raising=False)
        _app, _ = await app_factory(slug="any-app", state=AppState.ONLINE.value)

        verdict = await _verdict("any-app", None)
        assert verdict["decision"] == "not_enabled"
        assert "app_id" not in verdict, "an undeployed layer must not confirm that the app exists"

    async def test_no_token_returns_login_handoff(self, app_db, app_factory, runtime_enabled):
        """AC-27 — no session is a hand-off to login, not a 401 page."""
        _app, _ = await app_factory(slug="needs-login", state=AppState.ONLINE.value)
        verdict = await _verdict("needs-login", None)
        assert verdict["decision"] == "login"

    async def test_token_version_mismatch_denied(
        self, app_db, app_factory, app_owner, runtime_enabled, no_tenant_blacklist
    ):
        """K7 — a local JWT decode would accept this token forever. The platform
        invalidated it, and the entry path must consult the same counter."""
        _app, _ = await app_factory(slug="tv-app", state=AppState.ONLINE.value)
        stale = _token(app_owner.user_id, token_version=9)

        assert (await _verdict("tv-app", stale))["decision"] == "login"

    async def test_disabled_account_denied(self, app_db, app_factory, app_owner, runtime_enabled, no_tenant_blacklist):
        """A disabled account keeps a syntactically valid JWT until it expires."""
        from bisheng.user.domain.models.user import User

        _app, _ = await app_factory(slug="disabled-user-app", state=AppState.ONLINE.value)
        async with app_db() as session:
            row = await session.get(User, app_owner.user_id)
            row.delete = 1
            session.add(row)
            await session.commit()

        assert (await _verdict("disabled-user-app", _token(app_owner.user_id)))["decision"] == "login"

    async def test_disabled_tenant_denied(self, app_db, app_factory, app_owner, runtime_enabled, no_tenant_blacklist):
        """Tenant disable is a Redis blacklist the middleware reads; the entry
        path reads the same one rather than trusting the token's tenant claim."""
        _app, _ = await app_factory(slug="disabled-tenant-app", state=AppState.ONLINE.value)
        no_tenant_blacklist.add(1)

        assert (await _verdict("disabled-tenant-app", _token(app_owner.user_id)))["decision"] == "login"

    @pytest.mark.parametrize("state", (AppState.DRAFT.value, AppState.PENDING_CAPACITY.value, AppState.DELETED.value))
    async def test_draft_pending_deleted_and_nonexistent_return_same_page(
        self, app_db, app_factory, app_owner, runtime_enabled, no_tenant_blacklist, visible, state
    ):
        """AC-29 — four different truths, one answer. Any difference between them
        turns the entry path into an application-name oracle."""
        _app, _ = await app_factory(slug=f"hidden-{state}", state=state)
        token = _token(app_owner.user_id)

        hidden = await _verdict(f"hidden-{state}", token)
        missing = await _verdict("no-such-app-at-all", token)

        assert hidden == missing == {"decision": "not_found"}
        assert visible["calls"] == [], "a not-yet-online app is never even resolved for permissions"


class TestVisibleScope:
    async def test_not_visible_returns_forbidden_with_app_name_and_owner(
        self, app_db, app_factory, app_owner, normal_user, runtime_enabled, no_tenant_blacklist, visible
    ):
        """AC-28 — the visitor already has the link; the useful answer is who to ask."""
        _app, _ = await app_factory(slug="private-app", state=AppState.ONLINE.value, name="Private App")
        visible["allow"] = False

        verdict = await _verdict("private-app", _token(normal_user.user_id))

        assert verdict["decision"] == "forbidden"
        assert verdict["app_name"] == "Private App"
        assert verdict["owner_name"] == app_owner.user_name
        assert "headers" not in verdict and verdict.get("obo_token") is None

    async def test_visible_scope_uses_the_use_action(
        self, app_db, app_factory, app_owner, runtime_enabled, no_tenant_blacklist, visible
    ):
        """D9 — ``use`` is the action the permission dialog's viewer tier grants,
        so "who can open it" matches what the owner sees when sharing."""
        app, _ = await app_factory(slug="action-app", state=AppState.ONLINE.value)
        await _verdict("action-app", _token(app_owner.user_id))
        assert visible["calls"] == [("app", app.id, "use")]

    async def test_stopped_returns_stopped_page_only_for_visible_users(
        self, app_db, app_factory, app_owner, normal_user, runtime_enabled, no_tenant_blacklist, visible
    ):
        """AC-29 — inside the scope you learn it is stopped; outside it, you do not
        learn it exists at all."""
        _app, _ = await app_factory(slug="paused-app", state=AppState.STOPPED.value, name="Paused App")

        inside = await _verdict("paused-app", _token(app_owner.user_id))
        assert inside["decision"] == "stopped" and inside["app_name"] == "Paused App"

        visible["allow"] = False
        outside = await _verdict("paused-app", _token(normal_user.user_id))
        assert outside["decision"] == "forbidden"

    async def test_fga_unavailable_fail_closed_16146(
        self, app_db, app_factory, app_owner, runtime_enabled, no_tenant_blacklist, fga_down
    ):
        """AC-12 / INV-30 — "could not decide" is a refusal. There is no branch
        in this service that turns it into a pass."""
        _app, _ = await app_factory(slug="fga-down-app", state=AppState.ONLINE.value)

        verdict = await _verdict("fga-down-app", _token(app_owner.user_id))

        assert verdict["decision"] == "unavailable"
        assert verdict["code"] == 16146
        assert "headers" not in verdict


class TestInjectionMaterial:
    async def test_headers_material_complete(
        self, app_db, app_factory, chinese_name_user, runtime_enabled, no_tenant_blacklist, visible
    ):
        """AC-31 — the ten headers app-proxy injects, all derivable from one answer."""
        app, _ = await app_factory(slug="material-app", state=AppState.ONLINE.value)

        verdict = await _verdict("material-app", _token(chinese_name_user.user_id, chinese_name_user.user_name))

        material = verdict["headers"]
        assert set(material) == {
            "X-BiSheng-User-Id",
            "X-BiSheng-User-Name",
            "X-BiSheng-Tenant-Id",
            "X-BiSheng-Dept-Id",
            "X-BiSheng-Dept-Name",
            "X-BiSheng-Dept-Path",
            "X-BiSheng-Subject-Kind",
            "X-BiSheng-App-Id",
            "X-BiSheng-Access-Token",
            "X-BiSheng-Request-Id",
        }
        assert material["X-BiSheng-Subject-Kind"] == "human", "AC-31 requires the subject type"
        # The *business* key, not the autoincrement id: an app authorising on a
        # surrogate primary key would break the moment the row is re-seeded.
        assert material["X-BiSheng-Dept-Id"] == chinese_name_user.department_business_key
        assert material["X-BiSheng-App-Id"] == app.id

    async def test_chinese_name_percent_encoded_roundtrip(
        self, app_db, app_factory, chinese_name_user, runtime_enabled, no_tenant_blacklist, visible
    ):
        """Pit 9 — HTTP headers are latin-1, and English test accounts hide this."""
        _app, _ = await app_factory(slug="cjk-app", state=AppState.ONLINE.value)

        material = (await _verdict("cjk-app", _token(chinese_name_user.user_id)))["headers"]

        for header, expected in (
            ("X-BiSheng-User-Name", chinese_name_user.user_name),
            ("X-BiSheng-Dept-Name", chinese_name_user.department_name),
        ):
            assert material[header].isascii(), f"{header} would be rejected or mangled by h11"
            assert unquote(material[header]) == expected
        assert material["X-BiSheng-Dept-Path"].isascii()

    async def test_obo_token_signed_with_dedicated_secret(
        self, app_db, app_factory, app_owner, runtime_enabled, no_tenant_blacklist, visible
    ):
        """AC-34 — a separate key, or the token doubles as a session cookie."""
        from bisheng.app_runtime.domain.services.entry_authz_service import OBO_AUDIENCE
        from bisheng.common.services.config_service import settings

        app, _ = await app_factory(slug="obo-app", state=AppState.ONLINE.value)
        verdict = await _verdict("obo-app", _token(app_owner.user_id))
        token = verdict["obo_token"]

        claims = jwt.decode(token, OBO_SECRET, algorithms=["HS256"], audience=OBO_AUDIENCE)
        assert json.loads(claims["sub"]) == {
            "app_id": app.id,
            "user_id": app_owner.user_id,
            "tenant_id": 1,
            "subject_kind": "human",
        }
        assert claims["exp"] - claims["iat"] == 900

        with pytest.raises(jwt.InvalidSignatureError):
            jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], audience=OBO_AUDIENCE)

    async def test_no_obo_token_when_secret_equals_session_secret(
        self, app_db, app_factory, app_owner, runtime_enabled, no_tenant_blacklist, visible, monkeypatch
    ):
        """A shared secret is a misconfiguration, and signing anyway would hand
        every hosted app a valid platform session."""
        from bisheng.common.services.config_service import settings

        monkeypatch.setattr(settings.app_runtime, "obo_secret", settings.jwt_secret, raising=False)
        _app, _ = await app_factory(slug="shared-secret-app", state=AppState.ONLINE.value)

        verdict = await _verdict("shared-secret-app", _token(app_owner.user_id))
        assert verdict["decision"] == "allow"
        assert verdict["obo_token"] is None
        assert "X-BiSheng-Access-Token" not in verdict["headers"]
