from typing import Dict, Iterable, List, Optional, Sequence

from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from langchain_elasticsearch import AsyncElasticsearchStore, ElasticsearchStore
from langchain_milvus import Milvus

from bisheng.common.errcode.http_error import NotFoundError
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao
from bisheng.knowledge.rag.elasticsearch_factory import ElasticsearchFactory
from bisheng.knowledge.rag.milvus_factory import MilvusFactory
from bisheng.llm.domain import LLMService


ROOT_TENANT_ID = 1


class KnowledgeRag:
    """ initialize knowledge rag components """

    # ── F017 AC-06: Milvus / ES fallback helpers ──────────────────

    @classmethod
    async def aexpand_with_root_shared(
        cls,
        knowledge_ids: Sequence[int],
        *,
        leaf_tenant_id: Optional[int] = None,
    ) -> List[int]:
        """Return ``knowledge_ids`` plus every Root-shared knowledge id the
        caller can see (``tenant_id=1 AND is_shared=1``).

        Used at the retrieval layer so a Child-tenant conversation can
        cross-search its own collections + the Root-shared knowledge the
        tenant has been granted via F017 FGA tuples. Call this *before*
        ``get_multi_knowledge_vectorstore_sync`` when the caller needs
        the "Child + Root-shared" union (spec §5.3 Milvus fallback).

        No-ops (returns the input unchanged) when:
          - ``leaf_tenant_id`` is Root (already sees every Root knowledge)
          - multi_tenant is disabled
          - there are no Root-shared knowledge rows matching

        Dedups by id; preserves the caller's order for the original ids
        and appends the new Root-shared ids at the tail.
        """
        base_ids = list(dict.fromkeys(int(k) for k in knowledge_ids))
        if leaf_tenant_id is None:
            try:
                from bisheng.core.context.tenant import get_current_tenant_id
                leaf_tenant_id = get_current_tenant_id()
            except Exception:
                leaf_tenant_id = None
        if leaf_tenant_id is None or leaf_tenant_id == ROOT_TENANT_ID:
            return base_ids

        try:
            from bisheng.common.services.config_service import settings
            if not getattr(getattr(settings, 'multi_tenant', None), 'enabled', False):
                return base_ids
        except Exception:
            return base_ids

        root_shared = await cls._afetch_root_shared_knowledge_ids()
        if not root_shared:
            return base_ids
        seen = set(base_ids)
        for kid in root_shared:
            if kid not in seen:
                seen.add(kid)
                base_ids.append(kid)
        return base_ids

    @classmethod
    async def _afetch_root_shared_knowledge_ids(cls) -> List[int]:
        """Fetch all Root knowledge ids that are currently shared
        (``is_shared=1``). Query the ``knowledge`` table directly with a
        bypass_tenant_filter so the ORM's auto-inject does not filter them
        out for a Child caller.
        """
        from sqlalchemy import text as sa_text

        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.core.database import get_async_db_session

        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.exec(sa_text(
                    'SELECT id FROM knowledge '
                    'WHERE tenant_id = :t AND is_shared = 1'
                ).bindparams(t=ROOT_TENANT_ID))
                rows = result.all()
        return [int(r[0]) if isinstance(r, tuple) else int(r) for r in rows]

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
    async def init_knowledge_milvus_vectorstore(cls, invoke_user_id: int, knowledge: Knowledge = None,
                                                knowledge_id: int = None, embeddings=None, **kwargs) -> Milvus:
        knowledge = await cls._get_knowledge(knowledge, knowledge_id)
        if embeddings is None:
            embeddings = await LLMService.get_bisheng_knowledge_embedding(model_id=int(knowledge.model),
                                                                          invoke_user_id=invoke_user_id)
        return cls.init_milvus_vectorstore(knowledge.collection_name, embeddings, **kwargs)

    @classmethod
    def init_knowledge_milvus_vectorstore_sync(cls, invoke_user_id: int, knowledge: Knowledge = None,
                                               knowledge_id: int = None, embeddings=None, **kwargs) -> Milvus:
        knowledge = cls._get_knowledge_sync(knowledge, knowledge_id)
        if embeddings is None:
            embeddings = LLMService.get_bisheng_knowledge_embedding_sync(model_id=int(knowledge.model),
                                                                         invoke_user_id=invoke_user_id)
        return cls.init_milvus_vectorstore(knowledge.collection_name, embeddings, **kwargs)

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
    def get_multi_knowledge_vectorstore_sync(cls, invoke_user_id: int, knowledge_ids: list[int], user_name: str = None,
                                             check_auth: bool = True, include_es: bool = True,
                                             include_milvus: bool = True) \
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
                "knowledge": knowledge,
                "milvus": None,
                "es": None,
            }
            if include_milvus:
                vectorstore = cls.init_knowledge_milvus_vectorstore_sync(invoke_user_id, knowledge)
                ret[knowledge.id]["milvus"] = vectorstore
            if include_es:
                es_vectorstore = cls.init_knowledge_es_vectorstore_sync(knowledge)
                ret[knowledge.id]["es"] = es_vectorstore
        return ret

    @classmethod
    async def get_multi_knowledge_vectorstore(cls, invoke_user_id: int, knowledge_ids: list[int], user_name: str = None,
                                              check_auth: bool = True, include_es: bool = True,
                                              include_milvus: bool = True) \
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

        if knowledge_ids is None or len(knowledge_ids) == 0:
            return {}

        if not include_es and not include_milvus:
            raise RuntimeError('at least one of include_es and include_milvus must be True')
        if check_auth:
            if not user_name:
                raise RuntimeError('knowledge check auth user_name must be provided')
            knowledge_list = await KnowledgeDao.ajudge_knowledge_permission(user_name, knowledge_ids)
        else:
            knowledge_list = await KnowledgeDao.aget_list_by_ids(knowledge_ids)
        ret = {}
        for knowledge in knowledge_list:
            ret[knowledge.id] = {
                "knowledge": knowledge,
                "milvus": None,
                "es": None,
            }
            if include_milvus:
                vectorstore = await cls.init_knowledge_milvus_vectorstore(invoke_user_id, knowledge)
                ret[knowledge.id]["milvus"] = vectorstore
            if include_es:
                es_vectorstore = await cls.init_knowledge_es_vectorstore(knowledge)
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
