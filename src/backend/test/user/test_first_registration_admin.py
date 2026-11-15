"""Startup never creates identities; first registration keeps the ordinary admin path."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common import init_data
from bisheng.common.services.config_service import ConfigService
from bisheng.core.config.settings import Settings
from bisheng.database.constants import AdminRole, DefaultRole
from bisheng.user.domain.models.user import User, UserCreate
from bisheng.user.domain.services import user as users
from bisheng.user.domain.services.account_identity_service import AccountIdentityService


def test_retired_admin_and_unknown_yaml_keys_warn_without_blocking_startup(tmp_path, monkeypatch):
    from bisheng.common.services import config_service

    log = MagicMock()
    monkeypatch.setattr(config_service, "logger", log)
    source = tmp_path / "legacy.yaml"
    source.write_text("admin:\n  user_name: legacy\n  password: must-not-log-this\n")
    loaded = ConfigService.load_settings_from_yaml(str(source))
    assert "admin" not in Settings.model_fields
    assert not hasattr(loaded, "admin")
    assert "must-not-log-this" not in str(log.mock_calls)
    log.warning.assert_called_once()
    log.reset_mock()
    source.write_text("unknown_deployment_setting: true\n")
    loaded = ConfigService.load_settings_from_yaml(str(source))
    assert "unknown_deployment_setting" not in loaded.model_dump()
    log.warning.assert_called_once()
    assert "unknown_deployment_setting" in str(log.warning.call_args)


async def test_startup_never_creates_a_user_even_if_legacy_configuration_is_present(monkeypatch):
    session = MagicMock()

    async def execute(statement):
        model = statement.column_descriptions[0]["entity"]
        return SimpleNamespace(all=lambda: [] if model is User else [object()])

    session.exec = AsyncMock(side_effect=execute)
    session.commit = AsyncMock()

    @asynccontextmanager
    async def session_factory():
        yield session

    monkeypatch.setattr(init_data, "get_async_db_session", session_factory)
    monkeypatch.setattr(
        init_data, "get_database_connection", AsyncMock(return_value=SimpleNamespace(create_db_and_tables=AsyncMock()))
    )
    monkeypatch.setattr(
        init_data,
        "get_redis_client",
        AsyncMock(return_value=SimpleNamespace(asetNx=AsyncMock(return_value=True), adelete=AsyncMock())),
    )
    monkeypatch.setattr(
        init_data,
        "settings",
        SimpleNamespace(
            admin={"user_name": "legacy", "password": "unused"},
            init_config=AsyncMock(),
            openfga=SimpleNamespace(enabled=False),
        ),
    )
    for helper in (
        "_init_default_tenant",
        "_init_default_root_department",
        "_backfill_guest_department_membership",
        "_init_default_approval_scenarios",
        "_init_resource_tiers",
        "_retire_image_view_tool",
        "_ensure_web_fetch_tool",
        "_sync_web_fetch_tool",
        "init_dashboard_datasets",
    ):
        monkeypatch.setattr(init_data, helper, AsyncMock())
    await init_data.init_default_data()
    session.add.assert_not_called()
    session.add_all.assert_not_called()


@pytest.mark.parametrize("admin_exists", [False, True])
async def test_registration_preserves_first_admin_and_subsequent_default_role(monkeypatch, admin_exists):
    monkeypatch.setattr(
        users, "settings", SimpleNamespace(get_from_db=lambda _: False, multi_tenant=SimpleNamespace(enabled=False))
    )

    async def persist(row, *, bootstrap):
        assert bootstrap is True
        row.user_id = 2 if admin_exists else 1
        return row

    create = AsyncMock(side_effect=persist)
    monkeypatch.setattr(AccountIdentityService, "acreate_local", create)
    sync = AsyncMock()
    monkeypatch.setattr(users.LegacyRBACSyncService, "sync_user_auth_created", sync)
    monkeypatch.setattr(users.UserService, "decrypt_md5_password_strict", lambda _: "encrypted-password-hash")
    monkeypatch.setattr(users.UserService, "_resolve_registration_tenant_id", AsyncMock(return_value=1))
    for helper in (
        "_ensure_user_default_tenant_association",
        "_ensure_user_guest_department_membership",
        "areconcile_first_user_dashboard_permissions",
    ):
        monkeypatch.setattr(users.UserService, helper, AsyncMock())
    row = await users.UserService.user_register(
        UserCreate(user_name="registered", external_id="person-id", password="ciphertext")
    )
    assert row.external_id == "person-id"
    sync.assert_awaited_once_with(row.user_id, [DefaultRole if admin_exists else AdminRole])
    create.assert_awaited_once()
