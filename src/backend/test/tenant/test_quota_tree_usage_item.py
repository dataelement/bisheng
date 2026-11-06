"""Quota tree usage entries carry fractional storage usage."""

from bisheng.tenant.domain.schemas.tenant_schema import TenantQuotaUsageItem


def test_storage_usage_in_gb_is_kept_fractional():
    item = TenantQuotaUsageItem(resource_type="storage_gb", used=0.081, limit=10, utilization=0.0081)

    assert item.used == 0.081
    assert item.model_dump()["limit"] == 10


def test_count_types_stay_integers():
    dumped = TenantQuotaUsageItem(resource_type="knowledge_space", used=3, limit=-1, utilization=0.0).model_dump()

    assert dumped["used"] == 3 and isinstance(dumped["used"], int)
    assert isinstance(dumped["limit"], int)
