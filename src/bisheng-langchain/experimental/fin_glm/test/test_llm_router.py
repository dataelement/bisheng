from typing import Optional

import requests

BASE_API_URL = "http://192.168.106.120:3002/api/v1/process"
FLOW_ID = "d9c7f1b5-e341-476f-b04a-ae2b1b671a2d"
# You can tweak the flow by adding a tweaks dictionary
# e.g {"OpenAI-XXXXX": {"model_name": "gpt-4"}}
TWEAKS = {"LLMChain-J3biS": {}, "HostChatGLM2-4z978": {}, "PromptTemplate-ghDOs": {}}


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


if __name__ == '__main__':
    import json

    c = 0
    with open('/home/youjiachen/workspace/FinGLM/data/C-data/C-list-question.json', 'r') as f:
        for line in f:
            data = json.loads(line)
            inputs = {"query": data['question']}
            res = run_flow(inputs, flow_id=FLOW_ID, tweaks=TWEAKS)
            print(res)
