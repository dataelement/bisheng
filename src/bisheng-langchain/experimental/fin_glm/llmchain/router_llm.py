import json
from loguru import logger
import time

import requests
from langchain.chains import TransformChain

URL = 'http://192.168.106.12:5001'


def router_llm(inputs: dict) -> dict:
    query = inputs['query']
    model = 'finglm_combine'
    headers = {'Content-Type': 'application/json'}
    content = {
        'model': 'finglm_combine',
        'messages': [
            {'role': 'system', 'content': f'{query}'},
            {'role': 'user', 'content': ''},
        ],
    }

    data = json.dumps(content, ensure_ascii=False).encode('utf-8')
    start = time.time()
    response = requests.post(f"{URL}/v2.1/models/{model}/infer", headers=headers, data=data)
    end = time.time()
    logger.info(f'router_llm time cost: {end - start}')

    # get response content
    response_content = response.json()['choices'][0]['message']['content']
    return {'query_type': response_content}


router_llm_chain = TransformChain(
    input_variables=['query'],
    output_variables=['query_type'],
    transform=router_llm,
)


if __name__ == '__main__':
    import json

    from loguru import logger

    with open('/home/youjiachen/workspace/FinGLM/code/finglm5/serving/test_data/router.json', 'r') as f:
        for line in f:
            data = json.loads(line)
            print(data['question'])
            logger.info(data['type'])
            logger.info(router_llm_chain(data['question'])['query_type'])
