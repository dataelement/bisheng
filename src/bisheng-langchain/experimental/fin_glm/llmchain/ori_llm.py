import json
from loguru import logger
import time
import requests
from langchain.chains import TransformChain


def klg_llm_chain_func(inputs: dict) -> dict:
    URL = '192.168.106.12:5001'
    model = 'chatglm2-6b'

    query = inputs['query']
    desc_klg = inputs['desc_klg']
    klg = inputs['klg']
    headers = {'Content-Type': 'application/json'}
    content = {
        'model': 'router',
        'messages': [
            {
                'role': 'system',
                'content': f"""【任务描述】请阅读下列参考文本，回答问题\n【问题】{query}\n【参考文本】来源:{desc_klg}\n{klg}\n【问题】{query}""",
            },
            {'role': 'user', 'content': ''},
        ],
    }
    data = json.dumps(content, ensure_ascii=False).encode('utf-8')
    start = time.time()
    response = requests.post(f"http://{URL}/v2.1/models/{model}/infer", headers=headers, data=data)
    end = time.time()
    logger.info(f'klg_llm time cost: {end - start}')
    return {'answer': response.json()['choices'][0]['message']['content']}


klg_llm_chain = TransformChain(
    input_variables=["query", "desc_klg", "klg"],
    output_variables=["answer"],
    transform=klg_llm_chain_func,
)


def llm_chain_func(inputs: dict) -> dict:
    URL = '192.168.106.12:5001'
    model = 'chatglm2-6b'

    query = inputs['query']
    headers = {'Content-Type': 'application/json'}
    content = {
        'model': 'router',
        'messages': [
            {'role': 'system', 'content': f'{query}'},
            {'role': 'user', 'content': ''},
        ],
    }
    data = json.dumps(content, ensure_ascii=False).encode('utf-8')
    start = time.time()
    response = requests.post(f"http://{URL}/v2.1/models/{model}/infer", headers=headers, data=data)
    end = time.time()
    logger.info(f'llm time cost: {end - start}')
    return {'answer': response.json()['choices'][0]['message']['content']}


llm_chain = TransformChain(
    input_variables=["query"],
    output_variables=["answer"],
    transform=llm_chain_func,
)
