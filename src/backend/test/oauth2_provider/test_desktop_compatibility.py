"""Desktop first-party sessions do not rename the persisted legacy OAuth client."""

from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import ValidationError

from bisheng.oauth2_provider.domain.repositories.client import OAuth2ClientRepository
from bisheng.oauth2_provider.domain.schemas.client import OAuth2ClientUpdate
from bisheng.oauth2_provider.domain.schemas.platform_exchange import OAuth2PlatformSubject
from test.oauth2_provider.test_oauth2_provider import _make_pkce, oauth2_env  # noqa: F401


@pytest.mark.parametrize("client_id", ["dsh-desktop", "third-party", "bisheng-desktop-other"])
def test_legacy_oauth_client_is_not_a_first_party_platform_subject(client_id):
    with pytest.raises(ValidationError):
        OAuth2PlatformSubject(
            user_id=7, tenant_id=9, client_id=client_id, expires_at=1, session_expires_at=1, reference={}
        )


def test_new_builtin_desktop_registration_uses_product_name(request):
    runtime, _ = request.getfixturevalue("oauth2_env")
    with runtime.auth._session_factory() as db:
        builtin = OAuth2ClientRepository(db).ensure_builtin_dsh_client()
        assert builtin.client_id == "dsh-desktop"
        assert builtin.client_name == "BiSheng Desktop"
        assert builtin.description == "Built-in public PKCE client for BiSheng Desktop native login."


async def test_existing_desktop_registration_and_refresh_survive_builtin_ensure(request):
    runtime, _ = request.getfixturevalue("oauth2_env")
    original = await runtime.clients.update_client(
        "dsh-desktop",
        OAuth2ClientUpdate(
            client_name="BiSheng Desktop (DSH)", description="Existing registration", require_consent=False
        ),
    )
    verifier, challenge = _make_pkce()
    redirect_uri = "http://127.0.0.1:45678/dsh/callback"
    request_id, _, _ = await runtime.auth.start_authorization(
        client_id="dsh-desktop",
        redirect_uri=redirect_uri,
        response_type="code",
        scope="openid offline_access",
        state=None,
        nonce=None,
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    consent = await runtime.auth.submit_consent(request_id=request_id, user_id=42, tenant_id=7, decision="approve")
    code = parse_qs(urlsplit(consent.redirect_uri).query)["code"][0]
    tokens = await runtime.auth.exchange_code(
        origin="https://bisheng.example",
        code=code,
        client_id="dsh-desktop",
        redirect_uri=redirect_uri,
        code_verifier=verifier,
        client_secret=None,
    )
    with runtime.auth._session_factory() as db:
        repo = OAuth2ClientRepository(db)
        ensured = repo.ensure_builtin_dsh_client()
        assert ensured.id == original.id
        assert ensured.client_id == "dsh-desktop"
        assert ensured.client_name == "BiSheng Desktop (DSH)"
        assert ensured.description == "Existing registration"
        assert ensured.require_consent is False
        assert repo.get_by_client_id("bisheng-desktop") is None
    assert (await runtime.auth.userinfo("Bearer " + tokens.access_token)).sub == "42"
    refreshed = await runtime.auth.refresh_access_token(
        origin="https://bisheng.example",
        refresh_token=tokens.refresh_token,
        client_id="dsh-desktop",
        client_secret=None,
    )
    assert refreshed.refresh_token != tokens.refresh_token
    assert (await runtime.auth.userinfo("Bearer " + refreshed.access_token)).sub == "42"
