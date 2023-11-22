"""Chain that runs an arbitrary python function."""
import functools
import json
import logging
from typing import Any, Dict, List, Optional

from autogen import ConversableAgent
from bisheng_langchain.autogen_role import AutoGenGroupChatManager, AutoGenUser
from langchain.callbacks.manager import AsyncCallbackManagerForChainRun, CallbackManagerForChainRun
from langchain.chains.base import Chain

logger = logging.getLogger(__name__)


class AutoGenChain(Chain):
    """Chain that print the loader output.
    """
    user_proxy_agent: AutoGenUser
    recipient: ConversableAgent

    input_key: str = 'chat_topic'  #: :meta private:

    output_key: str = 'chat_content'  #: :meta private:

    @staticmethod
    @functools.lru_cache
    def _log_once(msg: str) -> None:
        """Log a message once.

        :meta private:
        """
        logger.warning(msg)

    @property
    def input_keys(self) -> List[str]:
        """Expect input keys.

        :meta private:
        """
        return [self.input_key]

    @property
    def output_keys(self) -> List[str]:
        """Return output keys.

        :meta private:
        """
        return [self.output_key]

    def _call(
        self,
        inputs: Dict[str, str],
        run_manager: Optional[CallbackManagerForChainRun] = None,
    ) -> Dict[str, str]:
        message = inputs[self.input_key]
        # io_output = io.StringIO()
        # with contextlib.redirect_stdout(io_output):
        global_chat_messages = []
        self.user_proxy_agent.initiate_chat(self.recipient, message=message,
                                            global_chat_messages=global_chat_messages,
                                            run_manager=run_manager)
        # chat_content = io_output.getvalue()
        chat_content = json.dumps(
            global_chat_messages, indent=2, ensure_ascii=False)
        output = {self.output_key: chat_content}
        return output

    async def _acall(
        self,
        inputs: Dict[str, Any],
        run_manager: Optional[AsyncCallbackManagerForChainRun] = None,
    ) -> Dict[str, Any]:
        message = inputs[self.input_key]
        # io_output = io.StringIO()
        # with contextlib.redirect_stdout(io_output):
        global_chat_messages = []
        self.recipient.stop = False
        await self.user_proxy_agent.a_initiate_chat(self.recipient,
                                                    message=message,
                                                    global_chat_messages=global_chat_messages,
                                                    run_manager=run_manager)
        # chat_content = io_output.getvalue()
        output = {self.output_key: global_chat_messages[-1].get('message'),
                  'intermediate_steps': global_chat_messages}
        return output

    async def stop(self):
        self.recipient.stop = True
        self.user_proxy_agent.event.set()
        self.user_proxy_agent.event.clear()

    async def reset(self):
        if isinstance(self.recipient, AutoGenGroupChatManager):
            self.recipient.reset()

    async def input(self, input: str):
        self.user_proxy_agent.input = input
        self.user_proxy_agent.event.set()
        self.user_proxy_agent.event.clear()
