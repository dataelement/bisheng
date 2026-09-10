import pytest

from bisheng.common.services.config_service import settings
from bisheng.open_api.domain.scopes import (
    ALWAYS_ISSUABLE_OPEN_API_SCOPE_CODES,
    LOCAL_DEV_TOOLKIT_SCOPE_CODES,
    OPEN_API_SCOPES,
    get_open_api_scope_marker,
    issuable_scope_codes,
    issuable_scopes,
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


def test_extension_scopes_are_not_issuable_without_open_platform(monkeypatch):
    monkeypatch.setattr(settings.open_platform, "enabled", False)

    assert LOCAL_DEV_TOOLKIT_SCOPE_CODES == {"model:invoke", "identity:read", "app:manage"}
    assert LOCAL_DEV_TOOLKIT_SCOPE_CODES.isdisjoint(issuable_scope_codes())
    assert LOCAL_DEV_TOOLKIT_SCOPE_CODES.isdisjoint(ALWAYS_ISSUABLE_OPEN_API_SCOPE_CODES)
    assert "delegate" in issuable_scope_codes()
    assert issuable_scope_codes() == ALWAYS_ISSUABLE_OPEN_API_SCOPE_CODES


def test_only_app_manage_becomes_issuable_with_open_platform(monkeypatch):
    monkeypatch.setattr(settings.open_platform, "enabled", True)

    codes = issuable_scope_codes()
    assert "app:manage" in codes
    assert {"model:invoke", "identity:read"}.isdisjoint(codes)
    assert codes == ALWAYS_ISSUABLE_OPEN_API_SCOPE_CODES | {"app:manage"}


def test_issuable_scopes_have_localized_presentation_metadata(monkeypatch):
    monkeypatch.setattr(settings.open_platform, "enabled", False)
    assert [scope.group for scope in issuable_scopes()] == [
        "workflow",
        "workflow",
        "assistant",
        "assistant",
        "assistant",
        "knowledge",
        "knowledge",
        "delegation",
    ]

    monkeypatch.setattr(settings.open_platform, "enabled", True)
    scopes = issuable_scopes()
    assert [scope.group for scope in scopes] == [
        "workflow",
        "workflow",
        "assistant",
        "assistant",
        "assistant",
        "knowledge",
        "knowledge",
        "local_dev_toolkit",
        "delegation",
    ]
    assert all(scope.label_key.startswith("openApiManagement.scopes.") for scope in scopes)
    assert all(scope.desc_key.startswith("openApiManagement.scopes.") for scope in scopes)
    assert all(scope.endpoints for scope in scopes if scope.code != "delegate")


def test_registry_maps_each_endpoint_to_exactly_one_scope():
    mapped = [endpoint for scope in OPEN_API_SCOPES for endpoint in scope.endpoints]
    assert len(mapped) == len(set(mapped))
