"""
文章 ES 索引定义与管理

定义 channel_articles 索引的 mappings 和 settings，
提供索引创建/确认方法。
"""
import logging

from elasticsearch import AsyncElasticsearch, exceptions as es_exceptions

from bisheng.core.search.elasticsearch.manager import get_es_connection

logger = logging.getLogger(__name__)

# 索引名称
ARTICLE_INDEX_NAME = "channel_articles"

# ES Mappings 定义
ARTICLE_MAPPINGS = {
    "source_type": {
        "type": "integer",
    },
    "source_id": {
        "type": "keyword",
    },
    "title": {
        "type": "text",
        "analyzer": "ik_max_word",
        "search_analyzer": "ik_smart",
        "fields": {
            "keyword": {"type": "keyword", "ignore_above": 256}
        }
    },
    "content": {
        "type": "text",
        "analyzer": "ik_max_word",
        "search_analyzer": "ik_smart",
    },
    "content_html": {
        "type": "text",
        "index": False,
    },
    "cover_image": {
        "type": "keyword",
        "index": False,
    },
    "publish_time": {
        "type": "date",
        "format": "strict_date_optional_time||epoch_millis",
    },
    "source_url": {
        "type": "keyword",
    },
    "create_time": {
        "type": "date",
        "format": "strict_date_optional_time||epoch_millis",
    },
    "update_time": {
        "type": "date",
        "format": "strict_date_optional_time||epoch_millis",
    },
}

# ES Settings（IK 分词器配置，fallback 到 standard）
ARTICLE_SETTINGS = {
    "number_of_shards": 1,
    "number_of_replicas": 0,
}


async def ensure_article_index_exists(es_client: AsyncElasticsearch = None) -> None:
    """
    确保文章索引存在，若不存在则创建。

    Args:
        es_client: 可选的 ES 客户端，若不传则自动获取
    """
    if es_client is None:
        es_client = await get_es_connection()

    try:
        exists = await es_client.indices.exists(index=ARTICLE_INDEX_NAME)
        if not exists:
            await es_client.indices.create(
                index=ARTICLE_INDEX_NAME,
                body={
                    "settings": ARTICLE_SETTINGS,
                    "mappings": {"properties": ARTICLE_MAPPINGS},
                }
            )
            logger.info(f"Successfully created ES index: {ARTICLE_INDEX_NAME}")
        else:
            logger.debug(f"ES index already exists: {ARTICLE_INDEX_NAME}")
    except es_exceptions.RequestError as e:
        if "resource_already_exists_exception" not in str(e):
            logger.error(f"Failed to create ES index '{ARTICLE_INDEX_NAME}': {e}")
            raise
        logger.debug(f"ES index '{ARTICLE_INDEX_NAME}' already exists (concurrent creation)")
