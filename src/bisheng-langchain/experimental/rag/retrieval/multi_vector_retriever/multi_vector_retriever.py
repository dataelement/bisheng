import json
import os
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import httpx
import pandas as pd
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseLanguageModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.pydantic_v1 import Field
from loguru import logger
from tqdm import tqdm

import llama_index
from langchain.chains.question_answering import load_qa_chain
from langchain.chat_models import ChatOpenAI
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.output_parsers.openai_functions import JsonKeyOutputFunctionsParser
from langchain.retrievers.multi_vector import MultiVectorRetriever, SearchType
from langchain.schema import Document
from langchain.storage import InMemoryByteStore
from langchain.text_splitter import RecursiveCharacterTextSplitter, TextSplitter
from langchain.vectorstores.milvus import Milvus
from llama_index.schema import NodeWithScore

openai_proxy = os.environ.get('OPENAI_PROXY')
httpx_client = httpx.Client(proxies=openai_proxy)
# httpx_client = httpx.AsyncClient(proxies=openai_proxy)
embedding = OpenAIEmbeddings(model='text-embedding-ada-002', http_client=httpx_client)
llm = ChatOpenAI(model='gpt-4-1106-preview', temperature=0.0, http_client=httpx_client)


@dataclass
class BishengMultiVectorRetriever:
    doc_path: str
    question_file: str
    save_path: str
    retriever_method: str
    child_splitter: TextSplitter
    parent_splitter: TextSplitter

    llm: Optional[BaseLanguageModel] = None
    embedding: Optional[Embeddings] = None
    ensemble_retriever: bool = False  # todo: 支持ensemble_retriever

    id_key: str = 'doc_id'  # small to big index field
    child_chunk_size: int = 512
    parent_chunk_size: int = 1024

    filter_func: Callable = None
    search_kwargs: dict = Field(default_factory=dict)
    """Keyword arguments to pass to the search function."""
    search_type: SearchType = SearchType.similarity
    """Type of search to perform (similarity / mmr)"""

    milvus_connection_args = {'host': '192.168.106.116', 'port': '19530'}
    elasticsearch_url = 'http://192.168.106.116:9200'
    ssl_verify = {'basic_auth': ('elastic', '')}

    qa_chain_type: str = 'stuff'

    def __post_init__(self):
        self.qa_chain = load_qa_chain(llm=self.llm, chain_type=self.qa_chain_type, verbose=False)

    @property
    def _child_splitter(self):
        return self.child_splitter(chunk_size=self.child_chunk_size)

    @property
    def _parent_splitter(self):
        return self.parent_splitter(chunk_size=self.parent_chunk_size)

    def data_loader(
        self,
    ) -> Dict[str, List[Document]]:
        # todo: 支持样本过滤函数传入
        if Path(self.doc_path).suffix == '.json':
            with open(self.doc_path, 'r') as f:
                data = json.load(f)

            result = defaultdict(list)
            for filename, content in data.items():
                result[filename].append(Document(**content))
            return result

    def get_answer(self):
        df = self._validate_excel()
        select_file = set(df['文件名'].to_list())

        all_parent_docs: Dict[str, List[Document]] = self.data_loader()
        all_parent_docs = {k: v for k, v in all_parent_docs.items() if k in select_file}

        for pdf_name, parent_doc in tqdm(all_parent_docs.items()):
            # built retriever
            self.retriever = getattr(self, f'{self.retriever_method}')(parent_doc)
            logger.info(f'{self.retriever_method} built')
            
            # get answer
            idx2question = df[df['文件名'] == pdf_name]['question'].to_dict()
            for idx, question in idx2question.items():
                rel_docs = self.retriever(question)
                source_docs = {d.metadata.get('source') for d in rel_docs}
                logger.info(f'rel_docs: {len(rel_docs)}')
                logger.info(f'source_file: {source_docs}')

                if len(rel_docs) and isinstance(rel_docs[0], NodeWithScore):
                    rel_docs = [Document(page_content=d.text, metadata=d.metadata) for d in rel_docs]

                try:
                    ans = self.qa_chain({'input_documents': rel_docs, 'question': question}, return_only_outputs=True)
                    logger.info(f'ans: {ans}, question: {question}')
                    df.loc[idx, f'{self.retriever_method}_answer'] = ans['output_text']

                except Exception as e:
                    logger.error(f'error in {pdf_name} with question {question}')
                    logger.error(e)
                    df.loc[idx, f'{self.retriever_method}_answer'] = 'error'
        # save
        exp_name = f'exp_{uuid.uuid4()}'
        with open(Path(self.save_path) / f'{exp_name}.json', 'w') as f:
            json.dump(
                {k: v for k, v in params.items() if not isinstance(v, (Callable, Embeddings, BaseLanguageModel))},
                f,
                ensure_ascii=False,
                indent=4,
            )
        df.to_excel(Path(self.save_path) / f'{exp_name}.xlsx', index=False)

    def split_parent_doc_and_built_index(self, parent_doc: List[Document]) -> Tuple[str, Document]:
        splited_parent_docs = self._parent_splitter.split_documents(parent_doc)
        doc_ids = [str(uuid.uuid4()) for _ in splited_parent_docs]
        id_to_par_doc = list(zip(doc_ids, splited_parent_docs))
        return id_to_par_doc

    def smaller_chunks_retriever(self, parent_doc: List[Document]):

        id_to_par_doc = self.split_parent_doc_and_built_index(parent_doc)
        all_sub_docs = []
        for _id, docs in id_to_par_doc:
            sub_docs = self._child_splitter.split_documents([docs])
            for _doc in sub_docs:
                _doc.metadata[self.id_key] = _id
            all_sub_docs.extend(sub_docs)

        filename = parent_doc[0].metadata.get('source')
        collection_name = self._filename_to_collection_name(filename)
        return self._built_retreiver(
            collection_name=collection_name,
            par_docs_with_id=id_to_par_doc,
            child_docs_with_id=all_sub_docs,
        )

    def summary_retriever(self, parent_doc: List[Document]):
        chain = (
            {"doc": lambda x: x.page_content}
            | ChatPromptTemplate.from_template("请帮我总结下列文档:\n\n{doc}")
            | ChatOpenAI(model='gpt-3.5-turbo-0125', temperature=0.0, http_client=httpx_client)
            | StrOutputParser()
        )

        id_to_par_doc = self.split_parent_doc_and_built_index(parent_doc)
        summary_docs = []
        for _id, docs in id_to_par_doc:
            summary = chain.invoke(docs)
            summary_docs.append(
                Document(
                    page_content=summary,
                    metadata={
                        self.id_key: _id,
                        'source': docs.metadata.get('source'),
                    },
                )
            )

        filename = parent_doc[0].metadata.get('source')
        collection_name = self._filename_to_collection_name(filename)
        return self._built_retreiver(
            collection_name=collection_name,
            par_docs_with_id=id_to_par_doc,
            child_docs_with_id=summary_docs,
        )

    def hypothetical_queries_retriever(self, parent_doc: List[Document]):
        functions = [
            {
                "name": "hypothetical_questions",
                "description": "Generate hypothetical questions",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "questions": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["questions"],
                },
            }
        ]

        chain = (
            {"doc": lambda x: x.page_content}
            # Only asking for 3 hypothetical questions, but this could be adjusted
            | ChatPromptTemplate.from_template(
                "Generate a list of exactly 3 hypothetical questions in Chinese that the below document could be used to answer:\n\n{doc}"
            )
            | ChatOpenAI(model='gpt-3.5-turbo-1106', temperature=0.0, http_client=httpx_client).bind(
                functions=functions, function_call={"name": "hypothetical_questions"}
            )
            | JsonKeyOutputFunctionsParser(key_name="questions")
        )

        id_to_par_doc: List[Tuple[str, List[Document]]] = self.split_parent_doc_and_built_index(parent_doc)
        question_docs: List[Document] = []
        for id, doc in id_to_par_doc:
            question_list = chain.invoke(doc)
            question_docs.extend([Document(page_content=s, metadata={self.id_key: id}) for s in question_list])

        filename = parent_doc[0].metadata.get('source')
        collection_name = self._filename_to_collection_name(filename)
        return self._built_retreiver(
            collection_name=collection_name,
            par_docs_with_id=id_to_par_doc,
            child_docs_with_id=question_docs,
        )

    def hybrid_fusion_retriever(self, parent_doc: List[Document]):
        """混合检索+rrf"""
        from hybrid_fusion_pack.base import HybridFusionRetrieverPack

        from llama_index import Document
        from llama_index.embeddings.openai import OpenAIEmbedding
        from llama_index.llms import OpenAI
        from llama_index.node_parser import LangchainNodeParser, SimpleNodeParser

        openai_api_key = os.environ.get('OPENAI_API_KEY', '')
        openai_proxy = os.environ.get('OPENAI_PROXY', '')
        llm = ChatOpenAI(model='gpt-3.5-turbo-1106', temperature=0.0, http_client=httpx_client)
        embed = OpenAIEmbedding(api_key=openai_api_key, http_client=httpx.Client(proxies=openai_proxy))

        documents = [Document(text=i.page_content, metadata=i.metadata) for i in parent_doc]
        node_parser = LangchainNodeParser(RecursiveCharacterTextSplitter(chunk_size=512))
        nodes = node_parser.get_nodes_from_documents(documents)
        hybrid_fusion_pack = HybridFusionRetrieverPack(
            nodes,
            vector_similarity_top_k=6,
            bm25_similarity_top_k=6,
            fusion_similarity_top_k=self.search_kwargs.get('k', 4),
            llm=llm,
            embedding=embed,
        )

        return hybrid_fusion_pack.retrieve

    def _validate_excel(self) -> pd.DataFrame:
        df: pd.DataFrame = pd.read_excel(self.question_file)
        df.dropna(subset=['question', '文件名', 'ground_truths'], inplace=True)
        logger.info(f'question number: {df.shape[0]}')
        return df

    def _filename_to_collection_name(self, filename: str) -> str:
        """文件名需为 144_xxx.pdf，前缀为数字"""
        num = ''.join([chr(int(i) + 65) for i in filename.split('_')[0]])
        collection_name = f'{self.retriever_method}_{num}'
        return collection_name

    def _built_retreiver(
        self,
        collection_name: str,
        par_docs_with_id: List[Tuple[str, Document]],
        child_docs_with_id: List[Document],
    ) -> MultiVectorRetriever:

        vector_store = Milvus(
            embedding_function=self.embedding,
            collection_name=collection_name,
            connection_args=self.milvus_connection_args,
        )
        retriever = MultiVectorRetriever(
            vectorstore=vector_store,
            byte_store=InMemoryByteStore(),
            id_key=self.id_key,
            search_kwargs=self.search_kwargs,
        )
        retriever.vectorstore.add_documents(
            documents=child_docs_with_id,
            embedding=self.embedding,
        )
        retriever.docstore.mset(par_docs_with_id)

        return retriever.get_relevant_documents


if __name__ == '__main__':

    method_list = [
        'smaller_chunks_retriever',
        'summary_retriever',
        'hypothetical_queries_retriever',
        'hybrid_fusion_retriever',
    ]
    for m in method_list:

        params = {
            'retriever_method': m,  # smaller_chunks_retriever / summary_retriever / hypothetical_queries_retriever / hybrid_fusion_retriever
            'doc_path': '/opt/bisheng/src/bisheng-langchain/experimental/rag/data/all_docs.json',
            'question_file': '/opt/bisheng/src/bisheng-langchain/experimental/rag/retrieval/multi_vector_retriever/data/benchmark_gpt4_badcase_less_than_50k.xlsx',
            'save_path': './output',
            'llm': llm,
            'embedding': embedding,
            'search_kwargs': {"k": 6},  # 控制子文档的返回数量
            'child_chunk_size': 216,
            # 'child_chunk_overlap': 0,
            'parent_chunk_size': 1024,
            'child_splitter': RecursiveCharacterTextSplitter,
            'parent_splitter': RecursiveCharacterTextSplitter,
            # todo
            # 'retriever_args': {'child_chunk_size': 256, 'parent_chunk_size': '512', search_kwargs: {"k": 3}, 'vector_similarity_top_k': 2, 'bm25_similarity_top_k': 2, 'fusion_similarity_top_k': 2, 'num_queries': 4, 'documents': None, 'cache_dir': None,},
        }

        bmv_retriver = BishengMultiVectorRetriever(**params)
        bmv_retriver.get_answer()
