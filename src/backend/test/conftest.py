"""Minimal pytest fixtures for F001 multi-tenant tests.

Provides SQLite in-memory database engine and settings mock.
Will be expanded in F000-test-infrastructure.

Note: Each test file that needs DB creates its own engine+session fixture
with only the tables it needs, to avoid SQLite/MySQL DDL incompatibilities
(e.g. ON UPDATE CURRENT_TIMESTAMP) and import chain issues.
"""

import pytest
from unittest.mock import MagicMock

from bisheng.core.config.multi_tenant import MultiTenantConf


@pytest.fixture()
def mock_settings(monkeypatch):
    """Mock the global settings object with controllable multi_tenant config.

    Returns a MagicMock with multi_tenant set to a real MultiTenantConf instance.
    """
    mock = MagicMock()
    mock.multi_tenant = MultiTenantConf(enabled=False)
    mock.jwt_secret = 'test-secret'
    mock.cookie_conf = MagicMock()
    mock.cookie_conf.jwt_token_expire_time = 86400
    mock.cookie_conf.jwt_iss = 'bisheng'

    monkeypatch.setattr('bisheng.common.services.config_service.settings', mock)
    return mock
