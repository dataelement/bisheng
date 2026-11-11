"""Only new browser advanced writes gain F019's expected-tenant check."""

import pytest

from bisheng.admin.application.tenant_scope import EffectiveManagementScope, require_expected_management_tenant
from bisheng.common.errcode.admin_scope import AdminScopeChangedError, AdminScopeTenantRequiredError
from bisheng.common.middleware.admin_scope import requires_expected_management_tenant


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "/api/v1/knowledge/space/7/processing-settings"),
        ("POST", "/api/v1/knowledge/space/7/processing-jobs"),
        ("POST", "/api/v1/knowledge/space/7/processing-jobs/precheck"),
        ("POST", "/api/v1/knowledge/space/7/processing-jobs/job-id/retry"),
    ],
)
def test_advanced_browser_writes_pin_the_expected_tenant(method, path):
    assert requires_expected_management_tenant(method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/knowledge/space/7/processing-settings"),
        ("GET", "/api/v1/knowledge/space/7/processing-jobs/job-id"),
        ("POST", "/api/v1/knowledge/space/7/files"),
        ("POST", "/api/v1/knowledge/space/files/move"),
        ("POST", "/api/v1/knowledge/space/files/batch-delete"),
        ("POST", "/api/v1/knowledge/space/7/files/operations/precheck"),
        ("POST", "/api/v2/knowledge/space/7/processing-jobs"),
    ],
)
def test_shared_reads_and_ordinary_writes_keep_the_existing_header_contract(method, path):
    assert not requires_expected_management_tenant(method, path)


def test_expected_tenant_is_checked_against_the_trusted_scope():
    scope = EffectiveManagementScope(tenant_id=101, source="selected", expires_at=None)
    with pytest.raises(AdminScopeTenantRequiredError):
        require_expected_management_tenant(None, scope)
    with pytest.raises(AdminScopeChangedError):
        require_expected_management_tenant("202", scope)
    require_expected_management_tenant("101", scope)
