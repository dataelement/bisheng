import json
import math
import os
import time
from typing import List, Optional

import langchain
import pandas as pd
import requests
from bisheng_langchain.retrievers import MixEsVectorRetriever
from bisheng_langchain.vectorstores import ElasticKeywordsSearch
from langchain.docstore.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Milvus
from langchain_openai import AzureOpenAIEmbeddings
from tqdm import tqdm

embeddings = AzureOpenAIEmbeddings(
    deployment="text-embedding-ada-002",
    model="text-embedding-ada-002",
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    openai_api_type="azure",
)
# text = "This is a test query."
# query_result = embeddings.embed_query(text)
# print(query_result)


def upload_q():
    knowledge_id = 3
    file_path = "./意图测试数据-for BiSheng test.xlsx"
    df = pd.read_excel(file_path)
    documents = []
    for idx, row in tqdm(df.iterrows(), total=len(df)):
        query = row['Question1']
        q2 = row['Question2']
        q3 = row['Question3']
        print(q2)
        json_data = {
            "knowledge_id": knowledge_id,
            "documents": [
                {
                    "page_content": q2,
                    "metadata": {"source": f"意图测试数据-for BiSheng test_{idx}_q2.xlsx", "question": query},
                }
            ],
        }

        url = 'http://192.168.106.117:7860/api/v2/filelib/chunks_string'
        resp = requests.post(url=url, json=json_data)
        json_data = {
            "knowledge_id": knowledge_id,
            "documents": [
                {
                    "page_content": q3,
                    "metadata": {"source": f"意图测试数据-for BiSheng test_{idx}_q3.xlsx", "question": query},
                }
            ],
        }

        url = 'http://192.168.106.117:7860/api/v2/filelib/chunks_string'
        resp = requests.post(url=url, json=json_data)
        print(resp.json())


def upload_q_v2():
    knowledge_id = 5
    file_path = "./data/第一批train.csv"
    df = pd.read_csv(file_path)
    for idx, row in tqdm(df.iterrows(), total=len(df)):
        title = row['标题']
        q = row['Question']
        json_data = {
            "knowledge_id": knowledge_id,
            "documents": [
                {
                    "page_content": q,
                    "metadata": {"source": title},
                }
            ],
        }

        url = 'http://192.168.106.117:7860/api/v2/filelib/chunks_string'
        resp = requests.post(url=url, json=json_data)
        print(resp.json())


def data_loader():
    start_time = time.time()
    file_path = "./意图测试数据-for BiSheng test.xlsx"
    df = pd.read_excel(file_path)
    documents = []
    for idx, row in df.iterrows():
        query = row['Question1']
        q2 = row['Question2']
        q3 = row['Question3']

        # documents.append(Document(page_content=q1))
        documents.append(Document(page_content=q2))
        documents.append(Document(page_content=q3))

    print('documents:', len(documents))
    print('load pdf time:', time.time() - start_time)

    # text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=0)
    # split_docs = text_splitter.split_documents(documents)
    # print('split_docs:', len(split_docs))

    start_time = time.time()
    MILVUS_HOST = '192.168.106.116'
    MILVUS_PORT = '19530'
    vector_store = Milvus.from_documents(
        documents=documents,
        embedding=embeddings,
        collection_name="yidong_jiutian",
        drop_old=True,
        connection_args={"host": MILVUS_HOST, "port": MILVUS_PORT},
    )
    print('embedding and vector store time:', time.time() - start_time)

    start_time = time.time()
    ssl_verify = {
        'basic_auth': ("elastic", "oSGL-zVvZ5P3Tm7qkDLC"),
    }
    vector_store = ElasticKeywordsSearch.from_documents(
        documents,
        embeddings,
        elasticsearch_url="http://192.168.106.116:9200",
        index_name="yidong_jiutian",
        drop_old=True,
        ssl_verify=ssl_verify,
    )
    print('keyword store time:', time.time() - start_time)


def multi_retrieval(query):
    MILVUS_HOST = '192.168.106.116'
    MILVUS_PORT = '19530'
    vector_store = Milvus(
        embedding_function=embeddings,
        collection_name="yidong_jiutian",
        connection_args={"host": MILVUS_HOST, "port": MILVUS_PORT},
    )
    vector_retriever = vector_store.as_retriever(search_type="similarity", search_kwargs={"k": 1})

    ssl_verify = {
        'basic_auth': ("elastic", "oSGL-zVvZ5P3Tm7qkDLC"),
    }
    es_store = ElasticKeywordsSearch(
        elasticsearch_url="http://192.168.106.116:9200",
        index_name="yidong_jiutian",
        ssl_verify=ssl_verify,
    )
    keyword_retriever = es_store.as_retriever(search_type="similarity", search_kwargs={"k": 1})

    combine_strategy = 'keyword_front'
    es_vector_retriever = MixEsVectorRetriever(
        vector_retriever=vector_retriever, keyword_retriever=keyword_retriever, combine_strategy=combine_strategy
    )
    print(es_vector_retriever.get_relevant_documents(query), len(es_vector_retriever.get_relevant_documents(query)))
    return es_vector_retriever.get_relevant_documents(query)


def eval_retrieval():
    file_path = "./意图测试数据-for BiSheng test.xlsx"
    df = pd.read_excel(file_path)
    score = 0
    result = []
    for idx, row in tqdm(df.iterrows(), total=len(df)):
        # query = row['标题']
        query = row['Question1']
        q2 = row['Question2']
        q3 = row['Question3']
        retrieval_result = multi_retrieval(query)
        if retrieval_result[0].page_content in [q2, q3]:
            _score = 1
            score += 1
        else:
            _score = 0
            score += 0
        # for i in retrieval_result:
        #     if i.page_content in [q2, q3]:
        #         _score = 1
        #         score += 1
        #         break
        #     else:
        #         _score = 0
        #         score += 0
        result.append(
            {
                'query': query,
                'labels': [q2, q3],
                'predict': retrieval_result[0].page_content,
                'score': _score,
            }
        )
    pd.DataFrame(result).to_excel('retrieval_result.xlsx', index=False)
    return score / len(df)


def eval_retrieval_v2():
    BASE_API_URL = "http://192.168.106.117:3001/api/v1/process"
    FLOW_ID = "feab2a59-0e18-481c-a918-607d5c93a56c"
    # You can tweak the flow by adding a tweaks dictionary
    # e.g {"OpenAI-XXXXX": {"model_name": "gpt-4"}}
    TWEAKS = {
        "MixEsVectorRetriever-5e87b": {},
        "Milvus-4ca68": {},
        "ElasticKeywordsSearch-113b6": {},
        "RetrievalChain-b56c3": {},
        "TransformChain-0edf4": {},
        "SequentialChain-97ad4": {},
        "PythonFunction-6f509": {},
    }

    def run_flow(inputs: dict, flow_id: str, tweaks: Optional[dict] = None) -> dict:
        """
        Run a flow with a given message and optional tweaks.

        :param message: The message to send to the flow
        :param flow_id: The ID of the flow to run
        :param tweaks: Optional tweaks to customize the flow
        :return: The JSON response from the flow
        """
        api_url = f"{BASE_API_URL}/{flow_id}"

        payload = {"inputs": inputs}

        if tweaks:
            payload["tweaks"] = tweaks

        response = requests.post(api_url, json=payload)
        return response.json()

    # Setup any tweaks you want to apply to the flow
    test_df = pd.read_csv('./data/第一批test.csv')
    train_df = pd.read_csv('./data/第一批train.csv')
    result_df = pd.DataFrame(
        columns=[
            'query',
            'labels',
            "label title",
            'vector predict',
            "vector predict title",
            'vector score',
            'keyword predict',
            'keyword predict title',
            'keyword score',
            'score',
        ]
    )
    for idx, row in tqdm(test_df.iterrows(), total=len(test_df)):
        title = row['标题']
        inputs = {"query": row['Question']}
        response = run_flow(inputs, flow_id=FLOW_ID, tweaks=TWEAKS)['data']['result']['output']
        pred = json.loads(response)
        vector_pred = pred['milvus']
        vector_pred_title = train_df[train_df['Question'] == vector_pred]['标题'].values[0]
        keyword_pred = pred['es']
        keyword_pred_title = train_df[train_df['Question'] == keyword_pred]['标题'].values[0]

        result_df.loc[idx, 'query'] = row['Question']
        result_df.loc[idx, 'vector predict'] = vector_pred
        result_df.loc[idx, 'keyword predict'] = keyword_pred
        try:
            result_df.loc[idx, 'labels'] = str([i for i in train_df[train_df['标题'] == title]['Question'].values])
        except Exception as e:
            print(e)
            result_df.loc[idx, 'labels'] = 'Train中找不到对应的标题'
            continue
        print(f"query: {row['Question']}, title: {title},")
        print(f"labels: {result_df.loc[idx, 'labels']}")
        print(f"vector predict: {vector_pred}, title: {vector_pred_title},")
        print(f"keyword predict: {keyword_pred}, title: {keyword_pred_title},")
        result_df.loc[idx, 'label title'] = title
        result_df.loc[idx, 'vector predict title'] = vector_pred_title
        result_df.loc[idx, 'keyword predict title'] = keyword_pred_title

        if vector_pred_title == title:
            result_df.loc[idx, 'vector score'] = 1
        else:
            result_df.loc[idx, 'vector score'] = 0
        if keyword_pred_title == title:
            result_df.loc[idx, 'keyword score'] = 1
        else:
            result_df.loc[idx, 'keyword score'] = 0
        if vector_pred_title == title or keyword_pred_title == title:
            result_df.loc[idx, 'score'] = 1
        else:
            result_df.loc[idx, 'score'] = 0
    result_df.to_excel('retrieval_result_v2.xlsx', index=False)


if __name__ == '__main__':
    # data_loader()
    # print(eval_retrieval())
    # upload_q()

    # upload_q_v2()
    eval_retrieval_v2()
