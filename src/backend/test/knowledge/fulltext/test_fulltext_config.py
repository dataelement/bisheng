import pytest

from bisheng.core.config.settings import KnowledgeConf
from bisheng.knowledge.domain import knowledge_fulltext_constants as constants


def test_fulltext_parameters_are_module_constants_not_knowledge_settings():
    conf = KnowledgeConf()

    assert "fulltext_index" not in KnowledgeConf.model_fields
    assert not hasattr(conf, "fulltext_index")
    assert not hasattr(constants, "KNOWLEDGE_FULLTEXT_ENABLED")
    assert constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS == "knowledge_fulltext"
    assert constants.physical_index_name() == "knowledge_fulltext_v1"
    assert constants.KNOWLEDGE_FULLTEXT_NGRAM_MIN == 1
    assert constants.KNOWLEDGE_FULLTEXT_NGRAM_MAX == 20


def test_fulltext_module_constant_ranges_are_internally_valid():
    assert 1 <= constants.KNOWLEDGE_FULLTEXT_NGRAM_MIN <= constants.KNOWLEDGE_FULLTEXT_NGRAM_MAX
    assert constants.KNOWLEDGE_FULLTEXT_RETRY_BASE_SECONDS <= constants.KNOWLEDGE_FULLTEXT_RETRY_MAX_SECONDS
    assert constants.KNOWLEDGE_FULLTEXT_CHUNK_PAGE_SIZE > 0
    assert constants.KNOWLEDGE_FULLTEXT_DISPATCH_BATCH_SIZE > 0
    assert constants.KNOWLEDGE_FULLTEXT_LEASE_TTL_SECONDS > 0
    assert constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_DELAY_SECONDS == 300
    assert 1 <= constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_BATCH_SIZE <= 1000
    assert constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_LEASE_SECONDS > constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_DELAY_SECONDS
    assert constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_RECONCILE_DAYS >= 2


def test_fulltext_module_constants_fail_closed_for_multi_tenant():
    with pytest.raises(ValueError, match="multi-tenant"):
        constants.ensure_runtime_compatible(multi_tenant_enabled=True)
