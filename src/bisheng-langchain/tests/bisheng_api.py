import requests
from typing import Optional

BASE_API_URL = "http://192.168.106.120:3001/api/v1/process"
FLOW_ID = "409dcd96-d31d-4097-a362-0dd1d9f38484"
# You can tweak the flow by adding a tweaks dictionary
# e.g {"OpenAI-XXXXX": {"model_name": "gpt-4"}}
TWEAKS = {
  "Milvus-zfM6N": {'collection_name': 'collection_test_glx'},
  "CombineDocsChain-hUv7V": {},
  "RetrievalQA-mBP3h": {},
  "InputNode-XiX4h": {},
  "ChatOpenAI-UcJv7": {'openai_api_key': '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'},
  "InputFileNode-uQwpc": {'file_path':'/root/.cache/bisheng/409dcd96-d31d-4097-a362-0dd1d9f38484/69a5a5b901a93aa1aad8fec210fd042305b1ced3495e50dda26f5e00bb1cc7bc'},
  "PyPDFLoader-qvZd1": {},
  "RecursiveCharacterTextSplitter-LWp8T": {},
  "OpenAIEmbeddings-PqyK2": {'openai_api_key': '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'}
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

# Setup any tweaks you want to apply to the flow
inputs = {"query": "开始"}
print(run_flow(inputs, flow_id=FLOW_ID, tweaks=TWEAKS))


# from bisheng import load_flow_from_json
# TWEAKS = {
#   "Milvus-zfM6N": {'collection_name': 'collection_test_glx'},
#   "CombineDocsChain-hUv7V": {},
#   "RetrievalQA-mBP3h": {},
#   "InputNode-XiX4h": {},
#   "ChatOpenAI-UcJv7": {'openai_api_key': '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'},
#   "InputFileNode-uQwpc": {'file_path': "/home/gulixin/workspace/bisheng/合同.pdf"},
#   "PyPDFLoader-qvZd1": {},
#   "RecursiveCharacterTextSplitter-LWp8T": {},
#   "OpenAIEmbeddings-PqyK2": {'openai_api_key': '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'}
# }
# flow = load_flow_from_json("/home/gulixin/workspace/bisheng/⭐研报分析-14825-87904.json", tweaks=TWEAKS)
# # Now you can use it like any chain
# inputs = [{"query": "开始"}]
# flow(inputs)