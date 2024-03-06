import os
import copy
import yaml
import pandas as pd
import httpx
import argparse
from loguru import logger
from tqdm import tqdm
import time
from langchain.vectorstores import Milvus
from bisheng_langchain.vectorstores import ElasticKeywordsSearch
from bisheng_langchain.retrievers import MixEsVectorRetriever
from langchain.chains.question_answering import load_qa_chain
from utils import import_by_type, import_class, import_module
from scoring.ragas_score import RagScore


class BishengRagPipeline():

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
        if embedding_params['type'] == 'OpenAIEmbeddings':
            embedding_params.pop('type')
            self.embeddings = embedding_object(
                http_client=httpx.Client(proxies=embedding_params['openai_proxy']),
                **embedding_params
            )
        else:
            embedding_params.pop('type')
            self.embeddings = embedding_object(**embedding_params)
        
        # init llm
        llm_params = self.params['chat_llm']
        llm_object = import_by_type(_type='llms', name=llm_params['type'])
        if llm_params['type'] == 'ChatOpenAI':
            llm_params.pop('type')
            self.llm = llm_object(
                http_client=httpx.Client(proxies=llm_params['openai_proxy']),
                **llm_params
            )
        else:
            llm_params.pop('type')
            self.llm = llm_object(**llm_params)

    def file2knowledge(self):
        """
        file to knowledge
        """
        df = pd.read_excel(self.question_path)
        if ('文件名' not in df.columns) or ('知识库名' not in df.columns):
            raise Exception(f'文件名 or 知识库名 not in {self.question_path}.')
        all_questions_info = df.to_dict('records')
        filename2collectionname = dict()
        for info in all_questions_info:
            if info['文件名'] not in filename2collectionname:
                filename2collectionname[info['文件名']] = info['知识库名']
         
        # knowledge params
        loader_params = self.params['knowledge']['loader']
        splitter_params = self.params['knowledge']['splitter']
        loader_object = import_by_type(_type='documentloaders', name=loader_params.pop('type'))
        splitter_object = import_by_type(_type='textsplitters', name=splitter_params.pop('type'))

        for file_name in tqdm(filename2collectionname):
            file_path = os.path.join(self.origin_file_path, file_name)
            if not os.path.exists(file_path):
                raise Exception(f'{file_path} not exists.')

            loader = loader_object(file_name=file_name, file_path=file_path, **loader_params)
            documents = loader.load()
            logger.info(f'documents: {len(documents)}')

            text_splitter = splitter_object(**splitter_params)
            split_docs = text_splitter.split_documents(documents)
            for split_doc in split_docs:
                if 'chunk_bboxes' in split_doc.metadata:
                    split_doc.metadata.pop('chunk_bboxes')
            logger.info(f'split_docs: {len(split_docs)}')

            if self.params['knowledge']['save_milvus']:
                collection_name = filename2collectionname[file_name] + '_milvus_' + self.params['knowledge']['suffix']
                vector_store = Milvus.from_documents(
                    split_docs,
                    embedding=self.embeddings,
                    collection_name=collection_name,
                    drop_old=self.params['milvus']['drop_old'],
                    connection_args={"host": self.params['milvus']['host'], "port": self.params['milvus']['port']}
                )

            if self.params['knowledge']['save_es']:
                index_name = filename2collectionname[file_name] + '_es_' + self.params['knowledge']['suffix']
                es_store = ElasticKeywordsSearch.from_documents(
                    split_docs, 
                    self.embeddings, 
                    elasticsearch_url=self.params['elasticsearch']['url'],
                    index_name=index_name,
                    drop_old=self.params['elasticsearch']['drop_old'],
                    ssl_verify=self.params['elasticsearch']['ssl_verify']
                )
            
    def retrieval_and_rerank(self, question, collection_name):
        """
        retrieval and rerank
        """
        # retrieval
        retrieval_params = self.params['retrieval_rerank']['retrieval']
        if retrieval_params['type'] == 'base':
            # base method
            vector_store = Milvus(
                    embedding_function=self.embeddings,
                    collection_name=collection_name + "_milvus_" + self.params['knowledge']['suffix'],
                    connection_args={"host": self.params['milvus']['host'], "port": self.params['milvus']['port']}
            )
            vector_retriever = vector_store.as_retriever(
                    search_type=retrieval_params['search_type'], 
                    search_kwargs={"k": retrieval_params['chunk_num']})
            es_store = ElasticKeywordsSearch(
                    elasticsearch_url=self.params['elasticsearch']['url'],
                    index_name=collection_name + "_es_" + self.params['knowledge']['suffix'],
                    ssl_verify=self.params['elasticsearch']['ssl_verify']
            )
            keyword_retriever = es_store.as_retriever(
                    search_type=retrieval_params['search_type'], 
                    search_kwargs={"k": retrieval_params['chunk_num']})
            if retrieval_params['mode'] == 'vector':
                docs = vector_retriever.get_relevant_documents(question)
            elif retrieval_params['mode'] == 'keyword':
                docs = keyword_retriever.get_relevant_documents(question)
            elif retrieval_params['mode'] == 'hybrid':
                es_vector_retriever = MixEsVectorRetriever(vector_retriever=vector_retriever,
                                                            keyword_retriever=keyword_retriever,
                                                            combine_strategy=retrieval_params['combine_strategy'])
                docs = es_vector_retriever.get_relevant_documents(question)
        else:
            # todo: 其他检索召回方法
            pass        
            
        # delete duplicate
        if self.params['retrieval_rerank']['delete_duplicate']:
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
        if self.params['retrieval_rerank']['with_rank'] and len(docs):
            if not hasattr(self, 'ranker'):
                rerank_params = self.params['retrieval_rerank']['rerank']
                rerank_type = rerank_params.pop('type')
                rerank_object = import_class(f'rerank.rerank.{rerank_type}')
                self.ranker = rerank_object(**rerank_params)
            docs = getattr(self, 'ranker').sort_and_filter(question, docs)
        
        return docs

    def load_documents(self, file_name, max_content=100000):
        file_path = os.path.join(self.origin_file_path, file_name)
        if not os.path.exists(file_path):
            raise Exception(f'{file_path} not exists.')

        loader_params = copy.deepcopy(self.params['knowledge']['loader'])
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
            prompt = import_module(f'from prompts.prompt import {prompt_type}')
        else:
            prompt = None
        qa_chain = load_qa_chain(llm=self.llm, 
                                 chain_type=self.params['generate']['chain_type'], 
                                 prompt=prompt, 
                                 verbose=False)
        file2docs = dict()
        for questions_info in tqdm(all_questions_info):
            question = questions_info['问题']
            file_type = questions_info['文件类型']
            file_name = questions_info['文件名']
            collection_name = questions_info['知识库名']

            if self.params['generate']['with_retrieval']:
                # retrieval and rerank
                docs = self.retrieval_and_rerank(question, collection_name)
            else:
                # load all documents
                if file_name not in file2docs:
                    docs = self.load_documents(file_name)
                    file2docs[file_name] = docs
                else:
                    docs = file2docs[file_name]

            # question answer
            try:
                ans = qa_chain({"input_documents": docs, "question": question}, return_only_outputs=True)
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
                'query_type_column': metric_params['query_type_column'],
                'metrics': metric_params['metrics'],
                'batch_size': metric_params['batch_size'],
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
    parser.add_argument('--params', type=str, default='config/baseline.yaml', help='bisheng rag params')
    # 解析参数
    args = parser.parse_args()

    rag = BishengRagPipeline(args.params)
    if args.mode == 'upload':
        rag.file2knowledge()
    elif args.mode == 'qa':
        rag.question_answering()
    elif args.mode == 'score':
        rag.score()
