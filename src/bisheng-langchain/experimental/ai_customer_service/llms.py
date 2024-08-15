import os
from typing import Dict, List

from openai import AsyncAzureOpenAI, AzureOpenAI


def call_openai(model: str, messages: List[Dict[str, str]], **kwargs) -> str:
    client = AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    )
    response = client.chat.completions.create(model=model, messages=messages, **kwargs)
    return response.choices[0].message.content
