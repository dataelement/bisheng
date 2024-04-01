import os
import httpx
import re
from langchain_core.language_models.base import LanguageModelLike
from bisheng_langchain.gpts.prompts import ASSISTANT_PROMPT_OPT
from bisheng_langchain.chat_models import ChatQWen
from langchain.chat_models import ChatOpenAI


def parse_markdown(input_str: str) -> str:
    match = re.search(r"```(markdown)?(.*)```", input_str, re.DOTALL)
    if match is None:
        out_str = input_str
    else:
        out_str = match.group(2)

    out_str = out_str.strip()
    out_str = out_str.replace('```', '')
    return out_str


def optimize_assistant_prompt(
    llm: LanguageModelLike,
    assistant_name: str, 
    assistant_description: str,
) -> str:
    """optimize assistant prompt

    Args:
        llm (LanguageModelLike): 
        assistant_name (str): 
        assistant_description (str): 

    Returns:
        assistant_prompt(str): 
    """
    chain = (
        {
            'assistant_name': lambda x: x['assistant_name'],
            'assistant_description': lambda x: x['assistant_description'],
        }
        | ASSISTANT_PROMPT_OPT
        | llm
    )
    chain_output = chain.invoke(
            {
                'assistant_name': assistant_name,
                'assistant_description': assistant_description,
            }
    )
    response = chain_output.content
    assistant_prompt = parse_markdown(response)
    return assistant_prompt


if __name__ == "__main__":
    httpx_client = httpx.Client(proxies=os.getenv('OPENAI_PROXY'))
    llm = ChatOpenAI(model='gpt-3.5-turbo-1106', temperature=0.01, http_client=httpx_client)
    # llm = ChatQWen(model="qwen1.5-72b-chat", temperature=0.01, api_key=os.getenv('QWEN_API_KEY'))
    assistant_name = '旅行助手'
    assistant_description = '1、帮助用户查询旅行信息；2、指定相关的旅行计划和攻略；3、提供旅行中的实时信息。'
    assistant_prompt = optimize_assistant_prompt(llm, assistant_name, assistant_description)
    print(assistant_prompt)

