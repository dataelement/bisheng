import json
import time

import requests
from langchain.chains import TransformChain
from loguru import logger

URL = 'http://192.168.106.12:5001'


def type1_nl2sql_llm(inputs: dict) -> dict:
    question = inputs['question']
    cols = inputs['cols']
    model = 'finglm_combine'
    headers = {'Content-Type': 'application/json'}
    content = {
        'model': 'router',
        'messages': [
            {
                'role': 'system',
                'content': f"""
    你的任务是将问题转化为SQL。
    1. SQL语句查询的表名为: big
    2. 涉及到的列名有: {cols}

    【问题】{question}
    【SQL】""",
            },
            {'role': 'user', 'content': ''},
        ],
    }

    data = json.dumps(content, ensure_ascii=False).encode('utf-8')
    start = time.time()
    response = requests.post(f"{URL}/v2.1/models/{model}/infer", headers=headers, data=data)
    end = time.time()
    logger.info(f'sql: {response.json()["choices"][0]["message"]["content"]}')
    logger.info(f'nl2sql time cost: {end-start}')

    response_content = response.json()['choices'][0]['message']['content']
    return {'sql': response_content}


def type2_nl2sql_llm(inputs: dict) -> dict:
    question = inputs['question']
    cols = inputs['cols']
    formula = inputs['formula']
    model = 'finglm_combine'
    headers = {'Content-Type': 'application/json'}
    content = {
        'model': 'router',
        'messages': [
            {
                'role': 'system',
                'content': f"""
    你的任务是将问题转化为SQL。
    1. SQL语句查询的表名为: big
    2. 涉及到的列名有: {cols}
    3. 涉及到的公式有: {formula}

    【问题】{question}
    【SQL】""",
            },
            {'role': 'user', 'content': ''},
        ],
    }

    data = json.dumps(content, ensure_ascii=False).encode('utf-8')
    start = time.time()
    response = requests.post(f"{URL}/v2.1/models/{model}/infer", headers=headers, data=data)
    end = time.time()
    logger.info(f'nl2sql time cost: {end - start}')

    response_content = response.json()['choices'][0]['message']['content']
    return {'sql': response_content}


type1_nl2sql_llm_chain = TransformChain(
    input_variables=['question', 'cols'],
    output_variables=['sql'],
    transform=type1_nl2sql_llm,
)
type2_nl2sql_llm_chain = TransformChain(
    input_variables=['question', 'cols', 'formula'],
    output_variables=['sql'],
    transform=type2_nl2sql_llm,
)

if __name__ == '__main__':
    pass
    # import json

    # from loguru import logger

    # with open('/home/youjiachen/workspace/FinGLM/code/finglm5/serving/test_data/router.json', 'r') as f:
    #     for line in f:
    #         data = json.loads(line)
    #         print(data['question'])
    #         logger.info(data['type'])
    #         logger.info(router(data['question'])['query_type'])
