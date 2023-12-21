import json

import requests
from langchain.chains import TransformChain

URL = 'http://192.168.106.12:5001'


def normlize_llm(inputs: dict) -> dict:
    sql_res = inputs['sql_res']
    query = inputs['query']
    model = 'finglm_combine'
    headers = {'Content-Type': 'application/json'}
    content = {
        'model': 'router',
        'messages': [
            {'role': 'system', 'content': f"""根据查询结果回答问题。【查询结果】{sql_res}【问题】{query}【回答】"""},
            {'role': 'user', 'content': ''},
        ],
    }

    data = json.dumps(content, ensure_ascii=False).encode('utf-8')
    response = requests.post(f"{URL}/v2.1/models/{model}/infer", headers=headers, data=data)

    # get response content
    response_content = response.json()['choices'][0]['message']['content']
    return {'answer': response_content}


normlize_llm_chain = TransformChain(
    input_variables=['sql_res'],
    output_variables=['answer'],
    transform=normlize_llm,
)


if __name__ == '__main__':
    pass
