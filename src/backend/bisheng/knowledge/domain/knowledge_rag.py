from typing import Dict

from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from langchain_elasticsearch import AsyncElasticsearchStore, ElasticsearchStore
from langchain_milvus import Milvus

from bisheng.common.errcode.http_error import NotFoundError
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao
from bisheng.knowledge.rag.elasticsearch_factory import ElasticsearchFactory
from bisheng.knowledge.rag.milvus_factory import MilvusFactory
from bisheng.llm.domain import LLMService


class KnowledgeRag:
    """ initialize knowledge rag components """

    @classmethod
    async def _get_knowledge(cls, knowledge: Knowledge = None, knowledge_id: int = None) -> Knowledge:
        if not knowledge:
            knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
            if not knowledge:
                raise NotFoundError.http_exception()
        return knowledge

    @classmethod
    def _get_knowledge_sync(cls, knowledge: Knowledge = None, knowledge_id: int = None):
        if not knowledge:
            knowledge = KnowledgeDao.query_by_id(knowledge_id)
            if not knowledge:
                raise NotFoundError.http_exception()
        return knowledge

    @classmethod
    async def init_knowledge_milvus_vectorstore(cls, knowledge: Knowledge = None,
                                                knowledge_id: int = None, **kwargs) -> Milvus:
        knowledge = await cls._get_knowledge(knowledge, knowledge_id)
        embedding = await LLMService.get_bisheng_embedding(model_id=knowledge.model)
        return cls.init_milvus_vectorstore(knowledge.collection_name, embedding, **kwargs)

    @classmethod
    def init_knowledge_milvus_vectorstore_sync(cls, knowledge: Knowledge = None,
                                               knowledge_id: int = None, **kwargs) -> Milvus:
        knowledge = cls._get_knowledge_sync(knowledge, knowledge_id)
        embedding = LLMService.get_bisheng_embedding_sync(model_id=knowledge.model)
        return cls.init_milvus_vectorstore(knowledge.collection_name, embedding, **kwargs)

    @classmethod
    async def init_knowledge_es_vectorstore(cls, knowledge: Knowledge = None, knowledge_id: int = None,
                                            **kwargs) -> AsyncElasticsearchStore:
        knowledge = await cls._get_knowledge(knowledge, knowledge_id)
        return cls.init_es_vectorstore(knowledge.index_name, **kwargs)

    @classmethod
    def init_knowledge_es_vectorstore_sync(cls, knowledge: Knowledge = None, knowledge_id: int = None,
                                           **kwargs) -> ElasticsearchStore:
        knowledge = cls._get_knowledge_sync(knowledge, knowledge_id)
        return cls.init_es_vectorstore_sync(knowledge.index_name, **kwargs)

    @classmethod
    def get_multi_knowledge_vectorstore(cls, knowledge_ids: list[int], user_name: str = None, check_auth: bool = True,
                                        include_es: bool = True, include_milvus: bool = True) \
            -> Dict[int, Dict[str, VectorStore | Knowledge]]:
        """ get multiple knowledge vectorstore, including milvus and es
            return: {
                knowledge_id: {
                    "knowledge": Knowledge
                    "milvus": Milvus,
                    "es": ElasticsearchStore,
                },
            }
        """
        if not include_es and not include_milvus:
            raise RuntimeError('at least one of include_es and include_milvus must be True')

        if check_auth:
            if not user_name:
                raise RuntimeError('knowledge check auth user_name must be provided')
            knowledge_list = KnowledgeDao.judge_knowledge_permission(user_name, knowledge_ids)
        else:
            knowledge_list = KnowledgeDao.get_list_by_ids(knowledge_ids)
        ret = {}
        for knowledge in knowledge_list:
            ret[knowledge.id] = {
                "milvus": None,
                "es": None,
            }
            if include_milvus:
                vectorstore = cls.init_knowledge_milvus_vectorstore_sync(knowledge)
                ret[knowledge.id]["milvus"] = vectorstore
            if include_es:
                es_vectorstore = cls.init_knowledge_es_vectorstore_sync(knowledge)
                ret[knowledge.id]["es"] = es_vectorstore
        return ret

    @classmethod
    def init_milvus_vectorstore(cls, collection_name: str, embeddings: Embeddings, **kwargs) -> Milvus:
        """ init milvus vectorstore by collection name and model id """
        return MilvusFactory.init_vectorstore(collection_name, embeddings, **kwargs)

    @classmethod
    def init_es_vectorstore(cls, index_name: str, **kwargs) -> AsyncElasticsearchStore:
        """ init es vectorstore by index name """
        return ElasticsearchFactory.init_vectorstore(index_name, **kwargs)

    @classmethod
    def init_es_vectorstore_sync(cls, index_name: str, **kwargs) -> ElasticsearchStore:
        """ init es vectorstore by index name """
        return ElasticsearchFactory.init_vectorstore_sync(index_name, **kwargs)
