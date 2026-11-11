"""Actual registration/login adapters preserve guards and use the new policy."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlmodel import Session, select

from bisheng.common.errcode.user import AmbiguousAccountError, CaptchaError, NicknameValidationError, UserValidateError
from bisheng.database.models.user_role import UserRole
from bisheng.user.domain.models.user import UserCreate, UserLogin
from bisheng.user.domain.services.account_identity_service import AccountIdentityService
from test.user.f011_fixtures import identity_store, old_user  # noqa: F401


@pytest.fixture
def user_module(monkeypatch, tmp_path):
    settings_file = tmp_path / "account-settings.yaml"
    settings_file.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("config", settings_file.as_posix())
    from bisheng.user.domain.services import user as module

    configuration = SimpleNamespace(
        multi_tenant=SimpleNamespace(enabled=False),
        get_from_db=Mock(return_value=False),
        aget_from_db=AsyncMock(return_value=False),
    )
    monkeypatch.setattr(module, "settings", configuration)
    return module


async def test_registration_accepts_32_and_preserves_exact_accounts(user_module, identity_store, monkeypatch):  # noqa: F811
    """AC-04, AC-09, AC-15, AC-32: exercise the real formerly-30-character registration path."""
    engine, _ = identity_store
    service = user_module.UserService
    monkeypatch.setattr(service, "decrypt_md5_password_strict", lambda _value: "test-only-digest")
    monkeypatch.setattr(service, "_resolve_registration_tenant_id", AsyncMock(return_value=1))
    for method in (
        "_ensure_user_default_tenant_association",
        "_ensure_user_guest_department_membership",
        "areconcile_first_user_dashboard_permissions",
    ):
        monkeypatch.setattr(service, method, AsyncMock())
    monkeypatch.setattr(user_module.LegacyRBACSyncService, "sync_user_auth_created", AsyncMock())
    name = "中" * 32
    first = await service.user_register(
        UserCreate(user_name=name, external_id="Case01", password="cipher", source="wecom", delete=1)
    )
    second = await service.user_register(
        UserCreate(user_name=name, external_id="case01", password="cipher", default_roleid=1)
    )
    assert first.source == second.source == "local"
    assert first.delete == second.delete == 0
    assert first.user_name == second.user_name == name
    assert first.account_rule_version == second.account_rule_version == 1
    assert first.external_id == "Case01" and second.external_id == "case01"
    assert "password" not in first.model_dump()
    assert "account_match_key" not in first.model_dump()
    with Session(engine) as session:
        roles = session.exec(select(UserRole)).all()
        assert {(row.user_id, row.role_id) for row in roles} == {(first.user_id, 1), (second.user_id, 2)}


async def test_registration_rejects_33_before_any_creation(user_module, monkeypatch):
    """AC-04, AC-31: direct requests receive the common nickname policy error."""
    create = AsyncMock()
    monkeypatch.setattr(AccountIdentityService, "acreate_local", create)
    with pytest.raises(NicknameValidationError):
        await user_module.UserService.user_register(
            UserCreate(user_name="中" * 33, external_id="New01", password="cipher")
        )
    create.assert_not_awaited()


async def test_captcha_remains_before_identity_resolution(user_module, monkeypatch):
    """AC-15: neither account resolution nor password probes bypass captcha."""
    user_module.settings.aget_from_db.return_value = True
    resolve = AsyncMock()
    monkeypatch.setattr(AccountIdentityService, "aresolve_login", resolve)
    with pytest.raises(CaptchaError):
        await user_module.UserService.user_login(SimpleNamespace(), UserLogin(user_name="Case01", password="cipher"))
    resolve.assert_not_awaited()


async def test_login_does_not_try_passwords_to_resolve_ambiguity(user_module, monkeypatch):
    """AC-13: identity ambiguity is rejected before decryption and password counters."""
    monkeypatch.setattr(AccountIdentityService, "aresolve_login", AsyncMock(side_effect=AmbiguousAccountError()))
    decrypt = Mock()
    judge = AsyncMock()
    monkeypatch.setattr(user_module.UserService, "decrypt_md5_password", decrypt)
    monkeypatch.setattr(user_module.UserService, "judge_user_password", judge)
    with pytest.raises(AmbiguousAccountError):
        await user_module.UserService.user_login(SimpleNamespace(), UserLogin(user_name="old01", password="cipher"))
    decrypt.assert_not_called()
    judge.assert_not_awaited()


async def test_wrong_password_checks_only_the_resolved_identity(user_module, identity_store, monkeypatch):  # noqa: F811
    """AC-15: keep the existing password checker and its per-user lockout state."""
    engine, _ = identity_store
    target = old_user(engine)
    monkeypatch.setattr(AccountIdentityService, "aresolve_login", AsyncMock(return_value=target))
    monkeypatch.setattr(user_module.UserService, "decrypt_md5_password", lambda _value: "candidate-digest")
    judge = AsyncMock(side_effect=UserValidateError())
    monkeypatch.setattr(user_module.UserService, "judge_user_password", judge)
    result = await user_module.UserService.user_login(
        SimpleNamespace(), UserLogin(user_name="Legacy01", password="cipher")
    )
    assert result.status_code == 10600
    judge.assert_awaited_once_with(target, "candidate-digest")
