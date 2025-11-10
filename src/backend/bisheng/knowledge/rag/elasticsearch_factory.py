from elasticsearch import Elasticsearch

from bisheng.common.services.config_service import settings
from bisheng.core.vectorstore import ElasticsearchStore, BM25Strategy


class ElasticsearchFactory:
    @staticmethod
    def init_vectorstore(index_name: str):
        """Initialize an ElasticsearchStore vectorstore for keywords."""
        es_conf = settings.get_vectors_conf().elasticsearch

        es_client = ElasticsearchStore(
            index_name=index_name,
            strategy=BM25Strategy(),
            es_connection=Elasticsearch(hosts=es_conf.elasticsearch_url, **es_conf.ssl_verify),
        )
        return es_client
