from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore

from bisheng.common.services.config_service import settings
from bisheng.core.vectorstore import Milvus

_default_index_params = {"index_type": "HNSW", "metric_type": "L2", "params": {"M": 8, "efConstruction": 64}}


class MilvusFactory:

    @staticmethod
    def init_vectorstore(collection_name: str, embedding_function: Embeddings) -> VectorStore:
        conf = settings.get_vectors_conf().milvus
        connection_args = conf.connection_args.copy()
        if connection_args.get('host') and connection_args.get('port'):
            uri = f"http://{connection_args.pop('host')}:{connection_args.pop('port')}"
            connection_args['uri'] = uri
        return Milvus(
            embedding_function=embedding_function,
            collection_name=collection_name,
            connection_args=connection_args,
            partition_key_field="knowledge_id",
            auto_id=True,
            index_params=_default_index_params
        )
