import hashlib
import json
import math
import os
import re
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import List, Optional

import pandas as pd
import requests
import torch
import yaml
from loguru import logger
from openai import OpenAI
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
TYPE2TEMPLATE = {
    "查询报错信息的含义": "{报错的操作行为}报错: {报错信息}",
    "查询报错解决方法": "{报错的操作行为}报错: {报错信息}的解决方法",
    "查询非报错信息的含义": "{想查询的信息}的含义",
    "查询操作指引": "{操作}的操作方法",
}


def response_parse(json_string: str) -> str:
    print(f'llm response before parse: {json_string}')
    match = re.search(r"```(json)?(.*)```", json_string, re.DOTALL)
    if match is None:
        json_str = ''
    else:
        json_str = match.group(2)

    json_str = json_str.strip()
    json_str = json_str.replace('```', '')

    match = re.search(r"{.*}", json_str, re.DOTALL)
    if match is None:
        json_str = json_str
    else:
        json_str = match.group(0)

    if json_str.endswith('}\n}'):
        json_str = json_str[:-2]
    if json_str.startswith('{\n{'):
        json_str = json_str.replace('{\n{', '{', 1)

    print(f'llm response after parse: {json_str}')
    return json_str


def call_qwen2_7b(messages):
    client = OpenAI(
        api_key="",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    completion = client.chat.completions.create(
        model="qwen2-7b-instruct", messages=messages, temperature=0.8, top_p=0.8
    )
    return completion


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
        # 将用户问题信息添加到messages列表中
        messages.append({'role': 'user', 'content': user_input})
        assistant_output = call_qwen2_7b(messages).choices[0].message.content
        # 将大模型的回复信息添加到messages列表中
        messages.append({'role': 'assistant', 'content': assistant_output})
        print(f'用户输入：{user_input}')
        print(f'模型输出：{assistant_output}')
        print('\n')


def fill_slots_chat(query: str, query_type: str, slots: List[str]) -> str:
    SLOTS_FILL_MSG = """你是一个专业的航空公司客服人员，用户正在向你咨询“{query_type}”的相关问题，你需要让用户提供“{slots}”这{slots_num}个方面信息，你要做的是：

1. 请根据用户的描述和历史聊天信息，判断上述{slots_num}个方面信息是否全，如果缺少哪一项或者哪几项信息，回复用户缺少部分的信息并让用户提供；
2. 如果用户提供的信息已包含了上述{slots_num}个方面信息，汇总上述信息并回复用户：请用户及时确认信息；
3. 如果用户发现部分信息提供错误，并提出了修改，请以修改后的信息为准，并再次汇总信息回复用户：请用户及时确认信息；
4. 如果用户回复确认了汇总信息没问题，把汇总信息以json格式输出；

json格式如下：
```json
{json_description}
```"""
    slots_example = {slot: f"{slot}的描述" for slot in slots}
    messages = [
        {
            'role': 'system',
            'content': SLOTS_FILL_MSG.format(
                query_type=query_type,
                slots="、".join(slots),
                slots_num=len(slots),
                json_description=json.dumps(slots_example, ensure_ascii=False),
            ),
        },
        {'role': 'user', 'content': query},
    ]
    assistant_output = call_qwen2_7b(messages).choices[0].message.content
    # 将大模型的回复信息添加到messages列表中
    messages.append({'role': 'assistant', 'content': assistant_output})
    try:
        parse_result = response_parse(assistant_output)
        SLOTS.update(parse_result)
    except:
        pass
    print(f'用户输入：{query}')
    print(f'模型输出：{assistant_output}')
    print('\n')

    while not len(SLOTS):
        user_input = input("input: ")
        # 将用户问题信息添加到messages列表中
        messages.append({'role': 'user', 'content': user_input})
        assistant_output = call_qwen2_7b(messages).choices[0].message.content
        # 将大模型的回复信息添加到messages列表中
        messages.append({'role': 'assistant', 'content': assistant_output})
        try:
            parse_result = response_parse(assistant_output)
            SLOTS.update(parse_result)
        except:
            pass
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
        docs=docs,
        drop_old_cache=True,
    )


def main():

    query_dir = "/public/youjiachen/workspace/移动九天/data/造的Q"

    for query_doc in Path(query_dir).glob("*"):
        df = pd.read_excel(query_doc)
        for idx, row in df.iterrows():
            global SLOTS
            SLOTS = {}
            query = row["没有背景信息的问题"]
            result = get_cls_response()
            cls_num = re.findall(r"\d+", result)
            while (cls_num) == 0 or int(cls_num[0]) not in range(1, 6):
                print("请输入正确的编号\n")
                result = get_cls_response()
                cls_num = re.findall(r"\d+", result)

            query_type = ID2TYPE.get(int(cls_num[0]), None)
            slots = TYPE2SLOTS.get(query_type, None)
            print(f"query: {query}")
            logger.info(f"query_type: {query_type}")
            logger.info(f"需填充的槽位: {slots}\n")

            if slots:
                for slot in slots:
                    slot_res = input(f"请填写 “{slot}”:")
                    SLOTS[slot] = slot_res
                template = TYPE2TEMPLATE.get(query_type)
                template = template.format(**SLOTS)
                print(f"检索的query: {template}\n")
                result = VectorStore.search(template, add_instruction=False, topk=10, threshold=0.7)
                if len(result) == 0:
                    logger.info("没有找到相关问题")
                else:
                    breakpoint()
                    rerank_score, rerank_inds = RERANK_MODEL.rerank([[query, r] for r in result], k=3)
                    # logger.info(result[rerank_inds])

            else:
                response = just_chat()
            break
        break


if __name__ == '__main__':
    prepare()
    main()
