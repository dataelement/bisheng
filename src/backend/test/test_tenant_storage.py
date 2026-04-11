"""Tests for tenant storage prefix functions.

Covers AC-10: default tenant returns empty string, new tenants get prefixes.
"""

from bisheng.core.storage.tenant_storage import (
    get_es_index_prefix,
    get_milvus_collection_prefix,
    get_minio_prefix,
    get_redis_key_prefix,
)


class TestMinioPrefix:
    def test_default_tenant(self):
        assert get_minio_prefix(1, 'default') == ''

    def test_new_tenant(self):
        assert get_minio_prefix(2, 'cofco') == 'tenant_cofco/'

    def test_another_tenant(self):
        assert get_minio_prefix(10, 'shougang') == 'tenant_shougang/'


class TestMilvusPrefix:
    def test_default_tenant(self):
        assert get_milvus_collection_prefix(1) == ''

    def test_new_tenant(self):
        assert get_milvus_collection_prefix(2) == 't2_'

    def test_large_id(self):
        assert get_milvus_collection_prefix(999) == 't999_'


class TestEsPrefix:
    def test_default_tenant(self):
        assert get_es_index_prefix(1) == ''

    def test_new_tenant(self):
        assert get_es_index_prefix(3) == 't3_'


class TestRedisPrefix:
    def test_default_tenant(self):
        assert get_redis_key_prefix(1) == ''

    def test_new_tenant(self):
        assert get_redis_key_prefix(2) == 't:2:'

    def test_another_tenant(self):
        assert get_redis_key_prefix(50) == 't:50:'
