import json
from langchain_community.utilities.requests import TextRequestsWrapper
from langchain_community.tools.requests.tool import (
    RequestsDeleteTool,
    RequestsGetTool,
    RequestsPatchTool,
    RequestsPostTool,
    RequestsPutTool,
    _parse_input,
)

payload = {
    'model': 'Qwen-14B-Chat',
    'messages': [
        {
            'role': 'system', 
            'content': '你是一个模型助手。'
        },
        {
            'role': 'user',
            'content': '你好'
        }
    ],
    'max_tokens': 1000,
}

data = {
    "url": "http://34.142.164.75:8001/v2.1/models/Qwen-14B-Chat/infer", 
    "data": payload
}

input_text = json.dumps(data)
print('input_text:', input_text)

client = TextRequestsWrapper()
tool = RequestsPostTool(requests_wrapper=client)
output_response = tool.run(input_text)

print('output_response:', output_response)
print(json.loads(output_response))