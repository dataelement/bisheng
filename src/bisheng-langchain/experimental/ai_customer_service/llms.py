import os
from typing import Dict, List

from openai import AzureOpenAI, OpenAI


class LLM:
    def __init__(self, mode='qwen') -> None:
        if mode == 'qwen':
            print("Using Qwen2-72B model")
            self.client = OpenAI(
                api_key=os.getenv("QWEN_API_KEY"),
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )

        elif mode == 'openai':
            self.client = AzureOpenAI(
                api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            )

    def chat(
        self,
        input_text: str,
        messages: List[Dict[str, str]],
        # model: str = 'qwen2-72b-instruct',
        model: str = 'gpt-4o',
        **kwargs,
    ) -> str:
        messages.append({'role': 'user', 'content': input_text})
        assistant_output = self._chat(model=model, messages=messages, **kwargs)
        messages.append({'role': 'assistant', 'content': assistant_output})
        return messages

    def _chat(self, model: str, messages: List[Dict[str, str]], **kwargs) -> str:
        response = self.client.chat.completions.create(model=model, messages=messages, **kwargs)
        return response.choices[0].message.content


def call_openai(model: str, messages: List[Dict[str, str]], **kwargs) -> str:
    client = AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    )
    response = client.chat.completions.create(model=model, messages=messages, **kwargs)
    return response.choices[0].message.content


def call_qwen2_7b(messages):
    client = OpenAI(
        api_key="",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    completion = client.chat.completions.create(
        model="qwen2-7b-instruct", messages=messages, temperature=0.8, top_p=0.8
    )
    return completion
