"""Centralized import chain pre-mocking for BiSheng backend tests.

BiSheng's deep module import chains (auth.py, config_service, database models)
cause circular dependencies during test discovery. This module provides a
single function to pre-mock all known problematic modules via sys.modules.

Usage in conftest.py (module-level, before any bisheng imports):

    from test.fixtures.mock_services import premock_import_chain
    premock_import_chain()

If a new Feature introduces import chain issues, add the module path to
PREMOCK_MODULES below.

Created by F000-test-infrastructure.
"""

import sys
from unittest.mock import MagicMock

# Pre-mock celery before any bisheng module can import it (settings.py uses celery.schedules).
# Must happen before the MultiTenantConf import below, which traverses the config chain.
for _mod in ('celery', 'celery.schedules', 'celery.app', 'celery.app.task'):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from bisheng.core.config.multi_tenant import MultiTenantConf

# Union of all modules that cause circular dependency issues during test import.
# Extracted from F001 test files: test_tenant_filter.py and test_tenant_auth.py.
PREMOCK_MODULES: list[str] = [
    # config_service and telemetry — deepest offenders
    'bisheng.common.services',
    'bisheng.common.services.config_service',
    'bisheng.common.services.telemetry',
    'bisheng.common.services.telemetry.telemetry_service',
    # database models that trigger SQLModel registration side effects
    'bisheng.database.models.user_group',
    'bisheng.database.models.role_access',
    'bisheng.database.models.group',
    'bisheng.database.models.role',
    'bisheng.database.constants',
    # user domain models
    'bisheng.user.domain.models.user_role',
    'bisheng.user.domain.models.user',
    # error/exception modules
    'bisheng.common.errcode.http_error',
    'bisheng.common.exceptions.auth',
]


def premock_import_chain() -> None:
    """Inject MagicMock into sys.modules for known problematic import chains.

    Only mocks modules not already present in sys.modules. Safe to call
    multiple times (idempotent). Must be called BEFORE importing modules
    that trigger the chain (e.g., bisheng.user.domain.services.auth).

    Does NOT interfere with F001 test files that do their own pre-mocking,
    because those files mock the same modules before this function runs.
    """
    for mod_name in PREMOCK_MODULES:
        if mod_name not in sys.modules:
            mock = MagicMock()
            if mod_name == 'bisheng.common.services.config_service':
                mock.settings = _create_default_mock_settings()
            elif mod_name == 'bisheng.database.constants':
                mock.AdminRole = 1
            sys.modules[mod_name] = mock


def create_mock_settings(
    multi_tenant_enabled: bool = False,
    jwt_secret: str = 'test-secret-key',
    jwt_expire: int = 86400,
    jwt_iss: str = 'bisheng',
) -> MagicMock:
    """Create a configured MagicMock mimicking the global Settings object.

    Use this in fixtures that need to monkeypatch settings with specific values.
    """
    mock = MagicMock()
    mock.multi_tenant = MultiTenantConf(enabled=multi_tenant_enabled)
    mock.jwt_secret = jwt_secret
    mock.cookie_conf = MagicMock()
    mock.cookie_conf.jwt_token_expire_time = jwt_expire
    mock.cookie_conf.jwt_iss = jwt_iss
    return mock


def _create_default_mock_settings() -> MagicMock:
    """Internal: create default settings for the config_service pre-mock."""
    return create_mock_settings()
