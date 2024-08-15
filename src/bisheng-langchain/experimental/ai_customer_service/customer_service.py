import os
import httpx
import gradio as gr
import re
import json
from typing import Optional, Tuple
from langchain_openai import ChatOpenAI
from langchain.chains import LLMChain
from langchain.memory import ConversationBufferMemory
from prompt import intent_detection_prompt
from langchain.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)


openai_api_key = os.environ.get('OPENAI_API_KEY', '')
openai_proxy = os.environ.get('OPENAI_PROXY', '')


def response_parse(json_string: str) -> str:
    print(f'llm response before parse: {json_string}')
    match = re.search(r"```(json)?(.*)```", json_string, re.DOTALL)
    if match is None:
        json_str = ''
    else:
        json_str = match.group(2)

    json_str = json_str.strip()
    json_str = json_str.replace('```', '')

    match = re.search(r"{.*}", json_str, re.DOTALL)
    if match is None:
        json_str = json_str
    else:
        json_str = match.group(0)

    if json_str.endswith('}\n}'):
        json_str = json_str[:-2]
    if json_str.startswith('{\n{'):
        json_str = json_str.replace('{\n{', '{', 1)

    print(f'llm response after parse: {json_str}')
    try:    
        res = json.loads(json_str)
    except:
        res = {}
    return res


def initial_intent_chain():
    intent_prompt = ChatPromptTemplate(
        messages=[
            SystemMessagePromptTemplate.from_template(intent_detection_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            HumanMessagePromptTemplate.from_template("{question}")
        ]
    )

    llm = ChatOpenAI(model="gpt-4-0125-preview", 
                    temperature=0.3,
                    openai_api_key=openai_api_key,
                    http_client=httpx.Client(proxies=openai_proxy),
                    http_async_client=httpx.AsyncClient(proxies=openai_proxy))
    
    memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
    conversation = LLMChain(llm=llm, prompt=intent_prompt, verbose=False, memory=memory)
    return conversation


def predict():
    intent_conversation = initial_intent_chain()
    history = []
    while True:
        user_input = input('user input: ')
        response = intent_conversation({"question": user_input})['text']
        history.append((user_input, response))
        res = response_parse(response)
        if res:
            print('finnal information:', res)
            break
    return history


if __name__ == "__main__":
    """智能客服意图解析多轮引导"""
    history = predict()
    print(history)