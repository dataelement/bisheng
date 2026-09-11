import pytest

from bisheng.open_api.domain.scopes import (
    ISSUABLE_OPEN_API_SCOPE_CODES,
    OPEN_API_SCOPES,
    get_open_api_scope_marker,
    open_api_scope,
)


def test_scope_marker_carries_modes_and_session_semantics():
    @open_api_scope("chat:invoke", modes=("S",), session=True)
    async def endpoint():
        return None

    marker = get_open_api_scope_marker(endpoint)
    assert marker is not None
    assert marker.scope == "chat:invoke"
    assert marker.modes == {"S"}
    assert marker.session is True


def test_unknown_scope_and_invalid_modes_fail_at_import_time():
    with pytest.raises(ValueError):
        open_api_scope("not-registered")
    with pytest.raises(ValueError):
        open_api_scope("knowledge:read", modes=())


def test_undeployed_extension_scopes_are_not_issuable():
    assert {"model:invoke", "identity:read", "app:manage"}.isdisjoint(ISSUABLE_OPEN_API_SCOPE_CODES)
    assert "delegate" in ISSUABLE_OPEN_API_SCOPE_CODES


def test_issuable_scopes_have_localized_presentation_metadata():
    scopes = [scope for scope in OPEN_API_SCOPES if scope.issuable]

    assert [scope.group for scope in scopes] == [
        "workflow",
        "workflow",
        "assistant",
        "assistant",
        "assistant",
        "knowledge",
        "knowledge",
        "delegation",
    ]
    assert all(scope.label_key.startswith("openApiManagement.scopes.") for scope in scopes)
    assert all(scope.desc_key.startswith("openApiManagement.scopes.") for scope in scopes)
    assert all(scope.endpoints for scope in scopes if scope.code != "delegate")
