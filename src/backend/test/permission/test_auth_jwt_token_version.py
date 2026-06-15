"""Tests for F012 JWT payload + LoginUser ``token_version`` carrying.

Narrowly scoped: verify the JWT payload embeds ``token_version`` and that
``LoginUser`` round-trips the value without losing type. The deep login
flow (``user/domain/services/user.py``) is exercised in T12 integration
tests; we don't need to run the full login chain here to validate the
payload shape.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import jwt
import pytest


@pytest.fixture()
def auth_jwt_instance(monkeypatch):
    """Build a self-contained AuthJwt with deterministic secret/iss/expiry.

    ``auth.py`` imports ``settings`` by name at module load, so patching
    ``config_service.settings`` alone is not enough — we patch the auth
    module's own binding too.
    """
    from bisheng.common.services import config_service as cs
    from bisheng.user.domain.services import auth as auth_mod

    mock_cookie = MagicMock()
    mock_cookie.jwt_token_expire_time = 3600
    mock_cookie.jwt_iss = 'bisheng-test'
    mock_settings = SimpleNamespace(
        jwt_secret='unit-test-secret',
        cookie_conf=mock_cookie,
    )
    monkeypatch.setattr(cs, 'settings', mock_settings)
    monkeypatch.setattr(auth_mod, 'settings', mock_settings)

    return auth_mod.AuthJwt()


class TestJWTPayload:

    def test_token_version_embedded_in_subject(self, auth_jwt_instance):
        """Payload JSON contains ``token_version``."""
        payload = {
            'user_id': 100, 'user_name': 'alice',
            'tenant_id': 5, 'token_version': 3,
        }
        token = auth_jwt_instance.create_access_token(subject=payload)
        decoded = jwt.decode(
            token, 'unit-test-secret',
            issuer='bisheng-test', algorithms=['HS256'],
        )
        subject = json.loads(decoded['sub'])
        assert subject['token_version'] == 3
        assert subject['tenant_id'] == 5

    def test_decode_jwt_token_preserves_fields(self, auth_jwt_instance):
        payload = {
            'user_id': 101, 'user_name': 'bob',
            'tenant_id': 7, 'token_version': 9,
        }
        token = auth_jwt_instance.create_access_token(subject=payload)
        subject = auth_jwt_instance.decode_jwt_token(token)
        assert subject['token_version'] == 9


class TestLoginUserField:
    """``LoginUser.token_version`` round-trip without hitting DB."""

    def test_defaults_zero_when_absent(self, monkeypatch):
        # Stub UserRoleDao so __init__ does not touch the DB.
        from bisheng.user.domain.services import auth as auth_mod
        monkeypatch.setattr(
            auth_mod.UserRoleDao,
            'get_user_roles',
            lambda user_id: [],
        )
        user = auth_mod.LoginUser(user_id=200, user_name='cara', user_role=[1])
        assert user.token_version == 0

    def test_reads_explicit_value(self, monkeypatch):
        from bisheng.user.domain.services import auth as auth_mod
        monkeypatch.setattr(
            auth_mod.UserRoleDao,
            'get_user_roles',
            lambda user_id: [],
        )
        user = auth_mod.LoginUser(
            user_id=201, user_name='dan',
            user_role=[1], token_version=42,
        )
        assert user.token_version == 42


class TestCreateAccessTokenClassmethod:
    """Verify the classmethod helper injects token_version correctly."""

    def test_reads_token_version_from_user(self, auth_jwt_instance, monkeypatch):
        from bisheng.user.domain.services import auth as auth_mod
        monkeypatch.setattr(
            auth_mod.UserRoleDao, 'get_user_roles', lambda uid: [],
        )
        fake_user = SimpleNamespace(
            user_id=300, user_name='eve', token_version=7,
        )
        token = auth_mod.LoginUser.create_access_token(
            user=fake_user, auth_jwt=auth_jwt_instance, tenant_id=5,
        )
        subject = json.loads(jwt.decode(
            token, 'unit-test-secret',
            issuer='bisheng-test', algorithms=['HS256'],
        )['sub'])
        assert subject['token_version'] == 7
        assert subject['tenant_id'] == 5

    def test_default_zero_when_user_missing_field(
        self, auth_jwt_instance, monkeypatch,
    ):
        """v2.5.0 User objects without ``token_version`` → payload carries 0."""
        from bisheng.user.domain.services import auth as auth_mod
        monkeypatch.setattr(
            auth_mod.UserRoleDao, 'get_user_roles', lambda uid: [],
        )
        fake_user = SimpleNamespace(user_id=301, user_name='frank')
        token = auth_mod.LoginUser.create_access_token(
            user=fake_user, auth_jwt=auth_jwt_instance,
        )
        subject = json.loads(jwt.decode(
            token, 'unit-test-secret',
            issuer='bisheng-test', algorithms=['HS256'],
        )['sub'])
        assert subject['token_version'] == 0

    def test_explicit_token_version_overrides_user_attr(
        self, auth_jwt_instance, monkeypatch,
    ):
        from bisheng.user.domain.services import auth as auth_mod
        monkeypatch.setattr(
            auth_mod.UserRoleDao, 'get_user_roles', lambda uid: [],
        )
        fake_user = SimpleNamespace(
            user_id=302, user_name='grace', token_version=3,
        )
        token = auth_mod.LoginUser.create_access_token(
            user=fake_user, auth_jwt=auth_jwt_instance,
            token_version=99,
        )
        subject = json.loads(jwt.decode(
            token, 'unit-test-secret',
            issuer='bisheng-test', algorithms=['HS256'],
        )['sub'])
        assert subject['token_version'] == 99
