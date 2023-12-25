from typing import Optional

import requests

BASE_API_URL = "http://192.168.106.120:3002/api/v1/process"
FLOW_ID = "017ca219-26d2-41fc-b7d5-21c421c4e9d4"
# You can tweak the flow by adding a tweaks dictionary
# e.g {"OpenAI-XXXXX": {"model_name": "gpt-4"}}
TWEAKS = {
    "HostChatGLM2-SN6Vp": {},
    "PromptTemplate-CQ5PK": {},
    "LLMChain-MdnZL": {},
    "HostChatGLM2-iaY18": {},
    "PromptTemplate-2YUBs": {},
    "LLMChain-MDSRT": {},
    "TransformChain-D78Hy": {},
    "PythonFunction-i7b7I": {},
    "TransformChain-WOSA1": {},
    "PythonFunction-fTaID": {},
    "SequentialChain-0q5Dv": {},
    "TransformChain-HatBh": {},
    "PythonFunction-NwGQU": {},
    "TransformChain-XrJ52": {},
    "PythonFunction-ShKVf": {},
    "TransformChain-3DkCb": {},
    "PythonFunction-xWxyZ": {},
    "PythonFunction-HaUbr": {},
    "RuleBasedRouter-zlwHa": {},
    "MultiRuleChain-UgrH6": {},
    "LLMChain-gUBEY": {},
    "HostChatGLM2-pYS1a": {},
    "PromptTemplate-fSg8o": {},
    "LLMChain-iS9KQ": {},
    "HostChatGLM2-1bACd": {},
    "PromptTemplate-wLNHo": {},
    "SequentialChain-6o7Ke": {},
    "TransformChain-FbAIw": {},
    "PythonFunction-RFv1D": {},
    "SequentialChain-p2kYq": {},
    "LLMChain-76ayL": {},
    "HostChatGLM2-pvPII": {},
    "PromptTemplate-kG7Nj": {},
    "TransformChain-05Pdy": {},
    "PythonFunction-hiqa9": {},
    "LLMChain-zz1EQ": {},
    "HostChatGLM2-bAbGr": {},
    "PromptTemplate-qhS4u": {},
    "RuleBasedRouter-zGoZI": {},
    "PythonFunction-ZDkJy": {},
    "MultiRuleChain-CAW1E": {},
    "MultiRuleChain-Pk0Fp": {},
    "RuleBasedRouter-a7iiu": {},
    "PythonFunction-WHrT1": {},
    "TransformChain-2PQLO": {},
    "PythonFunction-GhD4j": {},
    "TransformChain-y3W3B": {},
    "PythonFunction-cTzxs": {},
    "LLMChain-F6OOP": {},
    "HostChatGLM2-O9oPs": {},
    "PromptTemplate-dQmQr": {},
    "SequentialChain-hxR0D": {},
    "RuleBasedRouter-7afs6": {},
    "PythonFunction-JrZRG": {},
    "MultiRuleChain-EBmic": {},
    "LLMChain-1cQo2": {},
    "PromptTemplate-FczEg": {},
    "HostChatGLM2-CECm7": {},
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


import json

from loguru import logger

# Setup any tweaks you want to apply to the flow
from tqdm import tqdm

c_list_question_file = '/home/youjiachen/workspace/FinGLM/data/C-data/C-list-question.json'
oup_file = './bisheng_result.json'

f_out = open(oup_file, 'w')
with open(c_list_question_file, 'r') as f:
    for _line in f:
        line = json.loads(_line)
        query = line['question']
        logger.info(query)
        inputs = {"query": query, "id": "SequentialChain-6o7Ke"}
        res = run_flow(inputs, flow_id=FLOW_ID, tweaks=TWEAKS)
        logger.info(res)
        f_out.write(
            json.dumps(
                {'id': line['id'], 'question': query, 'answer': res['result']['answer']},
                ensure_ascii=False,
            )
            + '\n'
        )
    f_out.close()