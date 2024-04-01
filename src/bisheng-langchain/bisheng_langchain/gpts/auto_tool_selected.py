import os
import re

import httpx
from bisheng_langchain.chat_models import ChatQWen
from bisheng_langchain.gpts.load_tools import _ALL_TOOLS, load_tools
from dotenv import load_dotenv
from langchain.globals import set_debug
from langchain.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain_community.chat_models.openai import ChatOpenAI
from langchain_core.language_models.base import LanguageModelLike
from loguru import logger

SYS_MSG = """
你是一个善于分析用户需求的专家，你非常擅长根据用户对任务的描述，从你的工具箱中选择合适的工具给用户。

你需要准遵守以下规则：
1. 你需要根据用户输入的任务描述，选择最符合用户需求的工具，不要随意选择工具给用户。
2. 只能从你的工具箱中选择工具，一定不要自己编造工具箱中不存在的工具给用户！
3. 你只需要返回工具的名称，不需要返回工具的描述以及其他额外的信息，返回的格式为：['tool1', 'tool2', 'tool3']。
4. 如果你觉得没有合适的工具，请返回：[]。
5. 你的工具箱中有以下工具，其中tool_name表示这个工具的名字，tool_description表示工具的用途：{tool_pool}。
6. 如果你回答对了，将会获得100块钱的奖励，如果回答错误，将会扣除50块钱。
"""

HUMAN_MSG = """
任务名: {task_name}
任务描述: {task_description}
建议的工具: 
"""


class ToolSelector:
    def __init__(
        self,
        llm: LanguageModelLike,
        system_message: str = SYS_MSG,
        human_message: str = HUMAN_MSG,
    ) -> None:
        self.llm = llm
        self.system_message = system_message
        self.human_message = human_message

    def select(self, task_name, task_description):
        tool_pool, name_map = self.get_tool_infos()
        messages = [
            SystemMessagePromptTemplate.from_template(self.system_message),
            HumanMessagePromptTemplate.from_template(self.human_message),
        ]

        chain = (
            {
                'tool_pool': lambda x: x['tool_pool'],
                'task_name': lambda x: x['task_name'],
                'task_description': lambda x: x['task_description'],
            }
            | ChatPromptTemplate.from_messages(messages)
            | self.llm
        )

        chain_output = chain.invoke(
            {
                'tool_pool': tool_pool,
                'task_name': task_name,
                'task_description': task_description,
            }
        )

        try:
            output = list(map(lambda x: name_map[x], eval(chain_output.content)))
            return output
        except Exception as e:
            print(e)
            return []

    @staticmethod
    def get_tool_infos():
        """
        Get tool information
        Returns:
            list: list of dict, each dict contains tool_name and tool_description
            dict: mapping from tool_name to function_name
        """
        dummy_params = {
            'key': 'xx',
            'proxy': 'http://localhost:8000',
            'url': 'http://localhost:8000',
        }

        x = ['tianyancha.build_header', 'tianyancha.validate_environment', 'macro.get_api_tool']
        for _x in x:
            _ALL_TOOLS.pop(_x)

        tool_params = {}
        name_map = {}
        for name, tool_info in _ALL_TOOLS.items():
            tool_params[name] = {}
            if isinstance(tool_info, tuple):
                tool_func, extra_params = tool_info
                is_none = True
                for p in extra_params:
                    for d_p in dummy_params:
                        if re.search(d_p, p):
                            tool_params[name][p] = dummy_params[d_p]
                            is_none = False
                            break
                    if is_none:
                        tool_params[name][p] = None
            else:
                tool_params[name] = {}
        all_tools = load_tools(tool_params)

        result = []
        for tool, func_name in zip(all_tools, tool_params.keys()):
            result.append({'tool_name': tool.name, 'tool_description': tool.description})
            name_map[tool.name] = func_name

        return result, name_map


if __name__ == '__main__':
    set_debug(True)
    load_dotenv('/app/.env', override=True)
    httpx_client = httpx.Client(proxies=os.getenv('OPENAI_PROXY'))

    # llm = ChatOpenAI(model='gpt-3.5-turbo-1106', temperature=0.0, http_client=httpx_client)
    llm = ChatQWen(model="qwen1.5-72b-chat", temperature=0.0, api_key=os.getenv('QWEN_API_KEY'))
    tool_selector = ToolSelector(llm=llm)

    task_name = '论文助手'
    task_description = "帮助学生写论文，包括润色论文、改写论文以及上网查找相关论文。"
    print(tool_selector.select(task_name, task_description))
