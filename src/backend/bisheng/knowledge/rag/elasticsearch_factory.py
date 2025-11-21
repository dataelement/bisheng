from typing import Optional, List, Dict

from elasticsearch import Elasticsearch, AsyncElasticsearch

from bisheng.common.schemas.rag_schema import RagMetadataFieldSchema
from bisheng.common.services.config_service import settings
from bisheng.core.vectorstore import ElasticsearchStore, AsyncElasticsearchStore, BM25Strategy, AsyncBM25Strategy


def generate_metadata_mappings(metadata_schemas: Optional[List[RagMetadataFieldSchema]]):
    """
    Generate Elasticsearch metadata mappings from RagMetadataFieldSchema list.
    Args:
        metadata_schemas:

    Returns:

    """
    metadata_mappings: Optional[Dict[str, any]] = None
    for schema in metadata_schemas or []:
        if metadata_mappings is None:
            metadata_mappings = {}
        if schema.field_type == 'text':
            metadata_mappings[schema.field_name] = {'type': 'text',
                                                    'fields': {'keyword': {'type': 'keyword', 'ignore_above': 256}}}
        elif schema.field_type == 'boolean':
            metadata_mappings[schema.field_name] = {'type': 'boolean'}
        elif schema.field_type == 'int8' or schema.field_type == 'int16':
            metadata_mappings[schema.field_name] = {'type': 'short'}
        elif schema.field_type == 'int32':
            metadata_mappings[schema.field_name] = {'type': 'integer'}
        elif schema.field_type == 'int64':
            metadata_mappings[schema.field_name] = {'type': 'long'}
        elif schema.field_type == 'float':
            metadata_mappings[schema.field_name] = {'type': 'float'}
        elif schema.field_type == 'double':
            metadata_mappings[schema.field_name] = {'type': 'double'}
        elif schema.field_type == 'json':
            metadata_mappings[schema.field_name] = {'type': 'flattened'}

    return metadata_mappings


class ElasticsearchFactory:
    @staticmethod
    def init_vectorstore_sync(index_name: str, **kwargs) -> ElasticsearchStore:
        """Initialize an ElasticsearchStore vectorstore for keywords."""
        es_conf = settings.get_vectors_conf().elasticsearch

        metadata_schemas: Optional[List[RagMetadataFieldSchema]] = kwargs.pop('metadata_schemas', None)

        metadata_mappings = generate_metadata_mappings(metadata_schemas)

        es_client = ElasticsearchStore(
            index_name=index_name,
            strategy=BM25Strategy(),
            es_connection=Elasticsearch(hosts=es_conf.elasticsearch_url, **es_conf.ssl_verify),
            metadata_mappings=metadata_mappings,
            **kwargs
        )
        return es_client

    @staticmethod
    def init_vectorstore(index_name: str, **kwargs) -> AsyncElasticsearchStore:
        """Asynchronously initialize an ElasticsearchStore vectorstore for keywords."""
        es_conf = settings.get_vectors_conf().elasticsearch

        metadata_schemas: Optional[List[RagMetadataFieldSchema]] = kwargs.pop('metadata_schemas', None)

        metadata_mappings = generate_metadata_mappings(metadata_schemas)

        es_client = AsyncElasticsearchStore(
            index_name=index_name,
            strategy=AsyncBM25Strategy(),
            es_connection=AsyncElasticsearch(hosts=es_conf.elasticsearch_url, **es_conf.ssl_verify),
            metadata_mappings=metadata_mappings,
            **kwargs
        )
        return es_client
