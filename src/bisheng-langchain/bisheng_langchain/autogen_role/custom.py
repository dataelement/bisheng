
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from autogen import Agent, ConversableAgent


class AutoGenCustomRole(ConversableAgent):
    """Custom agent that can use langchain agent and chain."""

    def __init__(
        self,
        name: str,
        system_message: str,
        func: Callable[..., str],
        coroutine: Optional[Callable[..., Awaitable[str]]] = None,
        **kwargs,
    ):
        super().__init__(
            name=name,
            system_message=system_message,
            human_input_mode='NEVER',
            code_execution_config=False,
            llm_config=False,
            **kwargs,
        )
        self.func = func
        self.coroutine = coroutine
        self.register_reply(Agent, AutoGenCustomRole.generate_custom_reply)
        self.register_reply(Agent, AutoGenCustomRole.a_generate_custom_reply, is_async=True)

    def generate_custom_reply(
        self,
        messages: Optional[List[Dict]] = None,
        sender: Optional[Agent] = None,
        config: Optional[Any] = None,
        **kwargs,
    ) -> Union[str, Dict, None]:
        if messages is None:
            messages = self._oai_messages[sender]
        message = messages[-1]

        if 'content' in message:
            query = message['content']
            reply = self.func(query)
            if isinstance(reply, dict):
                reply = list(reply.values())
                if reply:
                    reply = str(reply[0])
                else:
                    reply = ''
            return True, reply

        return False, None

    async def a_generate_custom_reply(
        self,
        messages: Optional[List[Dict]] = None,
        sender: Optional[Agent] = None,
        config: Optional[Any] = None,
        **kwargs,
    ) -> Union[str, Dict, None]:
        if messages is None:
            messages = self._oai_messages[sender]
        message = messages[-1]

        if 'content' in message:
            query = message['content']
            if self.coroutine:
                reply = await self.coroutine(query)
            else:
                reply = self.func(query)
            if isinstance(reply, dict):
                reply = list(reply.values())
                if reply:
                    reply = str(reply[0])
                else:
                    reply = ''
            return True, reply

        return False, None
