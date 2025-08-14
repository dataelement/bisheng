import argparse
import copy
import inspect
import time
import os
from collections import defaultdict

import httpx
import pandas as pd
import yaml
from loguru import logger
from tqdm import tqdm
from bisheng_langchain.retrievers import EnsembleRetriever
from bisheng_langchain.vectorstores import ElasticKeywordsSearch, Milvus
from langchain.chains.question_answering import load_qa_chain
from bisheng_langchain.rag.init_retrievers import (
    BaselineVectorRetriever,
    KeywordRetriever,
    MixRetriever,
    SmallerChunksVectorRetriever,
)
from bisheng_langchain.rag.scoring.ragas_score import RagScore
from bisheng_langchain.rag.utils import import_by_type, import_class


class BishengRagPipeline:

    def __init__(self, yaml_path) -> None:
        self.yaml_path = yaml_path
        with open(self.yaml_path, 'r') as f:
            self.params = yaml.safe_load(f)

        # init data
        self.origin_file_path = self.params['data']['origin_file_path']
        self.question_path = self.params['data']['question']
        self.save_answer_path = self.params['data']['save_answer']

        # init embeddings
        embedding_params = self.params['embedding']
        embedding_object = import_by_type(_type='embeddings', name=embedding_params['type'])
        if embedding_params['type'] == 'OpenAIEmbeddings' and embedding_params['openai_proxy']:
            embedding_params.pop('type')
            self.embeddings = embedding_object(
                http_client=httpx.Client(proxies=embedding_params['openai_proxy']), **embedding_params
            )
        else:
            embedding_params.pop('type')
            self.embeddings = embedding_object(**embedding_params)

        # init llm
        llm_params = self.params['chat_llm']
        llm_object = import_by_type(_type='llms', name=llm_params['type'])
        if llm_params['type'] == 'ChatOpenAI' and llm_params['openai_proxy']:
            llm_params.pop('type')
            self.llm = llm_object(http_client=httpx.Client(proxies=llm_params['openai_proxy']), **llm_params)
        else:
            llm_params.pop('type')
            self.llm = llm_object(**llm_params)

        # milvus
        self.vector_store = Milvus(
            embedding_function=self.embeddings,
            connection_args={
                "host": self.params['milvus']['host'],
                "port": self.params['milvus']['port'],
            },
        )

        # es
        self.keyword_store = ElasticKeywordsSearch(
            index_name='default_es',
            elasticsearch_url=self.params['elasticsearch']['url'],
            ssl_verify=self.params['elasticsearch']['ssl_verify'],
        )

        # init retriever
        retriever_list = []
        retrievers = self.params['retriever']['retrievers']
        for retriever in retrievers:
            retriever_type = retriever.pop('type')
            retriever_params = {
                'vector_store': self.vector_store,
                'keyword_store': self.keyword_store,
                'splitter_kwargs': retriever['splitter'],
                'retrieval_kwargs': retriever['retrieval'],
            }
            retriever_list.append(self._post_init_retriever(retriever_type=retriever_type, **retriever_params))
        self.retriever = EnsembleRetriever(retrievers=retriever_list)

    def _post_init_retriever(self, retriever_type, **kwargs):
        retriever_classes = {
            'KeywordRetriever': KeywordRetriever,
            'BaselineVectorRetriever': BaselineVectorRetriever,
            'MixRetriever': MixRetriever,
            'SmallerChunksVectorRetriever': SmallerChunksVectorRetriever,
        }
        if retriever_type not in retriever_classes:
            raise ValueError(f'Unknown retriever type: {retriever_type}')

        input_kwargs = {}
        splitter_params = kwargs.pop('splitter_kwargs')
        for key, value in splitter_params.items():
            splitter_obj = import_by_type(_type='textsplitters', name=value.pop('type'))
            input_kwargs[key] = splitter_obj(**value)

        retrieval_params = kwargs.pop('retrieval_kwargs')
        for key, value in retrieval_params.items():
            input_kwargs[key] = value

        input_kwargs['vector_store'] = kwargs.pop('vector_store')
        input_kwargs['keyword_store'] = kwargs.pop('keyword_store')

        retriever_class = retriever_classes[retriever_type]
        return retriever_class(**input_kwargs)

    def file2knowledge(self):
        """
        file to knowledge
        """
        df = pd.read_excel(self.question_path)
        if ('文件名' not in df.columns) or ('知识库名' not in df.columns):
            raise Exception(f'文件名 or 知识库名 not in {self.question_path}.')

        loader_params = self.params['loader']
        loader_object = import_by_type(_type='documentloaders', name=loader_params.pop('type'))

        all_questions_info = df.to_dict('records')
        collectionname2filename = defaultdict(set)
        for info in all_questions_info:
            # 存入set，去掉重复的文件名
            collectionname2filename[info['知识库名']].add(info['文件名'])

        for collection_name in tqdm(collectionname2filename):
            all_file_paths = []
            for file_name in collectionname2filename[collection_name]:
                file_path = os.path.join(self.origin_file_path, file_name)
                if not os.path.exists(file_path):
                    raise Exception(f'{file_path} not exists.')
                # file path可以是文件夹或者单个文件
                if os.path.isdir(file_path):
                    # 文件夹包含多个文件
                    all_file_paths.extend(
                        [os.path.join(file_path, name) for name in os.listdir(file_path) if not name.startswith('.')]
                    )
                else:
                    # 单个文件
                    all_file_paths.append(file_path)

            # 当前知识库需要存储的所有文件
            collection_name = f"{collection_name}_{self.params['retriever']['suffix']}"
            for index, each_file_path in enumerate(all_file_paths):
                logger.info(f'each_file_path: {each_file_path}')
                loader = loader_object(
                    file_name=os.path.basename(each_file_path), file_path=each_file_path, **loader_params
                )
                documents = loader.load()
                logger.info(f'documents: {len(documents)}')
                if len(documents[0].page_content) == 0:
                    logger.error(f'{each_file_path} page_content is empty.')

                vector_drop_old = self.params['milvus']['drop_old'] if index == 0 else False
                keyword_drop_old = self.params['elasticsearch']['drop_old'] if index == 0 else False
                for idx, retriever in enumerate(self.retriever.retrievers):
                    retriever.add_documents(documents, f"{collection_name}_{idx}", vector_drop_old)
                    # retriever.add_documents(documents, collection_name, vector_drop_old)

    def retrieval_and_rerank(self, question, collection_name):
        """
        retrieval and rerank
        """
        collection_name = f"{collection_name}_{self.params['retriever']['suffix']}"

        # EnsembleRetriever直接检索召回会默认去重
        # docs = self.retriever.get_relevant_documents(query=question, collection_name=collection_name)
        docs = []
        for idx, retriever in enumerate(self.retriever.retrievers):
            docs.extend(retriever.get_relevant_documents(query=question, collection_name=f"{collection_name}_{idx}"))
            # docs.extend(retriever.get_relevant_documents(query=question, collection_name=collection_name))
        logger.info(f'retrieval docs: {len(docs)}')

        # delete duplicate
        if self.params['post_retrieval']['delete_duplicate']:
            logger.info(f'origin docs: {len(docs)}')
            all_contents = []
            docs_no_dup = []
            for index, doc in enumerate(docs):
                doc_content = doc.page_content
                if doc_content in all_contents:
                    continue
                all_contents.append(doc_content)
                docs_no_dup.append(doc)
            docs = docs_no_dup
            logger.info(f'delete duplicate docs: {len(docs)}')

        # rerank
        if self.params['post_retrieval']['with_rank'] and len(docs):
            if not hasattr(self, 'ranker'):
                rerank_params = self.params['post_retrieval']['rerank']
                rerank_type = rerank_params.pop('type')
                rerank_object = import_class(f'bisheng_langchain.rag.rerank.{rerank_type}')
                self.ranker = rerank_object(**rerank_params)
            docs = getattr(self, 'ranker').sort_and_filter(question, docs)

        return docs

    def load_documents(self, file_name, max_content=100000):
        """
        max_content: max content len of llm
        """
        file_path = os.path.join(self.origin_file_path, file_name)
        if not os.path.exists(file_path):
            raise Exception(f'{file_path} not exists.')
        if os.path.isdir(file_path):
            raise Exception(f'{file_path} is a directory.')

        loader_params = copy.deepcopy(self.params['loader'])
        loader_object = import_by_type(_type='documentloaders', name=loader_params.pop('type'))
        loader = loader_object(file_name=file_name, file_path=file_path, **loader_params)

        documents = loader.load()
        logger.info(f'documents: {len(documents)}, page_content: {len(documents[0].page_content)}')
        for doc in documents:
            doc.page_content = doc.page_content[:max_content]
        return documents

    def question_answering(self):
        """
        question answer over knowledge
        """
        df = pd.read_excel(self.question_path)
        all_questions_info = df.to_dict('records')
        if 'prompt_type' in self.params['generate']:
            prompt_type = self.params['generate']['prompt_type']
            prompt = import_class(f'bisheng_langchain.rag.prompts.{prompt_type}')
        else:
            prompt = None
        qa_chain = load_qa_chain(
            llm=self.llm, chain_type=self.params['generate']['chain_type'], prompt=prompt, verbose=False
        )
        file2docs = dict()
        for questions_info in tqdm(all_questions_info):
            question = questions_info['问题']
            file_name = questions_info['文件名']
            collection_name = questions_info['知识库名']

            if self.params['generate']['with_retrieval']:
                # retrieval and rerank
                docs = self.retrieval_and_rerank(question, collection_name)
            else:
                # load document
                if file_name not in file2docs:
                    docs = self.load_documents(file_name)
                    file2docs[file_name] = docs
                else:
                    docs = file2docs[file_name]

            # question answer
            try:
                ans = qa_chain({"input_documents": docs, "question": question}, return_only_outputs=False)
            except Exception as e:
                logger.error(f'question: {question}\nerror: {e}')
                ans = {'output_text': str(e)}

            # context = '\n\n'.join([doc.page_content for doc in docs])
            # content = prompt.format(context=context, question=question)

            # # for rate_limit
            # time.sleep(15)

            rag_answer = ans['output_text']
            logger.info(f'question: {question}\nans: {rag_answer}\n')
            questions_info['rag_answer'] = rag_answer
            # questions_info['rag_context'] = '\n----------------\n'.join([doc.page_content for doc in docs])
            # questions_info['rag_context'] = content

        df = pd.DataFrame(all_questions_info)
        df.to_excel(self.save_answer_path, index=False)

    def score(self):
        """
        score
        """
        metric_params = self.params['metric']
        if metric_params['type'] == 'bisheng-ragas':
            score_params = {
                'excel_path': self.save_answer_path,
                'save_path': os.path.dirname(self.save_answer_path),
                'question_column': metric_params['question_column'],
                'gt_column': metric_params['gt_column'],
                'answer_column': metric_params['answer_column'],
                'query_type_column': metric_params.get('query_type_column', None),
                'contexts_column': metric_params.get('contexts_column', None),
                'metrics': metric_params['metrics'],
                'batch_size': metric_params['batch_size'],
                'gt_split_column': metric_params.get('gt_split_column', None),
                'whether_gtsplit': metric_params.get('whether_gtsplit', False), # 是否需要模型对gt进行要点拆分
            }
            rag_score = RagScore(**score_params)
            rag_score.score()
        else:
            # todo: 其他评分方法
            pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process some integers.')
    # 添加参数
    parser.add_argument('--mode', type=str, default='qa', help='upload or qa or score')
    parser.add_argument('--params', type=str, default='config/test/baseline_s2b.yaml', help='bisheng rag params')
    # 解析参数
    args = parser.parse_args()

    rag = BishengRagPipeline(args.params)

    if args.mode == 'upload':
        rag.file2knowledge()
    elif args.mode == 'qa':
        rag.question_answering()
    elif args.mode == 'score':
        rag.score()
