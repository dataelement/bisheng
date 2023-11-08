"""Chain that runs an arbitrary python function."""
import logging
from typing import Dict, List, Optional

import openai
from autogen import Agent, GroupChat, GroupChatManager

logger = logging.getLogger(__name__)


class AutoGenGroupChatManager(GroupChatManager):
    """A chat manager agent that can manage a group chat of multiple agents.
    """
    agents: List[Agent]
    max_round: int = 50
    model_name: Optional[str] = 'gpt-4-0613'
    openai_api_key: Optional[str] = ''
    openai_proxy: Optional[str] = ''
    temperature: Optional[int] = 0

    def __init__(
        self,
        agents: List[Agent],
        max_round: int = 50,
        messages: List[Dict] = [],
        model_name: Optional[str] = 'gpt-4-0613',
        openai_api_key: Optional[str] = '',
        openai_proxy: Optional[str] = '',
        temperature: Optional[int] = 0,
        **kwargs,
    ):
        groupchat = GroupChat(agents=agents, messages=messages, max_round=max_round)

        if openai_proxy:
            openai.proxy = {'https': openai_proxy, 'http': openai_proxy}

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
            llm_config=llm_config
        )
