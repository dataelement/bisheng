"""Chain that runs an arbitrary python function."""
import os
import io
import contextlib
import functools
import logging
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

from langchain.callbacks.manager import (
    AsyncCallbackManagerForChainRun,
    CallbackManagerForChainRun,
)
from langchain.chains.base import Chain

from autogen import ConversableAgent
from .user_proxy_agent import AutoGenUserProxyAgent

logger = logging.getLogger(__name__)


class AutoGenChat(Chain):
    """Chain that print the loader output.
    """
    user_proxy_agent: AutoGenUserProxyAgent
    recipient: ConversableAgent

    input_key: str = "chat_topic"  #: :meta private:
    output_key: str = "chat_content"  #: :meta private:

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
            global_chat_messages=global_chat_messages)
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
        self.user_proxy_agent.initiate_chat(self.recipient,
            message=message, global_chat_messages=global_chat_messages)
        # chat_content = io_output.getvalue()
        chat_content = json.dumps(
            global_chat_messages, indent=2, ensure_ascii=False)
        output = {self.output_key: chat_content}
        return output

