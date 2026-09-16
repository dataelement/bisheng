"""Issue-time policy for the extension scopes (migration plan M7).

* ``app:manage`` is issuable exactly while ``open_platform.enabled`` is on;
  ``model:invoke`` / ``identity:read`` stay unissuable (F051 / F052 pending).
* ``delegate`` and the local development toolkit scopes are refused together,
  on issue and on edit alike (伴生 PRD §4.2.4 / AC-48, release-contract INV-31).
* A personal token never receives an extension scope (伴生 PRD §4.10.3).
"""

from types import SimpleNamespace

import pytest

from bisheng.common.errcode.open_api import (
    OpenApiDelegateExclusiveScopeError,
    OpenApiExtensionScopeNotDeployedError,
    PersonalTokenScopeInvalidError,
)
from bisheng.common.services.config_service import settings
from bisheng.open_api.api.endpoints.service_account_keys import list_open_api_scopes
from bisheng.open_api.domain.models.api_credential import (
    SUBJECT_KIND_NATURAL_PERSON,
    SUBJECT_KIND_SERVICE_ACCOUNT,
)
from bisheng.open_api.domain.schemas.credential import (
    DelegateScopeInput,
    KeyIssueRequest,
    KeyUpdateRequest,
)
from bisheng.open_api.domain.scopes import OPEN_API_SCOPE_MAP
from bisheng.open_api.domain.services.credential_service import CredentialService

DELEGATE_TARGET = [DelegateScopeInput(subject_type="user", subject_id=9)]


@pytest.fixture
def open_platform_enabled(monkeypatch):
    monkeypatch.setattr(settings.open_platform, "enabled", True)


@pytest.fixture
def open_platform_disabled(monkeypatch):
    monkeypatch.setattr(settings.open_platform, "enabled", False)


@pytest.fixture
def delegate_target_exists(monkeypatch):
    async def active_user(user_id):
        return SimpleNamespace(user_id=user_id, tenant_id=1)

    monkeypatch.setattr(
        "bisheng.open_api.domain.services.delegate_scope_service.OwnerRepository.get_active_natural_person",
        active_user,
    )


def test_app_manage_is_refused_while_open_platform_is_off(open_platform_disabled):
    with pytest.raises(OpenApiExtensionScopeNotDeployedError):
        CredentialService.validate_scopes(["knowledge:read", "app:manage"])


def test_app_manage_is_accepted_once_open_platform_is_on(open_platform_enabled):
    assert CredentialService.validate_scopes(["knowledge:read", "app:manage"]) == ["knowledge:read", "app:manage"]


@pytest.mark.parametrize("scope", ["model:invoke"])
def test_pending_extension_scopes_stay_unissuable_even_with_open_platform(open_platform_enabled, scope):
    with pytest.raises(OpenApiExtensionScopeNotDeployedError):
        CredentialService.validate_scopes([scope])


def test_identity_read_becomes_issuable_with_the_mcp_face(open_platform_enabled):
    """F052 shipped the three tools that read it, so an administrator may now tick it."""

    assert CredentialService.validate_scopes(["identity:read"]) == ["identity:read"]


def test_identity_read_is_still_refused_without_the_open_capability_layer(open_platform_disabled):
    with pytest.raises(OpenApiExtensionScopeNotDeployedError):
        CredentialService.validate_scopes(["identity:read"])


def test_app_manage_registers_the_four_app_factory_v2_routes():
    assert OPEN_API_SCOPE_MAP["app:manage"].endpoints == (
        ("GET", "/api/v2/apps/deploy-limits"),
        ("POST", "/api/v2/apps/deploy"),
        ("GET", "/api/v2/apps/deployments/{deployment_id}"),
        ("GET", "/api/v2/apps/{app_id}/logs"),
    )


async def test_service_account_issue_refuses_delegate_with_app_manage(
    open_api_db, fake_redis, open_platform_enabled, delegate_target_exists
):
    with pytest.raises(OpenApiDelegateExclusiveScopeError):
        await CredentialService.issue(
            tenant_id=1,
            subject_kind=SUBJECT_KIND_SERVICE_ACCOUNT,
            subject_id=7,
            request=KeyIssueRequest(
                name="mixed",
                scopes=["app:manage", "delegate"],
                delegate_scopes=DELEGATE_TARGET,
            ),
            created_by=3,
        )


async def test_edit_cannot_add_delegate_to_an_app_manage_key(
    open_api_db, fake_redis, open_platform_enabled, delegate_target_exists
):
    issued = await CredentialService.issue(
        tenant_id=1,
        subject_kind=SUBJECT_KIND_SERVICE_ACCOUNT,
        subject_id=7,
        request=KeyIssueRequest(name="cli", scopes=["app:manage"]),
        created_by=3,
    )
    assert issued.scopes == ["app:manage"]

    with pytest.raises(OpenApiDelegateExclusiveScopeError):
        await CredentialService.update(
            SUBJECT_KIND_SERVICE_ACCOUNT,
            7,
            issued.id,
            KeyUpdateRequest(scopes=["app:manage", "delegate"], delegate_scopes=DELEGATE_TARGET),
        )

    unchanged = await CredentialService.get_row(SUBJECT_KIND_SERVICE_ACCOUNT, 7, issued.id)
    assert list(unchanged.scopes) == ["app:manage"]


async def test_edit_cannot_add_app_manage_to_a_delegated_key(
    open_api_db, fake_redis, open_platform_enabled, delegate_target_exists
):
    issued = await CredentialService.issue(
        tenant_id=1,
        subject_kind=SUBJECT_KIND_SERVICE_ACCOUNT,
        subject_id=7,
        request=KeyIssueRequest(
            name="delegated",
            scopes=["knowledge:read", "delegate"],
            delegate_scopes=DELEGATE_TARGET,
        ),
        created_by=3,
    )

    with pytest.raises(OpenApiDelegateExclusiveScopeError):
        await CredentialService.update(
            SUBJECT_KIND_SERVICE_ACCOUNT,
            7,
            issued.id,
            KeyUpdateRequest(scopes=["knowledge:read", "delegate", "app:manage"]),
        )


async def test_personal_token_never_receives_app_manage(open_api_db, fake_redis, open_platform_enabled):
    with pytest.raises(PersonalTokenScopeInvalidError):
        await CredentialService.issue(
            tenant_id=1,
            subject_kind=SUBJECT_KIND_NATURAL_PERSON,
            subject_id=3,
            request=KeyIssueRequest(name="pat", scopes=["app:manage"]),
            created_by=3,
        )
    with pytest.raises(PersonalTokenScopeInvalidError):
        await CredentialService.issue(
            tenant_id=1,
            subject_kind=SUBJECT_KIND_NATURAL_PERSON,
            subject_id=3,
            request=KeyIssueRequest(name="pat", scopes=["knowledge:read", "app:manage"]),
            created_by=3,
        )


async def test_scope_catalog_offers_app_manage_only_with_open_platform(monkeypatch):
    monkeypatch.setattr(settings.open_platform, "enabled", False)
    hidden = (await list_open_api_scopes(_admin=None)).data
    assert hidden.open_platform_enabled is False
    assert "app:manage" not in {item.code for item in hidden.scopes}

    monkeypatch.setattr(settings.open_platform, "enabled", True)
    shown = (await list_open_api_scopes(_admin=None)).data
    codes = {item.code for item in shown.scopes}
    assert shown.open_platform_enabled is True
    assert "app:manage" in codes
    assert "identity:read" in codes  # F052 MCP face
    assert "model:invoke" not in codes
    app_manage = next(item for item in shown.scopes if item.code == "app:manage")
    assert app_manage.group == "local_dev_toolkit"
    assert [(endpoint.method, endpoint.path) for endpoint in app_manage.endpoints] == [
        ("GET", "/api/v2/apps/deploy-limits"),
        ("POST", "/api/v2/apps/deploy"),
        ("GET", "/api/v2/apps/deployments/{deployment_id}"),
        ("GET", "/api/v2/apps/{app_id}/logs"),
    ]
