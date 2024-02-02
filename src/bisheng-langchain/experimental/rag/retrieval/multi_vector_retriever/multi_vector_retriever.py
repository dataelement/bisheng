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

from langchain.chains.question_answering import load_qa_chain
from langchain.chat_models import ChatOpenAI
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.output_parsers.openai_functions import JsonKeyOutputFunctionsParser
from langchain.retrievers.multi_vector import MultiVectorRetriever, SearchType
from langchain.schema import Document
from langchain.storage import InMemoryByteStore
from langchain.text_splitter import RecursiveCharacterTextSplitter, TextSplitter
from langchain.vectorstores.milvus import Milvus

httpx_client = httpx.Client(proxies=os.environ.get('OPENAI_PROXY'))
embeddings = OpenAIEmbeddings(model='text-embedding-ada-002', http_client=httpx_client)
llm = ChatOpenAI(model='gpt-4-1106-preview', temperature=0.0, http_client=httpx_client)


@dataclass
class BishengMultiVectorRetriever:
    '''
    Base class for multi vector retriever
    '''

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

    @property
    def parent_docstore(self):
        return InMemoryByteStore()

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
        '''
        get answer
        '''
        df = self._validate_excel()
        select_file = set(df['文件名'].to_list())

        all_parent_docs: Dict[str, List[Document]] = self.data_loader()
        all_parent_docs = {k: v for k, v in all_parent_docs.items() if k in select_file}

        for pdf_name, parent_doc in tqdm(all_parent_docs.items()):
            par_docs_with_id, child_docs_with_id = getattr(self, f'built_par_child_docs_{self.retriever_method}')(
                parent_doc
            )
            # vectorestore写入
            collection_name = self._filename_to_collection_name(pdf_name)
            vector_store = Milvus(
                embedding_function=self.embedding,
                collection_name=collection_name,
                connection_args=self.milvus_connection_args,
            )
            self.parent_doc_retriever = MultiVectorRetriever(
                vectorstore=vector_store,
                byte_store=self.parent_docstore,
                id_key=self.id_key,
                search_kwargs=self.search_kwargs,
            )
            self.parent_doc_retriever.vectorstore.add_documents(
                documents=child_docs_with_id,
                embedding=self.embedding,
            )
            self.parent_doc_retriever.docstore.mset(par_docs_with_id)

            # 读取问题
            idx2question = df[df['文件名'] == pdf_name]['问题改写'].to_dict()
            for idx, question in idx2question.items():
                rel_docs = self.parent_doc_retriever.get_relevant_documents(question)
                logger.info(f'rel_docs: {len(rel_docs)}')
                source_docs = {d.metadata.get('source') for d in rel_docs}
                logger.info(f'source_file: {source_docs}')

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

    def built_par_child_docs_Base(self, parent_doc: List[Document]) -> Union[Tuple[Any], List[Document]]:
        id_to_par_doc = self.split_parent_doc_and_built_index(parent_doc)
        all_sub_docs = []
        for i, (_id, docs) in enumerate(id_to_par_doc):
            sub_docs = self._child_splitter.split_documents([docs])
            for _doc in sub_docs:
                _doc.metadata[self.id_key] = _id
            all_sub_docs.extend(sub_docs)
        return id_to_par_doc, all_sub_docs

    def built_par_child_docs_Summary(self, parent_doc: List[Document]) -> Union[Tuple[Any], List[Document]]:
        logger.info('built_par_child_docs_Summary')

        chain = (
            {"doc": lambda x: x.page_content}
            | ChatPromptTemplate.from_template("请帮我总结下列文档:\n\n{doc}")
            | llm
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

        return id_to_par_doc, summary_docs

    def built_par_child_docs_Hquery(self, parent_doc: List[Document]) -> Union[Tuple[Any], List[Document]]:
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
            | ChatOpenAI(model='gpt-3.5-turbo-0125', temperature=0.0, http_client=httpx_client).bind(
                functions=functions, function_call={"name": "hypothetical_questions"}
            )
            | JsonKeyOutputFunctionsParser(key_name="questions")
        )

        id_to_par_doc: List[Tuple[str, List[Document]]] = self.split_parent_doc_and_built_index(parent_doc)
        question_docs: List[Document] = []
        for id, doc in id_to_par_doc:
            question_list = chain.invoke(doc)
            question_docs.extend([Document(page_content=s, metadata={self.id_key: id}) for s in question_list])

        return id_to_par_doc, question_docs

    def _validate_excel(self) -> pd.DataFrame:
        df: pd.DataFrame = pd.read_excel(self.question_file)
        df.dropna(subset=['问题改写', '文件名', 'GT'], inplace=True)
        logger.info(f'question number: {df.shape[0]}')
        return df

    def _filename_to_collection_name(self, filename: str) -> str:
        """文件名需为 144_xxx.pdf，前缀为数字"""
        num = ''.join([chr(int(i) + 65) for i in filename.split('_')[0]])
        collection_name = f'{self.retriever_method}_{num}'
        return collection_name


if __name__ == '__main__':

    params = {
        'retriever_method': 'Hquery',
        'doc_path': '/opt/bisheng/src/bisheng-langchain/experimental/rag/data/all_docs.json',
        'question_file': '/opt/bisheng/src/bisheng-langchain/experimental/rag/data/analysis_result/short_doc_gpt4.xlsx',
        'save_path': './output',
        'llm': llm,
        'embedding': embeddings,
        'search_kwargs': {"k": 10},  # 控制子文档的返回数量
        'child_chunk_size': 216,
        'parent_chunk_size': 512,
        'child_splitter': RecursiveCharacterTextSplitter,
        'parent_splitter': RecursiveCharacterTextSplitter,
    }

    bmv_retriver = BaseMultiVectorRetriever(**params)
    bmv_retriver.get_answer()
