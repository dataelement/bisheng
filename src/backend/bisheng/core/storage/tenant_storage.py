"""Tenant-aware storage prefix functions.

Each function returns an empty string for the default tenant (id=1),
preserving backward compatibility with existing storage paths (INV-9).
New tenants get distinct prefixes to achieve storage isolation.

These functions define the prefix convention only. Actual storage call sites
are modified in F008-resource-rebac-adaptation, not here.
"""

from bisheng.core.context.tenant import DEFAULT_TENANT_ID


def get_minio_prefix(tenant_id: int, tenant_code: str) -> str:
    """Return MinIO object key prefix for the given tenant.

    Default tenant (id=1): "" (original paths unchanged)
    New tenant: "tenant_{code}/"
    """
    if tenant_id == DEFAULT_TENANT_ID:
        return ''
    return f'tenant_{tenant_code}/'


def get_milvus_collection_prefix(tenant_id: int) -> str:
    """Return Milvus collection name prefix for the given tenant.

    Default tenant (id=1): "" (original collection names unchanged)
    New tenant: "t{id}_"
    """
    if tenant_id == DEFAULT_TENANT_ID:
        return ''
    return f't{tenant_id}_'


def get_es_index_prefix(tenant_id: int) -> str:
    """Return Elasticsearch index name prefix for the given tenant.

    Default tenant (id=1): "" (original index names unchanged)
    New tenant: "t{id}_"
    """
    if tenant_id == DEFAULT_TENANT_ID:
        return ''
    return f't{tenant_id}_'


def get_redis_key_prefix(tenant_id: int) -> str:
    """Return Redis key prefix for the given tenant.

    Default tenant (id=1): "" (original keys unchanged)
    New tenant: "t:{id}:"
    """
    if tenant_id == DEFAULT_TENANT_ID:
        return ''
    return f't:{tenant_id}:'
