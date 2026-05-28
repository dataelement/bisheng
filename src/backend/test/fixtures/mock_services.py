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

import logging
import sys
import types
from unittest.mock import MagicMock

# Pre-import the real ``redis`` package so tests that need a live Redis
# connection (e.g. test_file_scheduler_lua.py) can obtain real StrictRedis
# instances.  The ``if _mod not in sys.modules`` guard in the mock loop below
# will then skip ``redis`` automatically, leaving it as the genuine package.
# redis.asyncio and redis.exceptions are still mocked because they are
# reached via bisheng.core.cache.redis_conn, which is itself pre-blocked.
import redis as _redis_real_module  # noqa: F401  (side-effect: registers in sys.modules)

_premock_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# knowledge_utils stub — must be installed BEFORE any module that imports
# KnowledgeSpaceService, because subscribe_handler.py imports
# KnowledgeSpaceService at module top, and KnowledgeSpaceService extends
# KnowledgeUtils.  If redis_manager is already mocked when that import
# happens, KnowledgeUtils would silently become a MagicMock auto-attribute,
# making KnowledgeSpaceService a MagicMock subclass and poisoning all tests
# that run after test_knowledge_version_endpoint.py in the same session.
#
# The placeholder is a real Python class so that `class KnowledgeSpaceService
# (KnowledgeUtils)` produces a genuine class — not a MagicMock.  The real
# KnowledgeUtils implementation is never needed in unit tests because every
# test that touches KnowledgeSpaceService patches it via monkeypatch /
# _load_service_class helpers.
# ---------------------------------------------------------------------------
_knowledge_utils_mod = types.ModuleType("bisheng.knowledge.domain.services.knowledge_utils")


class _KnowledgeUtilsPlaceholder:
    """Test-only placeholder for KnowledgeUtils.

    Provides stub implementations of every method that KnowledgeSpaceService
    (and its tests) call directly so tests do not fail with AttributeError even
    when _install_schema_stubs() skips re-installing the module because it is
    already present in sys.modules.
    """

    @classmethod
    async def update_folder_update_time(cls, *args, **kwargs):
        return None

    @staticmethod
    def update_folder_update_time_sync(*args, **kwargs):
        return None

    @classmethod
    def get_preview_cache_key(cls, *args, **kwargs):
        return "preview-cache-key"

    @classmethod
    async def process_retry_files(cls, *args, **kwargs):
        return ([], set())

    @classmethod
    async def process_rebuild_file(cls, *args, **kwargs):
        return None

    @classmethod
    def ensure_milvus_schema_ready(cls, *args, **kwargs):
        return None

    @classmethod
    def get_knowledge_file_object_name(cls, *args, **kwargs):
        return ""

    @classmethod
    def resolve_source_object_name(cls, *args, **kwargs):
        return None

    @classmethod
    def resolve_preview_object_name(cls, *args, **kwargs):
        return None

    @classmethod
    def get_knowledge_abstract_llm(cls, *args, **kwargs):
        return None, None

    chunk_split = "\n----------\n"
    schema_ready_lock_ttl = 60
    schema_ready_wait_seconds = 20
    schema_ready_poll_interval = 0.5


_knowledge_utils_mod.KnowledgeUtils = _KnowledgeUtilsPlaceholder
sys.modules["bisheng.knowledge.domain.services.knowledge_utils"] = _knowledge_utils_mod

# Pre-mock celery before any bisheng module can import it (settings.py uses celery.schedules).
# Must happen before the MultiTenantConf import below, which traverses the config chain.
# F011 adds: docstring_parser (pulled in by bisheng.utils.util when tenant_service imports),
# fakeredis (some fixtures), and a defensive list of optional dependencies.
for _mod in (
    "celery",
    "celery.schedules",
    "celery.app",
    "celery.app.task",
    "celery.signals",
    "docstring_parser",
    "redis",
    "redis.asyncio",
    "redis.exceptions",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from bisheng.core.config.multi_tenant import MultiTenantConf  # noqa: E402

# Union of all modules that cause circular dependency issues during test import.
# Extracted from F001 test files: test_tenant_filter.py and test_tenant_auth.py.
PREMOCK_MODULES: list[str] = [
    # config_service and telemetry — deepest offenders
    "bisheng.common.services",
    "bisheng.common.services.base",
    "bisheng.common.services.config_service",
    "bisheng.common.services.telemetry",
    "bisheng.common.services.telemetry.telemetry_service",
    # database models that trigger SQLModel registration side effects
    "bisheng.database.models.user_group",
    "bisheng.database.models.role_access",
    "bisheng.database.models.group",
    "bisheng.database.models.role",
    "bisheng.database.constants",
    # user domain models
    "bisheng.user.domain.models.user_role",
    "bisheng.user.domain.models.user",
    # error/exception modules
    "bisheng.common.errcode.http_error",
    "bisheng.common.exceptions.auth",
    # F011: tenant_service pulls in redis_manager/openfga on import
    "bisheng.core.cache.redis_conn",
    "bisheng.core.cache.redis_manager",
    # worker/celery modules — run celery setup at import time, break in test env
    "bisheng.worker",
    "bisheng.worker.main",
    "bisheng.worker.knowledge",
    "bisheng.worker.knowledge.file_worker",
    "bisheng.worker.approval",
    "bisheng.worker.approval.tasks",
]

# Modules that must be imported for real (not mocked) even though their parent
# package appears in PREMOCK_MODULES.  Each entry is imported and registered in
# sys.modules BEFORE the parent package mock is installed, so subsequent
# `from bisheng.worker.knowledge.scheduler import …` in test files resolves to
# the real module rather than a MagicMock attribute.
_REAL_SUBMODULES: list[str] = [
    "bisheng.worker.knowledge.scheduler",
]


def premock_import_chain() -> None:
    """Inject MagicMock into sys.modules for known problematic import chains.

    Only mocks modules not already present in sys.modules. Safe to call
    multiple times (idempotent). Must be called BEFORE importing modules
    that trigger the chain (e.g., bisheng.user.domain.services.auth).

    Does NOT interfere with F001 test files that do their own pre-mocking,
    because those files mock the same modules before this function runs.
    """
    # Step 1: install redis/cache mocks first so that real submodules that
    # depend on redis_manager can be imported without errors.
    _redis_deps = (
        "bisheng.core.cache.redis_conn",
        "bisheng.core.cache.redis_manager",
    )
    for mod_name in _redis_deps:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = MagicMock()

    # Step 2: pre-load real submodules before their parent package is mocked.
    import importlib

    for real_mod in _REAL_SUBMODULES:
        if real_mod not in sys.modules:
            try:
                importlib.import_module(real_mod)
            except ImportError as exc:  # pragma: no cover — defensive
                _premock_log.warning(
                    "premock_import_chain: failed to pre-load %s: %s; tests that depend on it will fail",
                    real_mod,
                    exc,
                )

    # Step 3: mock the remaining problematic modules (skipping already-present ones).
    for mod_name in PREMOCK_MODULES:
        if mod_name not in sys.modules:
            mock = MagicMock()
            if mod_name == "bisheng.common.services.config_service":
                mock.settings = _create_default_mock_settings()
            elif mod_name == "bisheng.database.constants":
                mock.AdminRole = 1
            sys.modules[mod_name] = mock


def create_mock_settings(
    multi_tenant_enabled: bool = False,
    jwt_secret: str = "test-secret-key",
    jwt_expire: int = 86400,
    jwt_iss: str = "bisheng",
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
