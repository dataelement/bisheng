"""Chain that runs an arbitrary python function."""
import logging
from typing import List, Optional

import openai
from autogen import Agent, GroupChat, GroupChatManager

from .user import AutoGenUser

logger = logging.getLogger(__name__)


class AutoGenGroupChatManager(GroupChatManager):
    """A chat manager agent that can manage a group chat of multiple agents.
    """
    def __init__(
        self,
        agents: List[Agent],
        max_round: int = 50,
        model_name: Optional[str] = 'gpt-4-0613',
        openai_api_key: Optional[str] = '',
        openai_api_base: Optional[str] = '',
        openai_proxy: Optional[str] = '',
        temperature: Optional[float] = 0,
        name: Optional[str] = 'chat_manager',
        system_message: Optional[str] = 'Group chat manager.',
        **kwargs,
    ):
        if not any(isinstance(agent, AutoGenUser) for agent in agents):
            raise Exception('chat_manager must contains AutoGenUser')

        groupchat = GroupChat(agents=agents, messages=[], max_round=max_round)

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
            groupchat=groupchat,
            llm_config=llm_config,
            name=name,
            system_message=system_message,
        )
