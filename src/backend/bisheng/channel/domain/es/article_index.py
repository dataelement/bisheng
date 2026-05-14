"""
Article ES Index Definition and Management

Defines the mappings and settings for the channel_articles index,
provides index creation/validation methods.
"""
import logging

from elasticsearch import AsyncElasticsearch, exceptions as es_exceptions, Elasticsearch

from bisheng.core.search.elasticsearch.manager import get_es_connection

logger = logging.getLogger(__name__)

# Index name
ARTICLE_INDEX_NAME = "channel_articles"

# ES Mappings definition
ARTICLE_MAPPINGS = {
    "source_type": {
        "type": "integer",
    },
    "source_id": {
        "type": "keyword",
    },
    "title": {
        "type": "text",
        "analyzer": "single_char_analyzer",
        "search_analyzer": "single_char_analyzer",
        "fields": {
            "keyword": {"type": "keyword", "ignore_above": 256}
        }
    },
    "content": {
        "type": "text",
        "analyzer": "single_char_analyzer",
        "search_analyzer": "single_char_analyzer"
    },
    "content_preview": {
        "type": "keyword",
        "ignore_above": 256,
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

# ES Settings (IK analyzer configuration, fallback to standard)
ARTICLE_SETTINGS = {
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "analysis": {
        "tokenizer": {
            "single_char_tokenizer": {
                "type": "ngram",
                "min_gram": 2,
                "max_gram": 3,
                "token_chars": [
                    "letter",
                    "digit",
                    "punctuation",
                    "symbol",
                    "whitespace"
                ],
            }
        },
        "analyzer": {
            "single_char_analyzer": {
                "type": "custom",
                "tokenizer": "single_char_tokenizer",
            }
        },
    },
}


async def ensure_article_index_exists(es_client: AsyncElasticsearch = None) -> None:
    """
    Ensure article index exists, create if it doesn't exist.

    Args:
        es_client: Optional ES client, automatically obtained if not provided
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


def ensure_article_index_exists_sync(es_client: Elasticsearch = None) -> None:
    """
    Synchronous version: Ensure article index exists, create if it doesn't exist.

    Args:
        es_client: Optional ES client, automatically obtained if not provided
    """
    if es_client is None:
        from bisheng.core.search.elasticsearch.manager import get_es_connection_sync
        es_client = get_es_connection_sync()

    try:
        exists = es_client.indices.exists(index=ARTICLE_INDEX_NAME)
        if not exists:
            es_client.indices.create(
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
