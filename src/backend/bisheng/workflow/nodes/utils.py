from typing import List, Dict, Any

from langchain_core.documents import Document
from loguru import logger

from bisheng.core.ai.rerank.rrf_rerank import RRFRerank
from bisheng.core.vectorstore.multi_retriever import MultiRetriever
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.llm.domain import LLMService
from bisheng.workflow.nodes.base import BaseNode


class RagUtils(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._knowledge_type = self.node_params.get('knowledge', {}).get('type', "knowledge")
        self._knowledge_value = [
            one['key'] for one in self.node_params.get('knowledge', {}).get('value', [])
        ]

        self._advance_kwargs = self.node_params.get('advanced_retrieval_switch', {})
        if self._advance_kwargs:
            self._advance_kwargs = self.node_params.get('advanced_retrieval_switch', {})
            self._knowledge_auth = self._advance_kwargs['user_auth']
            self._max_chunk_size = int(self._advance_kwargs['max_chunk_size'])
            self._keyword_weight = float(self._advance_kwargs['keyword_weight'])
            self._vector_weight = float(self._advance_kwargs['vector_weight'])
            self._rerank_flag = self._advance_kwargs['rerank_flag']
            self._rerank_model_id = self._advance_kwargs['rerank_model']
        else:
            self._knowledge_auth = self.node_params.get('user_auth', False)
            self._max_chunk_size = int(self.node_params.get('max_chunk_size', 15000))
            self._keyword_weight = 0.5
            self._vector_weight = 0.5
            self._rerank_flag = False
            self._rerank_model_id = ''

        self._multi_milvus_retriever = None
        self._multi_es_retriever = None
        self._retriever_kwargs = {"k": 100, "params": {"ef": 110}}
        self._rerank_model = None

    def _run(self, unique_id: str) -> Dict[str, Any]:
        raise NotImplementedError()

    def retrieve_question(self, question: str) -> List[Document]:
        # 1: retrieve documents from multi retrievers
        milvus_docs = []
        es_docs = []
        if self._multi_milvus_retriever:
            milvus_docs = self._multi_milvus_retriever.invoke(question)
        if self._multi_es_retriever:
            es_docs = self._multi_es_retriever.invoke(question)

        logger.debug(f'retrieve es chunks: {es_docs}')
        logger.debug(f'retrieve milvus chunks: {milvus_docs}')
        # 2: merge documents
        rrf_rerank = RRFRerank(retrievers=[self._multi_es_retriever, self._multi_milvus_retriever],
                               weights=[self._keyword_weight, self._vector_weight], remove_zero_score=True)
        finally_docs = rrf_rerank.compress_documents(documents=[es_docs, milvus_docs], query=question)

        logger.debug(f'retrieve rrf chunks: {finally_docs}')
        # 3: rerank documents
        if self._rerank_model:
            finally_docs = self._rerank_model.compress_documents(documents=finally_docs, query=question)
            logger.debug(f'retrieve rerank model chunks: {finally_docs}')

        # 4. limit  by max_chunk_size
        doc_num, doc_content_sum = 0, 0
        for doc in finally_docs:
            doc_content_sum += len(doc.page_content)
            if doc_content_sum > self._max_chunk_size:
                break
            doc_num += 1
        finally_docs = finally_docs[:doc_num]

        logger.debug(f'retrieve finally chunks: {finally_docs}')

        # 4: return dict
        return finally_docs

    def init_user_question(self) -> List[str]:
        # 默认把用户问题都转为字符串
        ret = []
        for one in self.node_params['user_question']:
            ret.append(f"{self.get_other_node_variable(one)}")
        return ret

    def init_rerank_model(self):
        if not self._rerank_flag:
            return
        if self._rerank_model:
            return
        self._rerank_model = LLMService.get_bisheng_rerank_sync(model_id=self._rerank_model_id)

    def init_multi_retriever(self):
        if self._knowledge_type == "knowledge":
            self.init_knowledge_retriever()
        else:
            self.init_file_retriever()

    def init_knowledge_retriever(self):
        """ retriever from knowledge base """
        if self._multi_milvus_retriever or self._multi_es_retriever:
            return
        milvus_vectors, es_vectors = KnowledgeRag.get_multi_knowledge_vectorstore(
            knowledge_ids=self._knowledge_value,
            user_name=self.user_info.user_name,
            check_auth=self._knowledge_auth,
            include_es=self._keyword_weight > 0,
            include_milvus=self._vector_weight > 0,
        )
        if milvus_vectors:
            self._multi_milvus_retriever = MultiRetriever(
                vectors=milvus_vectors,
                search_kwargs=self._retriever_kwargs,
            )
        if es_vectors:
            self._multi_es_retriever = MultiRetriever(
                vectors=es_vectors,
                search_kwargs=self._retriever_kwargs,
            )

    def init_file_retriever(self):
        """ retriever from file user upload """
        file_ids = []
        for one in self._knowledge_value:
            file_metadata = self.get_other_node_variable(one)
            if not file_metadata:
                # 未找到对应的临时文件数据, 用户未上传文件
                continue
            file_ids.append(file_metadata[0]['file_id'])
        if not file_ids:
            self._multi_es_retriever = None
            self._multi_milvus_retriever = None
            return
        embeddings = LLMService.get_knowledge_default_embedding()
        if not embeddings:
            raise Exception('没有配置知识库默认embedding模型')

        # vectorstore use different collection_name for different embedding model
        tmp_collection_name = self.get_milvus_collection_name(getattr(embeddings, 'model_id'))
        milvus_vector = KnowledgeRag.init_milvus_vectorstore(collection_name=tmp_collection_name, embeddings=embeddings)
        milvus_extra = {"expr": f"file_id in {file_ids}"}
        self._multi_es_retriever = milvus_vector.as_retriever(search_kwargs=self._retriever_kwargs | milvus_extra)

        es_extra = {"filter": [{"terms": {"metadata.file_id": file_ids}}]}
        es_vector = KnowledgeRag.init_es_vectorstore(index_name=self.tmp_collection_name)
        self._multi_es_retriever = es_vector.as_retriever(search_kwargs=self._retriever_kwargs | es_extra)
