"""Chain that runs an arbitrary python function."""
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

import openai
from autogen import AssistantAgent

logger = logging.getLogger(__name__)


class AutoGenAssistant(AssistantAgent):
    """Assistant agent, designed to solve a task with LLM.
    """

    DEFAULT_SYSTEM_MESSAGE = """You are a helpful AI assistant.
Solve tasks using your coding and language skills.
In the following cases, suggest python code (in a python coding block) or shell script (in a sh coding block) for the user to execute.
    1. When you need to collect info, use the code to output the info you need, for example, browse or search the web, download/read a file, print the content of a webpage or a file, get the current date/time, check the operating system. After sufficient info is printed and the task is ready to be solved based on your language skill, you can solve the task by yourself.
    2. When you need to perform some task with code, use the code to perform the task and output the result. Finish the task smartly.
Solve the task step by step if you need to. If a plan is not provided, explain your plan first. Be clear which step uses code, and which step uses your language skill.
When using code, you must indicate the script type in the code block. The user cannot provide any other feedback or perform any other action beyond executing the code you suggest. The user can't modify your code. So do not suggest incomplete code which requires users to modify. Don't use a code block if it's not intended to be executed by the user.
If you want the user to save the code in a file before executing it, put # filename: <filename> inside the code block as the first line. Don't include multiple code blocks in one response. Do not ask users to copy and paste the result. Instead, use 'print' function for the output when relevant. Check the execution result returned by the user.
If the result indicates there is an error, fix the error and output the code again. Suggest the full code instead of partial code or code changes. If the error can't be fixed or if the task is not solved even after the code is executed successfully, analyze the problem, revisit your assumption, collect additional info you need, and think of a different approach to try.
When you find an answer, verify the answer carefully. Include verifiable evidence in your response if possible.
Reply "TERMINATE" in the end when everything is done.
    """ # noqa

    def __init__(
        self,
        name: str,
        model_name: Optional[str] = 'gpt-4-0613',  # when llm_flag=True, need to set
        openai_api_key: Optional[str] = '',  # when llm_flag=True, need to set
        openai_api_base: Optional[str] = '',  # when llm_flag=True, need to set
        openai_proxy: Optional[str] = '',  # when llm_flag=True, need to set
        temperature: Optional[float] = 0,  # when llm_flag=True, need to set
        system_message: Optional[str] = DEFAULT_SYSTEM_MESSAGE,  # agent system message, llm or group chat manage will use # noqa
        is_termination_msg: Optional[Callable[[Dict], bool]] = None,
        **kwargs,
    ):
        is_termination_msg = (
            is_termination_msg if is_termination_msg is not None else (lambda x: x.get("content") == "TERMINATE")
        )
        if openai_proxy:
            openai.proxy = {'https': openai_proxy, 'http': openai_proxy}
        if openai_api_base:
            openai.api_base = openai_api_base

        config_list = [
            {
                'model': model_name,
                'api_key': openai_api_key,
            },
        ]
        llm_config = {
            'seed': 42,  # change the seed for different trials
            'temperature': temperature,
            'config_list': config_list,
            'request_timeout': 120,
        }

        super().__init__(
            name,
            llm_config=llm_config,
            system_message=system_message,
            is_termination_msg=is_termination_msg,
            max_consecutive_auto_reply=None,
            human_input_mode="NEVER",
            code_execution_config=False,
        )
