"""F118 opt-in fixtures; isolated tests never connect to deployment services."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture
def f118_tenant_ids():
    return (101, 202)


@pytest.fixture
def f118_identity_cases(f118_tenant_ids):
    """Test inputs only: services still construct and authorize real actors."""
    first, second = f118_tenant_ids
    return {
        "super_admin": SimpleNamespace(user_id=11, tenant_id=first, role="super_admin"),
        "tenant_admin": SimpleNamespace(user_id=12, tenant_id=first, role="tenant_admin"),
        "owner": SimpleNamespace(user_id=13, tenant_id=first, role="resource_owner"),
        "ordinary": SimpleNamespace(user_id=14, tenant_id=first, role="ordinary"),
        "file_viewer": SimpleNamespace(user_id=15, tenant_id=first, role="file_viewer"),
        "other_tenant": SimpleNamespace(user_id=21, tenant_id=second, role="tenant_admin"),
    }


@pytest.fixture
def f118_engine():
    """Each caller creates only the tables that its transactional scenario uses."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def reference_store_failure():
    """Inject at the reference Repository boundary to assert whole-unit rollback."""
    return RuntimeError("injected reference store failure")
