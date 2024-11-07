from typing import Any

from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.callback.event import OutputMsgData
from langchain_core.callbacks.base import AsyncCallbackHandler, BaseCallbackHandler
from loguru import logger


class LLMNodeAsyncCallbackHandler(AsyncCallbackHandler):
    """Callback handler for streaming LLM responses."""

    def __init__(self, callback: BaseCallback, unique_id: str, node_id: str):
        self.callback_manager = callback
        self.unique_id = unique_id
        self.node_id = node_id

    async def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        logger.debug(f'on_llm_new_token token={token} kwargs={kwargs}')
        # azure偶尔会返回一个None
        if token is None:
            return

        # 将流式输出内容放入到队列内，以方便中断流式输出后，可以将内容记录到数据库
        self.callback_manager.on_output_msg(
            OutputMsgData(
                node_id=self.node_id,
                msg=token,
                unique_id=self.unique_id,
            ))


class LLMNodeCallbackHandler(BaseCallbackHandler):
    """Callback handler for streaming LLM responses."""

    def __init__(
        self,
        callback: BaseCallback,
        unique_id: str,
        node_id: str,
        output: bool,
        output_key: str,
    ):
        self.callback_manager = callback
        self.unique_id = unique_id
        self.node_id = node_id
        self.output = output
        self.output_key = output_key

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        # azure偶尔会返回一个None
        if token is None:
            return
        logger.info('on_llm_new_token {} token={}', self.output, token)
        if self.output:
            self.callback_manager.on_output_msg(
                OutputMsgData(node_id=self.node_id,
                              msg=token,
                              unique_id=self.unique_id,
                              output_key=self.output_key))
