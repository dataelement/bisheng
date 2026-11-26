"""Real RSA registration through HTTP and native identity persistence."""

import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import rsa
from fastapi import FastAPI
from sqlmodel import Session, select

from bisheng.common.errcode.user import CaptchaError, UserPasswordStrengthError
from bisheng.user.domain.models.user import User, UserCreate
from test.user.f011_fixtures import identity_store as identity_store
from test.user.test_account_login_rules import user_module as user_module


@pytest.fixture(scope="module")
def keypair():
    return rsa.newkeys(2048)


@pytest.fixture
def registration(user_module, identity_store, monkeypatch, keypair):
    from bisheng.user.api import user as endpoints

    cache = Mock()
    cache.get.return_value = keypair
    monkeypatch.setattr(endpoints, "get_redis_client_sync", lambda: cache)
    monkeypatch.setattr(user_module, "get_redis_client_sync", lambda: cache)
    service = user_module.UserService
    tenant = AsyncMock(return_value=1)
    monkeypatch.setattr(service, "_resolve_registration_tenant_id", tenant)
    # External tenant/department/permission projections have separate suites.
    # Keep actual RSA, strength rules, model validation and SQL identity writes.
    for helper in (
        "_ensure_user_default_tenant_association",
        "_ensure_user_guest_department_membership",
        "areconcile_first_user_dashboard_permissions",
    ):
        monkeypatch.setattr(service, helper, AsyncMock())
    sync = AsyncMock()
    monkeypatch.setattr(user_module.LegacyRBACSyncService, "sync_user_auth_created", sync)
    app = FastAPI()
    app.include_router(endpoints.router, prefix="/api/v1")
    return SimpleNamespace(app=app, module=user_module, engine=identity_store[0], cache=cache, tenant=tenant, sync=sync)


def encrypt(plain, public):
    cipher = base64.b64encode(rsa.encrypt(plain.encode(), public)).decode()
    assert len(cipher) == 344  # exceeds User's stored-hash field limit (255)
    return cipher


def stored_users(registration):
    with Session(registration.engine) as session:
        return session.exec(select(User)).all()


@pytest.mark.parametrize("plain", ["Regression#Pass123", "测试Aa7!密码", "Aa1!" + "a" * 124])
async def test_register_accepts_real_rsa_cipher_and_persists_only_hash(registration, plain):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=registration.app), base_url="http://test") as client:
        response = await client.get("/api/v1/user/public_key")
        public = rsa.PublicKey.load_pkcs1(response.json()["data"]["public_key"].encode())
        assert public.n.bit_length() == 2048
        cipher = encrypt(plain, public)
        response = await client.post(
            "/api/v1/user/regist",
            json={
                "user_name": "RSA注册用户",
                "external_id": "RsaRegistration01",
                "password": cipher,
                "source": "wecom",
                "delete": 1,
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status_code"] == 200
    assert "password" not in body["data"]
    (row,) = stored_users(registration)
    assert row.password == hashlib.md5(plain.encode()).hexdigest()
    assert len(row.password) == 32
    assert row.source == "local" and row.delete == 0
    assert row.external_id == "RsaRegistration01"
    assert row.user_name == "RSA注册用户"
    registration.sync.assert_awaited_once()
    assert User.__table__.c.password.type.length == 255


@pytest.mark.parametrize("plain", ["weakpass", "Aa1!" + "a" * 125])
async def test_encrypted_invalid_password_is_rejected_before_any_creation(registration, keypair, plain):
    request = UserCreate(user_name="Weak", external_id="Weak01", password=encrypt(plain, keypair[0]))
    with pytest.raises(UserPasswordStrengthError):
        await registration.module.UserService.user_register(request)
    assert stored_users(registration) == []
    registration.tenant.assert_not_awaited()
    registration.sync.assert_not_awaited()


async def test_registration_captcha_still_precedes_decryption(registration, keypair, monkeypatch):
    registration.module.settings.get_from_db.return_value = True
    captcha = AsyncMock(return_value=False)
    monkeypatch.setattr(registration.module, "verify_captcha", captcha)
    decrypt = Mock(wraps=registration.module.UserService.decrypt_md5_password_strict)
    monkeypatch.setattr(registration.module.UserService, "decrypt_md5_password_strict", decrypt)
    request = UserCreate(
        user_name="Captcha",
        external_id="Captcha01",
        password=encrypt("Strong#Pass123", keypair[0]),
        captcha_key="test-key",
        captcha="wrong",
    )
    with pytest.raises(CaptchaError):
        await registration.module.UserService.user_register(request)
    captcha.assert_awaited_once_with("wrong", "test-key")
    decrypt.assert_not_called()
    assert stored_users(registration) == []
    registration.tenant.assert_not_awaited()


async def test_plaintext_development_mode_still_hashes_before_persisting(registration):
    registration.cache.get.return_value = None
    plain = "Development#Pass123"
    await registration.module.UserService.user_register(
        UserCreate(user_name="Dev", external_id="Dev01", password=plain)
    )
    (row,) = stored_users(registration)
    assert row.password == hashlib.md5(plain.encode()).hexdigest()
