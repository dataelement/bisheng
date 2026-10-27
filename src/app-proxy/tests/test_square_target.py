"""Visitor fallback links must enter the client app square, not the builder."""

import pytest

from app_proxy.config import DEFAULT_SQUARE_URL, load_config, set_config
from app_proxy.pages import render_page
from tests.conftest import NAVIGATE_HEADERS
from tests.fakes import deny_response


@pytest.mark.parametrize("configured", [None, "", "/custom/workspace/apps/explore"])
def test_square_target_environment_override(monkeypatch, configured):
    if configured is None:
        monkeypatch.delenv("APP_PROXY_SQUARE_URL", raising=False)
    else:
        monkeypatch.setenv("APP_PROXY_SQUARE_URL", configured)
    assert load_config().square_url == (configured or "/workspace/apps/explore")


@pytest.mark.parametrize("kind", ["stopped", "forbidden", "not_found"])
def test_default_page_links_to_actual_square_route(kind):
    assert DEFAULT_SQUARE_URL == "/workspace/apps/explore"
    assert 'href="/workspace/apps/explore"' in render_page(kind)


@pytest.mark.parametrize("custom", [None, "/custom/workspace/apps/explore"])
def test_stopped_navigation_uses_configured_square(logged_in, fake_backend, wired, custom):
    if custom:
        set_config(wired.with_overrides(square_url=custom))
    fake_backend.response = deny_response("stopped", app_state="stopped")
    response = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
    assert response.status_code == 200
    assert f'href="{custom or DEFAULT_SQUARE_URL}"' in response.text
    assert 'href="/workspace"' not in response.text
