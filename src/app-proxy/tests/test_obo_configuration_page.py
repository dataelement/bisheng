"""Coverage: F054 AC-70, AC-71; refusal is not an anonymous app response."""

import pytest

from app_proxy.pages import render_page


@pytest.fixture(autouse=True)
def wired():
    """Pure page rendering needs no package-wide fake HTTP/WebSocket servers."""
    yield


@pytest.mark.parametrize(
    ("locale", "text"),
    [
        ("zh-Hans", "本环境配置不完整，请联系平台管理员"),
        ("en", "This environment is not fully configured"),
        ("ja", "環境設定が不完全です"),
    ],
)
def test_configuration_refusal_has_localized_operator_hint(locale, text):
    page = render_page("unavailable", reason="identity_config_incomplete", accept_language=locale)
    assert text in page
    assert 'http-equiv="refresh"' not in page


@pytest.mark.parametrize("preview", [False, True])
async def test_prior_allow_is_rechecked_after_configuration_invalidates(preview):
    import secrets

    import httpx

    from app_proxy.clients import BackendAuthzClient

    calls = []

    async def response(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={"decision": "allow", "headers": {"X-BiSheng-User-Id": "7"}}
            if len(calls) == 1
            else {"decision": "unavailable", "reason": "identity_config_incomplete"},
        )

    client = BackendAuthzClient("http://backend", secrets.token_hex(32), transport=httpx.MockTransport(response))
    try:
        method = client.authorize_preview if preview else client.authorize
        target = {"session": "preview-a"} if preview else {"slug": "app-a"}
        first = await method(**target, access_token="session", request_id="1")
        second = await method(**target, access_token="session", request_id="2")
        assert first["decision"] == "allow"
        assert second["decision"] == "unavailable" and not second["cache_hit"]
        assert len(calls) == 2
    finally:
        await client.aclose()
