"""Tests for JWT tenant_id extension and LoginUser tenant awareness.

Covers AC-07 (JWT encode/decode with tenant_id, old token fallback)
and AC-08 (LoginUser.tenant_id field).

Note: LoginUser import triggers a deep import chain that may fail in some
environments due to SQLModel version mismatches. We mock the problematic
modules to isolate JWT/tenant_id logic.
"""

import json
import sys
from unittest.mock import MagicMock, patch

# Pre-mock modules in the import chain that cause version issues
import jwt as pyjwt

from bisheng.core.context.tenant import DEFAULT_TENANT_ID

# Pre-mock modules that trigger ondelete/config_service import chain issues.
# This allows importing auth.py in isolation for JWT testing.
_MOCKS_NEEDED = [
    'bisheng.common.services',
    'bisheng.common.services.config_service',
    'bisheng.common.services.telemetry',
    'bisheng.common.services.telemetry.telemetry_service',
    'bisheng.database.models.user_group',
    'bisheng.database.models.role_access',
    'bisheng.database.models.group',
    'bisheng.user.domain.models.user_role',
    'bisheng.user.domain.models.user',
    'bisheng.database.models.role',
    'bisheng.database.constants',
    'bisheng.common.errcode.http_error',
    'bisheng.common.exceptions.auth',
]
for _mod_name in _MOCKS_NEEDED:
    if _mod_name not in sys.modules:
        _mock = MagicMock()
        if _mod_name == 'bisheng.common.services.config_service':
            _mock.settings = MagicMock()
            _mock.settings.jwt_secret = 'test-secret-key'
            _mock.settings.cookie_conf = MagicMock()
            _mock.settings.cookie_conf.jwt_token_expire_time = 86400
            _mock.settings.cookie_conf.jwt_iss = 'bisheng'
        elif _mod_name == 'bisheng.database.constants':
            _mock.AdminRole = 1
        sys.modules[_mod_name] = _mock

from bisheng.user.domain.services.auth import AuthJwt, LoginUser


def _make_auth_jwt():
    """Create an AuthJwt instance with test configuration.

    Works because the pre-mock above sets config_service.settings
    with matching jwt_secret and cookie_conf values.
    """
    return AuthJwt()


class TestJwtTenantId:
    """AC-07: JWT payload should include tenant_id."""

    def test_jwt_encode_with_tenant_id(self):
        """New JWT should contain tenant_id in the subject."""
        auth = _make_auth_jwt()
        subject = {'user_id': 1, 'user_name': 'admin', 'tenant_id': 2}
        token = auth.create_access_token(subject=subject)

        decoded = auth.decode_jwt_token(token)
        assert decoded['tenant_id'] == 2
        assert decoded['user_id'] == 1

    def test_jwt_decode_old_token_fallback(self):
        """Old JWT without tenant_id should fallback to DEFAULT_TENANT_ID."""
        auth = _make_auth_jwt()

        # Create a token without tenant_id (simulating pre-v2.5 token)
        old_subject = {'user_id': 1, 'user_name': 'admin'}
        token = auth.create_access_token(subject=old_subject)

        decoded = auth.decode_jwt_token(token)
        # tenant_id not in payload — caller uses .get('tenant_id', DEFAULT)
        assert decoded.get('tenant_id', DEFAULT_TENANT_ID) == DEFAULT_TENANT_ID


class TestLoginUserTenantId:
    """AC-08: LoginUser should expose tenant_id field."""

    @patch('bisheng.user.domain.services.auth.UserRoleDao')
    def test_login_user_has_tenant_id(self, mock_dao):
        """LoginUser constructed with tenant_id should expose it."""
        mock_dao.get_user_roles.return_value = []

        user = LoginUser(user_id=1, user_name='test', tenant_id=3)
        assert user.tenant_id == 3

    @patch('bisheng.user.domain.services.auth.UserRoleDao')
    def test_login_user_default_tenant_id(self, mock_dao):
        """LoginUser without explicit tenant_id defaults to DEFAULT_TENANT_ID."""
        mock_dao.get_user_roles.return_value = []

        user = LoginUser(user_id=1, user_name='test')
        assert user.tenant_id == DEFAULT_TENANT_ID

    @patch('bisheng.user.domain.services.auth.UserRoleDao')
    def test_login_user_create_access_token_with_tenant(self, mock_dao):
        """create_access_token should include tenant_id in the JWT payload."""
        mock_dao.get_user_roles.return_value = []

        auth = _make_auth_jwt()
        mock_user = MagicMock()
        mock_user.user_id = 10
        mock_user.user_name = 'tenant_user'

        token = LoginUser.create_access_token(mock_user, auth, tenant_id=5)
        decoded = auth.decode_jwt_token(token)
        assert decoded['tenant_id'] == 5
        assert decoded['user_id'] == 10
