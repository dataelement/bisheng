import json
from loguru import logger
import os
import re
from pathlib import Path
from typing import Dict, List

import pandas as pd
import yaml
from bisheng_langchain.document_loaders import ElemUnstructuredLoader
from dotenv import load_dotenv
from llms import LLM
from prompt import intent_clarify_prompt, intent_detection_prompt
from retrieval_v2 import LlmBasedLayerwiseReranker, VectorSearch
from sentence_transformers import SentenceTransformer
from utils import response_parse

load_dotenv('.env', override=True)

TYPE2TEMPLATE = {
    "查询报错信息的含义": "请帮我查询，当我...时报错信息为: ...的含义",
    "查询报错解决方法": "请帮我查询，当我...时报错信息为: ...的解决方法",
    "查询非报错信息的含义": "请帮我查询...的含义",
    "查询操作指引": "请帮我查询...的操作方法",
}


def prepare():
    config_file = './config.yaml'
    with open(config_file) as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    embedding = SentenceTransformer(
        model_name_or_path=config['vector_store']['embedding']['model_path'],
    )
    embedding.to(config['vector_store']['embedding']['device'])

    global RERANK_MODEL
    RERANK_MODEL = LlmBasedLayerwiseReranker(
        model_path=config['reranker']['model_path'],
        device=config['reranker']['device'],
    )

    doc_dir = config['data']['doc_dir']
    docs = []
    detail_docs = []
    for doc in Path(doc_dir).glob("*"):
        df = pd.read_excel(doc).dropna(subset=['文章标题']).drop_duplicates(subset=['文章标题'])
        titles = df['文章标题'].to_list()
        docs.extend(titles)
        detail_docs.extend(df.to_dict(orient='records'))

    global VECTOR_STORE
    VECTOR_STORE = VectorSearch(
        embedding_model=embedding,
        store_name=config['vector_store']['store_name'],
        docs=list(set(docs)),
        drop_old_cache=True,
        detail_docs=detail_docs,
    )


def predict():
    llm = LLM(mode='openai')
    history = []
    states = {}

    # 1. 意图分类
    # rounds = 0
    # while True:
    #     if rounds == 0:
    #         intent_cls_messages = [{'role': 'system', 'content': intent_detection_prompt}]
    #         user_input = input('user input: ')
    #     else:
    #         user_input = input('user input: ')
    #     intent_cls_messages = llm.chat(user_input, intent_cls_messages, temperature=0.3)
    #     response = intent_cls_messages[-1]['content']
    #     rounds += 1
    #     history.append((user_input, response))
    #     res = response_parse(response)
    #     if res:
    #         states['intent_cls'] = json.loads(res)['问题类别']
    #         print('finnal information:', res)
    #         break

    # 2. 意图澄清x
    rounds = 0
    while True:
        if rounds == 0:
            user_input = input(
                '请详细描述您的问题，例如您想进行的操作是什么，遇到了什么问题，报错信息是什么？告诉我，我会为您解决: '
            )
            question_list = VECTOR_STORE.search(
                user_input,
                add_instruction=False,
                topk=5,
                threshold=0.6,
            )
            intent_clarify_messages = [
                {
                    'role': 'system',
                    'content': intent_clarify_prompt.format(
                        query=user_input,
                        # query_type=states['intent_cls'],
                        question_list=";\n".join([f"意图{i+1}: {q}" for i, q in enumerate(question_list)]),
                        # query_format=TYPE2TEMPLATE,
                    ),
                }
            ]
        else:
            user_input = input('input: ')
        intent_clarify_messages = llm.chat(user_input, intent_clarify_messages, temperature=0.3)
        response = intent_clarify_messages[-1]['content']
        rounds += 1
        history.append((user_input, response))
        res = response_parse(response)
        if res:
            states['intent_clarify'] = json.loads(res)['消除歧义后的问题']
            logger.info('最终的问题:', states['intent_clarify'])
            break

    # 3. 检索召回
    question = states['intent_clarify']
    embed_result = VECTOR_STORE.search(question, add_instruction=False, topk=10, threshold=0.7)
    if len(embed_result):
        # print(f"检索结果：{embed_result}")
        score, idx = RERANK_MODEL.rerank([[question, r] for r in embed_result])
        answer = list(filter(lambda x: x['文章标题'] == embed_result[idx], VECTOR_STORE.detail_docs))[0]['操作方法']
        logger.info(f"最终答案：{embed_result[idx]}")
        logger.info(f"最终答案：{answer}")
        return {"state": '1', "query": question, "result": {"title": embed_result[idx], "answer": answer}}
    else:
        return {"state": '0', "query": question, "result": "没有找到相关信息"}


if __name__ == "__main__":
    """智能客服意图解析多轮引导"""
    prepare()
    while True:
        pred = predict()
        # print(pred)
