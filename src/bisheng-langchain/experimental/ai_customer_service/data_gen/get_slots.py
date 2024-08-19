import json
import os
import httpx
from dotenv import load_dotenv
import tqdm

from openai import AzureOpenAI, OpenAI

load_dotenv('.env', override=True)


slots_detenct_prompt = """作为一个意图理解助手, 分析输入的文本，首先对文本进行意图分类然后根据分类的意图提取对应的槽位。

意图类型： 查询报错信息, 查询报错解决方法, 查询操作指引, 查询非报错信息的含义, 原因说明
意图槽位： 操作行为, 报错信息, 查询信息, 事件信息

示例如下:
---
输入: TRI自动换开指令提示"00045- NO VALID FARE FOR INPUT CRITERIA"的解决办法
输出:
意图类型: 查询报错解决方法
操作行为: 执行TRI自动换开指令
报错信息: 00045- NO VALID FARE FOR INPUT CRITERIA

---
输入: 三合一插件打印行程单时报错：009-31-01-10007 IT/RP HAVING PRINTED!NUMBER:身份证号
输出:
意图类型: 查询报错信息
操作行为: 三合一插件打印行程单
报错信息: 009-31-01-10007 IT/RP HAVING PRINTED!NUMBER:身份证号

---
输入: 400验真问题处理的操作方法
输出:
意图类型: 查询操作指引
查询信息: 400验真问题处理

---
输入: 记录中“1A/REJECTED-MESSAGE IGNORED”的含义
输出:
意图类型: 查询非报错信息的含义
查询信息: 录中“1A/REJECTED-MESSAGE IGNORED”的含义

---
输入: 记录中座位被取消（HX）的原因
输出: 
意图类型: 原因说明
事件信息: 记录中座位被取消（HX）

---
输入:
"""


def get_slots(title):
    #   client = OpenAI(
    #     # api_key=os.environ.get("OPENAI_API_KEY"),
    #     base_url="https://cloud.infini-ai.com/maas/qwen2-72b-instruct/nvidia")

    client = AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    )

    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": slots_detenct_prompt},
            {"role": "user", "content": title + "\n输出:\n"},
        ])

    return completion.choices[0].message.content


def batch_process():

    results = []
    titles = open('crs_v1.txt').readlines()
    total_chars = 0
    for title in tqdm.tqdm(titles):
        title = title.strip()
        total_chars += len(title)
        ret = get_slots(title)
        results.append({'question': title, 'answer': ret})

    print('total_chars', total_chars)
    with open('./crs_v1_slots.jsonl', 'w') as f:
        for item in results:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')


batch_process()
