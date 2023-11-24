"""Chain that runs an arbitrary python function."""
import logging
from typing import Callable, Dict, Optional

import openai
from autogen import UserProxyAgent

logger = logging.getLogger(__name__)


class AutoGenUserProxyAgent(UserProxyAgent):
    """A proxy agent for the user, that can execute code and provide feedback to the other agents.
    """

    def __init__(
        self,
        name: str,
        max_consecutive_auto_reply: Optional[int] = None,
        human_input_mode: Optional[str] = 'ALWAYS',  # hmean feedback input
        code_execution_flag: Optional[bool] = True,  # code execution
        function_map: Optional[Dict[str, Callable]] = None,  # function call
        llm_flag: Optional[bool] = False,  # llm call
        model_name: Optional[str] = 'gpt-4-0613',  # when llm_flag=True, need to set
        openai_api_key: Optional[str] = '',  # when llm_flag=True, need to set
        openai_api_base: Optional[str] = '',  # when llm_flag=True, need to set
        openai_proxy: Optional[str] = '',  # when llm_flag=True, need to set
        temperature: Optional[float] = 0,  # when llm_flag=True, need to set
        system_message: Optional[str] = '',  # agent system message, llm or group chat manage will use
        is_termination_msg: Optional[Callable[[Dict], bool]] = None,
        **kwargs,
    ):
        is_termination_msg = (
            is_termination_msg if is_termination_msg is not None else (lambda x: x.get("content") == "TERMINATE")
        )

        if code_execution_flag:
            code_execution_config = {
                'work_dir': 'autogen_coding',  # code save path
                'use_docker': False,
            }
        else:
            code_execution_config = False

        if llm_flag:
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
        else:
            llm_config = False

        super().__init__(
            name,
            is_termination_msg=is_termination_msg,
            max_consecutive_auto_reply=max_consecutive_auto_reply,
            human_input_mode=human_input_mode,
            function_map=function_map,
            code_execution_config=code_execution_config,
            llm_config=llm_config,
            system_message=system_message
        )


class AutoGenUser(UserProxyAgent):
    """A proxy agent for the user, that can provide feedback to the other agents.
    """

    def __init__(
        self,
        name: str,
        max_consecutive_auto_reply: Optional[int] = 10,
        human_input_mode: Optional[str] = 'ALWAYS',  # hmean feedback input
        system_message: Optional[str] = '',  # agent system message, llm or group chat manage will use
        is_termination_msg: Optional[Callable[[Dict], bool]] = None,
        **kwargs,
    ):
        is_termination_msg = (
            is_termination_msg if is_termination_msg is not None else (lambda x: x.get('content') == 'TERMINATE')
        )
        code_execution_config = False
        llm_config = False

        super().__init__(
            name,
            is_termination_msg=is_termination_msg,
            max_consecutive_auto_reply=max_consecutive_auto_reply,
            human_input_mode=human_input_mode,
            code_execution_config=code_execution_config,
            llm_config=llm_config,
            system_message=system_message
        )


class AutoGenCoder(UserProxyAgent):
    """A proxy agent for the coder, that can execute code to the other agents.
    """

    def __init__(
        self,
        name: str,
        function_map: Optional[Dict[str, Callable]] = None,  # function call
        system_message: Optional[str] = '',  # agent system message, llm or group chat manage will use
        is_termination_msg: Optional[Callable[[Dict], bool]] = None,
        **kwargs,
    ):
        is_termination_msg = (
            is_termination_msg if is_termination_msg is not None else (lambda x: x.get('content') == 'TERMINATE')
        )
        code_execution_config = {
            'work_dir': 'autogen_coding',  # code save path
            'use_docker': False,
        }
        llm_config = False

        super().__init__(
            name,
            is_termination_msg=is_termination_msg,
            human_input_mode='NEVER',
            function_map=function_map,
            code_execution_config=code_execution_config,
            llm_config=llm_config,
            system_message=system_message
        )
