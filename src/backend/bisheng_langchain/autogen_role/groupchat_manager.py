"""Chain that runs an arbitrary python function."""
import logging
from typing import List, Optional

import httpx
from autogen import Agent, GroupChat, GroupChatManager
from langchain.base_language import BaseLanguageModel

from .user import AutoGenUser

logger = logging.getLogger(__name__)


class AutoGenGroupChatManager(GroupChatManager):
    """A chat manager agent that can manage a group chat of multiple agents.
    """

    def __init__(
        self,
        agents: List[Agent],
        max_round: int = 50,
        llm: Optional[BaseLanguageModel] = None,
        model_name: Optional[str] = 'gpt-4-0613',
        openai_api_key: Optional[str] = '',
        openai_api_base: Optional[str] = '',
        openai_proxy: Optional[str] = '',
        temperature: Optional[float] = 0,
        api_type: Optional[str] = None,  # when llm_flag=True, need to set
        api_version: Optional[str] = None,  # when llm_flag=True, need to set
        name: Optional[str] = 'chat_manager',
        system_message: Optional[str] = 'Group chat manager.',
        **kwargs,
    ):
        if not any(isinstance(agent, AutoGenUser) for agent in agents):
            raise Exception('chat_manager must contains AutoGenUser')

        groupchat = GroupChat(agents=agents, messages=[], max_round=max_round)

        config_list = [
            {
                'model': model_name,
                'api_key': openai_api_key,
                'api_base': openai_api_base,
                'api_type': api_type,
                'api_version': api_version,
            },
        ]
        if openai_proxy:
            config_list[0]['http_client'] = httpx.Client(proxies=openai_proxy)
            config_list[0]['http_async_client'] = httpx.AsyncClient(proxies=openai_proxy)

        if llm:
            llm_config = llm
        else:
            llm_config = {
                'seed': 42,  # change the seed for different trials
                'temperature': temperature,
                'config_list': config_list,
                'request_timeout': 120,
            }

        super().__init__(
            groupchat=groupchat,
            llm_config=llm_config,
            name=name,
            system_message=system_message,
        )
