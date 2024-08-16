import re
from collections import defaultdict
from pathlib import Path
from typing import List, Optional

import pandas as pd
import yaml
from langchain_core.output_parsers import JsonOutputParser
from llms import call_openai
from loguru import logger
from openai import OpenAI
from prompt import IC_SYSTEM_MSG
from retrieval_v2 import LlmBasedLayerwiseReranker, VectorSearch
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

config_file = './config.yaml'
with open(config_file) as f:
    CONFIG = yaml.load(f, Loader=yaml.FullLoader)

EMBEDDING_MODEL = SentenceTransformer(
    model_name_or_path=CONFIG['vector_store']['embedding']['model_path'],
)
EMBEDDING_MODEL.to(CONFIG['vector_store']['embedding']['device'])
RERANK_MODEL = LlmBasedLayerwiseReranker(
    model_path=CONFIG['reranker']['model_path'],
    device=CONFIG['reranker']['device'],
)


json_parser = JsonOutputParser()
ID2TYPE = {
    1: "查询报错信息的含义",
    2: "查询报错解决方法",
    3: "查询非报错信息的含义",
    4: "查询操作指引",
    5: "闲聊",
}
TYPE2SLOTS = {
    "查询报错信息的含义": ["报错的操作行为", "报错信息"],
    "查询报错解决方法": ["报错的操作行为", "报错信息"],
    "查询非报错信息的含义": ["想查询的信息"],
    "查询操作指引": ["操作"],
    "闲聊": [],
}
# TYPE2TEMPLATE = {
#     "查询报错信息的含义": "{报错的操作行为}报错: {报错信息}",
#     "查询报错解决方法": "{报错的操作行为}报错: {报错信息}的解决方法",
#     "查询非报错信息的含义": "{想查询的信息}的含义",
#     "查询操作指引": "{操作}的操作方法",
# }

TYPE2TEMPLATE = {
    "查询报错信息的含义": "请帮我查询，当我...时报错信息为: ...的含义",
    "查询报错解决方法": "请帮我查询，当我...时报错信息为: ...的解决方法",
    "查询非报错信息的含义": "请帮我查询...的含义",
    "查询操作指引": "请帮我查询...的操作方法",
}


def get_cls_response():
    CLS_MSG = """请输入您想查询问题的编号：
1. 查询报错信息的含义
2. 查询报错解决方法
3. 查询非报错信息的含义 
4. 查询操作指引 
5. 闲聊

编号：
"""
    user_input = input(CLS_MSG)
    return user_input


def just_chat() -> str:
    messages = [{'role': 'system', 'content': 'You are a helpful assistant.'}]
    print("你好！")
    for i in range(3):
        user_input = input("input: ")
        messages.append({'role': 'user', 'content': user_input})
        assistant_output = call_openai(messages).choices[0].message.content
        messages.append({'role': 'assistant', 'content': assistant_output})
        print(f'用户输入：{user_input}')
        print(f'模型输出：{assistant_output}')
        print('\n')


def intent_classification(query: str, query_type: str, slots: List[str]) -> str:
    question_list = VectorStore.search(query, add_instruction=False, topk=5, threshold=0.6)
    slots_example = {slot: f"{slot}的描述" for slot in slots}
    messages = [
        {
            'role': 'system',
            'content': IC_SYSTEM_MSG.format(
                query=query,
                query_type=query_type,
                slots="、".join(slots),
                # slots_num=len(slots),
                question_list=";\n".join([f"意图{i+1}: {q}" for i, q in enumerate(question_list)]),
                query_format=TYPE2TEMPLATE[query_type],
            ),
        },
        {'role': 'user', 'content': query},
    ]
    # logger.info(f"messages: {messages}")

    assistant_output = call_openai(model='gpt-4o', messages=messages)
    messages.append({'role': 'assistant', 'content': assistant_output})
    if "消除歧义后的问题" in assistant_output:
        parse_result = json_parser.parse(assistant_output)
        return parse_result["消除歧义后的问题"]

    print(f'用户输入：{query}')
    print(f'模型输出：{assistant_output}')
    print('\n')

    while True:
        user_input = input("input: ")
        messages.append({'role': 'user', 'content': user_input})
        assistant_output = call_openai(model='gpt-4o', messages=messages)
        messages.append({'role': 'assistant', 'content': assistant_output})

        if "消除歧义后的问题" in assistant_output:
            parse_result = json_parser.parse(assistant_output)
            return parse_result["消除歧义后的问题"]
        print(f'用户输入：{user_input}')
        print(f'模型输出：{assistant_output}')
        print('\n')


def is_slot_value(query, query_type, solt_name):
    # check_prompt = "请帮我判断“{query}”是否属于用户{query_type}中涉及的“{slot_name}”，如果是，请回复1；如果否，请回复0。仅回复数字即可，不要回复其他内容。"
    check_prompt = "请帮我判断“{query}”是否属于用户{query_type}中涉及的“{slot_name}”，如果是，请回复1；如果否，请回复0。回复数字和你的解释。"
    messages = [
        {
            'role': 'user',
            'content': check_prompt.format(
                query=query,
                query_type=query_type,
                slot_name=solt_name,
            ),
        },
    ]
    assistant_output = call_qwen2_7b(messages).choices[0].message.content
    logger.info(f"is slot value assistant_output: {assistant_output}")
    output = re.findall(r"\d+", assistant_output)
    breakpoint()
    return int(output[0])


def prepare():
    doc_dir = "/public/youjiachen/workspace/移动九天/data/全量-QA问答对"
    docs = []
    for doc in Path(doc_dir).glob("*"):
        df = pd.read_excel(doc)
        titles = df['文章标题'].to_list()
        docs.extend(titles)

    global VectorStore
    VectorStore = VectorSearch(
        embedding_model=EMBEDDING_MODEL,
        store_name=CONFIG['vector_store']['store_name'],
        docs=list(set(docs)),
        drop_old_cache=True,
    )


def main():

    query_dir = "/public/youjiachen/workspace/移动九天/data/造的Q"

    for query_doc in Path(query_dir).glob("*"):

        df = pd.read_excel(query_doc)
        for idx, row in df.iterrows():
            try:
                query = row["只含报错"]
            except:
                continue
            # result = get_cls_response()
            # cls_num = re.findall(r"\d+", result)
            # while (cls_num) == 0 or int(cls_num[0]) not in range(1, 6):
            #     print("请输入正确的编号\n")
            #     result = get_cls_response()
            #     cls_num = re.findall(r"\d+", result)
            cls_num = [1]

            query_type = ID2TYPE.get(int(cls_num[0]), None)
            slots = TYPE2SLOTS.get(query_type, None)
            print(f"query: {query}")
            logger.info(f"query_type: {query_type}")

            if slots:
                final_query = intent_classification(query, query_type, slots)
                logger.info(f"检索的query: {final_query}\n")
                result = VectorStore.search(final_query, add_instruction=False, topk=10, threshold=0.7)
                logger.info(f"检索结果: {result}")
                logger.info(f'标注结果: {row["原文章标题"]}')
                if len(result) == 0:
                    logger.info("没有找到相关问题")
                else:
                    breakpoint()
                    rerank_score, rerank_inds = RERANK_MODEL.rerank([[query, r] for r in result])
                    logger.info(result[rerank_inds])

            else:
                response = just_chat()


if __name__ == '__main__':
    prepare()
    main()
